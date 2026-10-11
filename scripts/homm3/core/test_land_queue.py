"""The landing lock: one holder across worktrees, waiters served in arrival order."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from homm3.core import land_queue

# A lane: queue for the lock, say so, hold it until a line arrives on stdin.
LANE = """
import sys
from pathlib import Path
from homm3.core import land_queue
queue = land_queue.Queue(Path(sys.argv[1]))
info = {"worktree": "/lanes/" + sys.argv[2], "branch": "lane/" + sys.argv[2]}
with queue.turn(info, report=lambda line: print("wait:", line, flush=True), poll=0.02) as turn:
    turn.phase("build")
    print("acquired", sys.argv[2], flush=True)
    sys.stdin.readline()
"""


class LandQueueTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory())) / "homm3-land"
        self.queue = land_queue.Queue(self.dir)

    def lane(self, name):
        process = subprocess.Popen([sys.executable, "-c", LANE, str(self.dir), name],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)

        def reap():
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(reap)
        return process

    def read_until(self, process, prefix):
        for _ in range(200):
            line = process.stdout.readline()
            if not line:
                self.fail(f"lane exited before printing {prefix!r}")
            if line.startswith(prefix):
                return line.strip()
        self.fail(f"no {prefix!r} line")

    def release(self, process):
        process.stdin.write("\n")
        process.stdin.flush()
        process.wait(10)

    def waiting(self):
        return [Path(entry["worktree"]).name for entry in self.queue.status()["waiting"]]

    def wait_for(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        self.fail("condition not reached")

    def test_waiters_are_served_in_arrival_order(self):
        holder = self.lane("first")
        self.assertEqual(self.read_until(holder, "acquired"), "acquired first")
        lanes = {}
        for name in ("a", "b", "c"):
            lanes[name] = self.lane(name)
            self.read_until(lanes[name], "wait:")
            self.wait_for(lambda name=name: self.waiting()[-1:] == [name])
        self.assertEqual(self.waiting(), ["a", "b", "c"])
        self.release(holder)
        for name, rest in (("a", ["b", "c"]), ("b", ["c"]), ("c", [])):
            self.assertEqual(self.read_until(lanes[name], "acquired"), f"acquired {name}")
            self.assertEqual(self.waiting(), rest)
            self.release(lanes[name])
        history = [json.loads(line) for line in
                   self.queue.history_path.read_text().splitlines()]
        self.assertEqual([Path(item["worktree"]).name for item in history],
                         ["first", "a", "b", "c"])
        self.assertTrue(all(item["result"] == "done" for item in history))

    def test_waiter_sees_its_position_and_the_holder(self):
        holder = self.lane("first")
        self.read_until(holder, "acquired")
        waiter = self.lane("second")
        line = self.read_until(waiter, "wait:")
        self.assertIn("position 1 of 1", line)
        self.assertIn(f"first (lane/first) pid {holder.pid}, phase build", line)
        self.release(holder)
        self.read_until(waiter, "wait: landing lock acquired")

    def test_status_names_the_holder_and_phase(self):
        holder = self.lane("first")
        self.read_until(holder, "acquired")
        state = self.queue.status()
        self.assertEqual(state["holder"]["state"], "held")
        self.assertEqual(state["holder"]["pid"], holder.pid)
        self.assertEqual(state["holder"]["phase"], "build")
        rendered = "\n".join(land_queue.render(state))
        self.assertIn(f"holder: first (lane/first) pid {holder.pid} at /lanes/first", rendered)
        self.assertIn("phase build for", rendered)
        self.release(holder)
        state = self.queue.status()
        self.assertEqual(state["holder"]["state"], "free")
        self.assertIn("first (lane/first)", "\n".join(land_queue.render(state)))

    def test_a_killed_holder_is_stale_and_its_lock_is_free(self):
        holder = self.lane("first")
        self.read_until(holder, "acquired")
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        state = self.queue.status()
        self.assertEqual(state["holder"]["state"], "stale")
        self.assertIn("has exited; the kernel released its lock",
                      "\n".join(land_queue.render(state)))
        started = time.monotonic()
        with self.queue.turn({"worktree": "/lanes/next", "branch": "lane/next"},
                             report=lambda line: None, poll=0.02):
            self.assertEqual(self.queue.status()["holder"]["pid"], os.getpid())
        self.assertLess(time.monotonic() - started, 2)

    def test_a_dead_waiter_leaves_the_queue(self):
        holder = self.lane("first")
        self.read_until(holder, "acquired")
        dead = self.lane("dead")
        self.read_until(dead, "wait:")
        live = self.lane("live")
        self.read_until(live, "wait:")
        self.wait_for(lambda: self.waiting() == ["dead", "live"])
        dead.send_signal(signal.SIGKILL)
        dead.wait()
        self.wait_for(lambda: self.waiting() == ["live"])
        self.release(holder)
        self.assertEqual(self.read_until(live, "acquired"), "acquired live")
        self.release(live)

    def test_an_interrupted_waiter_withdraws(self):
        holder = self.lane("first")
        self.read_until(holder, "acquired")
        waiter = self.lane("quitter")
        self.read_until(waiter, "wait:")
        waiter.send_signal(signal.SIGINT)
        waiter.wait(10)
        self.assertEqual(self.waiting(), [])
        self.release(holder)

    def test_a_reused_pid_is_not_alive(self):
        me = {"pid": os.getpid(), "process_start": land_queue.process_start(os.getpid())}
        self.assertTrue(land_queue.alive(me))
        self.assertFalse(land_queue.alive({**me, "process_start": "0"}))
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.assertFalse(land_queue.alive({"pid": gone.pid}))
        self.assertFalse(land_queue.alive(None))

    def test_the_holder_record_goes_with_its_turn(self):
        with self.queue.turn({"worktree": "/lanes/x", "branch": "b"},
                             report=lambda line: None) as turn:
            turn.phase("push")
            record = json.loads(self.queue.holder_path.read_text())
            self.assertEqual((record["phase"], record["pid"]), ("push", os.getpid()))
            turn.record["result"] = "landed"
        self.assertFalse(self.queue.holder_path.exists())
        history = json.loads(self.queue.history_path.read_text().splitlines()[-1])
        self.assertEqual((history["result"], history["phase"]), ("landed", "push"))

    def test_common_dir_is_shared_by_linked_worktrees(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True,
                                           capture_output=True)
        git("init", "-q", "main")
        subprocess.run(["git", "-C", "main", "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "x"], cwd=root, check=True)
        subprocess.run(["git", "-C", "main", "worktree", "add", "-q", "../lane"], cwd=root,
                       check=True)
        self.assertEqual(land_queue.Queue.for_checkout(root / "lane").dir,
                         (root / "main/.git/homm3-land").resolve())
        self.assertEqual(land_queue.Queue.for_checkout(root / "main").dir,
                         (root / "main/.git/homm3-land").resolve())


if __name__ == "__main__":
    unittest.main()
