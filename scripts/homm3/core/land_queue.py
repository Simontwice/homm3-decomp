"""One landing at a time across every worktree of the repository, in arrival order.

`homm3 land` rebases a lane, runs the full gate cycle and pushes. Only the
holder of this lock pushes, so nothing lands between its rebase and its push
and the cycle runs once per turn. The state lives in the repository's common
git directory (`git rev-parse --git-common-dir`), shared by every linked
worktree:

    homm3-land/lock          flock(2) held for the whole turn; the kernel
                             releases it when the holder exits, however it exits
    homm3-land/queue.json    {"next": ticket, "waiting": [entry, ...]}: the
                             waiters in arrival order
    homm3-land/queue.lock    flock guarding queue.json updates (held briefly)
    homm3-land/holder.json   the current holder: worktree, branch, pid, start
                             time, phase
    homm3-land/history.jsonl one line per finished turn

Fairness: a waiter takes the next ticket and appends itself to the queue;
only the queue's head tries the lock, so waiters are served in ticket order
whatever order the kernel would wake them in. A waiter that dies (pid gone,
or the pid reused by a process with another start time) is pruned by the
next waiter that reads the queue. A holder that dies leaves holder.json
behind, but its flock is gone; `status` reports such a record as stale and
the next holder overwrites it.
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

DIR_NAME = "homm3-land"
POLL_SECONDS = 2.0
HISTORY_SHOWN = 5


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def common_dir(cwd: Path) -> Path:
    """The repository's common git directory (shared by linked worktrees)."""
    out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         cwd=cwd, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"not a git checkout: {cwd}: {out.stderr.strip()}")
    return Path(out.stdout.strip())


def process_start(pid: int) -> str | None:
    """The process's start time in clock ticks since boot (Linux), so a reused
    pid is not mistaken for the recorded process; None when it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # Field 2 (comm) may contain spaces; fields after its closing ')' are fixed.
    return stat.rpartition(")")[2].split()[19]


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def alive(record: dict | None) -> bool:
    """Whether the process a record names still runs (same pid, same start)."""
    if not record:
        return False
    try:
        pid = int(record["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    if not pid_alive(pid):
        return False
    recorded = record.get("process_start")
    return recorded is None or process_start(pid) in (None, recorded)


def _write_json(path: Path, value) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def describe(record: dict) -> str:
    """`homm3-dialogs (match/dialogs) pid 1234`"""
    tree = Path(record.get("worktree", "?")).name
    return f"{tree} ({record.get('branch', '?')}) pid {record.get('pid')}"


def clock(stamp: str | None) -> str:
    try:
        return datetime.datetime.fromisoformat(stamp).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "?"


def elapsed(stamp: str | None, until: float | None = None) -> str:
    try:
        start = datetime.datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return "?"
    seconds = max(0, int((until or time.time()) - start))
    return f"{seconds // 60}m{seconds % 60:02d}s"


class Turn:
    """The holder's handle: phase updates go to holder.json for `status`."""

    def __init__(self, queue: "Queue", record: dict):
        self.queue, self.record = queue, record

    def phase(self, name: str) -> None:
        self.record.update(phase=name, phase_started=now())
        _write_json(self.queue.holder_path, self.record)


class Queue:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.lock_path = self.dir / "lock"
        self.queue_path = self.dir / "queue.json"
        self.meta_path = self.dir / "queue.lock"
        self.holder_path = self.dir / "holder.json"
        self.history_path = self.dir / "history.jsonl"

    @classmethod
    def for_checkout(cls, cwd: Path) -> "Queue":
        return cls(common_dir(cwd) / DIR_NAME)

    # ------------------------------------------------------------ queue file

    @contextlib.contextmanager
    def _state(self):
        """queue.json under queue.lock, with dead waiters pruned; saved on exit."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.meta_path, "a+") as meta:
            fcntl.flock(meta, fcntl.LOCK_EX)
            try:
                state = _read_json(self.queue_path, {})
                state.setdefault("next", 1)
                waiting = state.get("waiting") or []
                state["waiting"] = [entry for entry in waiting if alive(entry)]
                yield state
                _write_json(self.queue_path, state)
            finally:
                fcntl.flock(meta, fcntl.LOCK_UN)

    def lock_free(self) -> bool:
        """Whether nobody holds the landing lock (probes it without waiting)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(handle, fcntl.LOCK_UN)
            return True

    # ------------------------------------------------------------ the turn

    @contextlib.contextmanager
    def turn(self, info: dict, *, report=print, poll: float = POLL_SECONDS):
        """Wait in ticket order, then hold the landing lock for the block.

        `info` describes the lane (worktree, branch, command, ...); `report`
        receives one line whenever the waiter's position or the holder changes.
        Yields a Turn whose `phase(name)` updates the visible holder record.
        """
        identity = {"pid": os.getpid(), "process_start": process_start(os.getpid())}
        with self._state() as state:
            ticket = state["next"]
            state["next"] = ticket + 1
            entry = {**info, **identity, "ticket": ticket, "queued": now()}
            state["waiting"].append(entry)
        handle = open(self.lock_path, "a+")
        acquired = False
        waited = time.monotonic()
        shown = None
        try:
            while True:
                with self._state() as state:
                    tickets = [item["ticket"] for item in state["waiting"]]
                    if ticket not in tickets:      # pruned by mistake: rejoin in place
                        state["waiting"].append(entry)
                        state["waiting"].sort(key=lambda item: item["ticket"])
                        tickets = [item["ticket"] for item in state["waiting"]]
                    position = tickets.index(ticket)
                    if position == 0:
                        try:
                            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            acquired = True
                        except BlockingIOError:
                            pass
                    if acquired:
                        state["waiting"] = [item for item in state["waiting"]
                                            if item["ticket"] != ticket]
                        record = {**entry, "started": now(), "phase": "starting",
                                  "phase_started": now()}
                        _write_json(self.holder_path, record)
                        ahead = len(tickets)
                if acquired:
                    break
                holder = _read_json(self.holder_path, None)
                current = describe(holder) if alive(holder) else None
                key = (position, current)
                if key != shown:
                    shown = key
                    who = (f"{current}, phase {holder.get('phase')} since "
                           f"{clock(holder.get('phase_started'))}" if current
                           else "a holder without a record" if not self.lock_free()
                           else "nobody")
                    report(f"waiting for the landing lock: position {position + 1} of "
                           f"{len(tickets)} (ticket {ticket}); holder: {who}")
                time.sleep(poll)
            if shown is not None:
                report(f"landing lock acquired after {time.monotonic() - waited:.0f}s")
            turn = Turn(self, record)
            outcome = {"result": "interrupted"}
            try:
                yield turn
                outcome["result"] = turn.record.get("result", "done")
            except BaseException as exc:
                outcome["result"] = turn.record.get("result") or f"error: {type(exc).__name__}"
                raise
            finally:
                history = {key: turn.record.get(key) for key in
                           ("worktree", "branch", "pid", "ticket", "started", "phase",
                            "dry_run", "log", "pushed")}
                history.update(outcome, finished=now(), waiters_behind=ahead - 1)
                with contextlib.suppress(OSError):
                    with self.history_path.open("a") as stream:
                        stream.write(json.dumps(history, sort_keys=True) + "\n")
                with contextlib.suppress(OSError):
                    if _read_json(self.holder_path, {}).get("ticket") == ticket:
                        self.holder_path.unlink()
        finally:
            if not acquired:
                with contextlib.suppress(OSError):
                    with self._state() as state:
                        state["waiting"] = [item for item in state["waiting"]
                                            if item["ticket"] != ticket]
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    # ------------------------------------------------------------ status

    def status(self) -> dict:
        """Holder (live, stale or none), waiters and recent turns."""
        record = _read_json(self.holder_path, None)
        free = self.lock_free()
        if record and alive(record) and not free:
            holder = {"state": "held", **record}
        elif record:
            holder = {"state": "stale", **record}   # its process exited; the lock is free
        elif not free:
            holder = {"state": "unknown"}           # held, but no record (being written)
        else:
            holder = {"state": "free"}
        with self._state() as state:
            waiting = list(state["waiting"])
        history = []
        with contextlib.suppress(OSError):
            history = [json.loads(line) for line in
                       self.history_path.read_text().splitlines()[-HISTORY_SHOWN:] if line]
        return {"holder": holder, "waiting": waiting, "history": history}


def render(status: dict) -> list[str]:
    holder, lines = status["holder"], []
    state = holder["state"]
    if state == "held":
        lines.append(f"holder: {describe(holder)} at {holder.get('worktree')}")
        lines.append(f"  started {clock(holder.get('started'))} ({elapsed(holder.get('started'))} "
                     f"ago){' [dry run]' if holder.get('dry_run') else ''}; phase "
                     f"{holder.get('phase')} for {elapsed(holder.get('phase_started'))}")
        if holder.get("log"):
            lines.append(f"  log: {holder['log']}")
    elif state == "stale":
        lines.append(f"holder: none (stale record: {describe(holder)} started "
                     f"{clock(holder.get('started'))}, phase {holder.get('phase')}, "
                     "has exited; the kernel released its lock)")
    elif state == "unknown":
        lines.append("holder: a process holds the lock but has not written its record yet")
    else:
        lines.append("holder: none (the landing lock is free)")
    if status["waiting"]:
        lines.append(f"waiting ({len(status['waiting'])}):")
        for position, entry in enumerate(status["waiting"], 1):
            lines.append(f"  {position}. {describe(entry)} since {clock(entry.get('queued'))} "
                         f"({elapsed(entry.get('queued'))})")
    else:
        lines.append("waiting: nobody")
    if status["history"]:
        lines.append("recent turns:")
        for item in status["history"]:
            took = elapsed(item.get("started"), datetime.datetime.fromisoformat(
                item["finished"]).timestamp()) if item.get("finished") else "?"
            lines.append(f"  {clock(item.get('finished'))} {describe(item)}: "
                         f"{item.get('result')} after {took}"
                         f"{' [dry run]' if item.get('dry_run') else ''}")
    return lines
