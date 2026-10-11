"""homm3 land - rebase, gate and fast-forward push one lane at a time.

    homm3 land [--dry-run] [--mac] [--jobs N]
    homm3 land --status [--json]

Lanes edit and measure in their own worktrees. When a lane has commits to
publish, `homm3 land` takes the repository-wide landing lock
(homm3.core.land_queue: an flock in the common git dir, served in arrival
order) and, while holding it:

1. fetches origin and rebases the current branch onto
   origin/decomp-complete-4.0. Conflicts in generated files are resolved the
   way lanes resolve them by hand: score ledgers three ways with
   `homm3 [--image KEY] status merge-baseline`, README score blocks,
   placements tables and build.ninja from origin (the gate cycle regenerates
   them). Any other conflict aborts the rebase and releases the lock;
2. runs the full `homm3 build` (game, h3maped and h3ccmped), checking the
   summary built every pinned image. Its only acceptable failure is an
   editor image's stale placements;
3. runs `homm3 --image KEY placements --write` for every editor image whose
   objects that build compiled, then the full build again when a table
   changed or the first build was not green; that build must be green;
4. runs `homm3 mac build` when the lane's own commits touch the Mac build's
   inputs (`mac_paths`: game unit sources, the game include roots outside
   the editors' trees, config/units.toml, config/mac/), or with --mac;
5. commits the refreshed ledgers, README blocks, placements and cleanliness
   floors as "Refresh scores ... after the rebase" (any other change fails);
6. pushes `git push origin HEAD:decomp-complete-4.0`, a plain fast-forward
   (never forced), and releases the lock.

Only the holder pushes, so nothing can land between its rebase and its push:
the cycle runs once per turn. `--dry-run` does everything but the push (the
rebase and the refresh commit stay in the local branch). Waiters see their
position and the holder; `homm3 land --status` prints the holder (worktree,
branch, pid, start time, phase), the queue and the last turns, and reports a
holder whose process has exited as stale (the kernel has released its lock).

The whole run is logged to build/land/<time>.log (and build/land/latest.log).
A failure exits 1 naming the failing gate.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from homm3.core import common
from homm3.core import land_queue

ROOT = common.HOMM3_DIR
REMOTE = "origin"
BRANCH = "decomp-complete-4.0"
# Files the gate cycle itself rewrites; the refresh commit takes exactly these.
REFRESHED = ("README.md", "build.ninja", "config/match_baseline.tsv",
             "config/match_baseline.*.tsv", "config/retail/*/placements.tsv",
             "config/mac/match_baseline.tsv", "config/mac/match_profiles.tsv",
             "config/cleanliness/baseline.tsv", "config/cleanliness/baseline.*.tsv")
SCORE_BLOCK = re.compile(r"^<!-- ([a-z0-9-]*match-score):(start|end) -->$")


class GateFailed(Exception):
    def __init__(self, gate: str, detail: str = ""):
        super().__init__(gate)
        self.gate, self.detail = gate, detail


# ------------------------------------------------------------------ logging

class Log:
    """Every line goes to the terminal and to build/land/<time>.log."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("a", buffering=1)
        latest = path.with_name("latest.log")
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(path.name)
        except OSError:
            pass

    def __call__(self, message: str) -> None:
        line = f"[land] {message}"
        print(line, flush=True)
        self.stream.write(f"{datetime.datetime.now():%H:%M:%S} {line}\n")

    def raw(self, line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()
        self.stream.write(line)

    def close(self) -> None:
        self.stream.close()


def _environment() -> dict:
    env = dict(os.environ)
    from homm3.core import usage
    event = usage._ACTIVE_EVENT.get()
    if event:
        env["HOMM3_USAGE_PARENT_EVENT_ID"] = event
    env.pop("HOMM3_IMAGE", None)
    return env


def run(log: Log, *command: str, check: str | None = None) -> tuple[int, str]:
    """Run a command in the worktree, streaming its merged output into the log.
    With `check`, a non-zero exit raises GateFailed(check)."""
    log(f"$ {' '.join(command)}")
    lines = []
    with subprocess.Popen(list(command), cwd=ROOT, env=_environment(), text=True,
                          errors="replace", stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as process:
        try:
            for line in process.stdout:
                lines.append(line)
                log.raw(line)
            rc = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    output = "".join(lines)
    if check and rc:
        raise GateFailed(check, f"`{' '.join(command)}` exited {rc}")
    return rc, output


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        raise GateFailed(f"git {args[0]}", (out.stderr or out.stdout).strip())
    return out.stdout


def homm3(*args: str) -> tuple[str, ...]:
    return (sys.executable, "-m", "homm3", *args)


# ------------------------------------------------------------------ build summary

def editor_images() -> list[str]:
    from homm3.core import images
    return images.images(ROOT)[1:]


def _image_line(key: str, text: str) -> str | None:
    """The image's own score line, printed once its compile and delink ran."""
    match = re.search(rf"^\[build\] {re.escape(key)}: (MAX \d+/\d+ functions exact.*)$",
                      text, re.M)
    return match and match.group(1)


def build_problems(output: str, images: list[str]) -> list[str]:
    """Why a full `homm3 build` output does not certify every image."""
    problems = []
    for key in images:
        if re.search(rf"^\[build\] image {re.escape(key)}: SKIPPED", output, re.M):
            problems.append(f"image {key} was skipped")
        elif not re.search(rf"^\[build\] image {re.escape(key)}: building", output, re.M):
            problems.append(f"image {key} was not built (no `image {key}: building` line)")
        elif not re.search(rf"^\[build\] {re.escape(key)}: all gates passed", output, re.M):
            problems.append(f"image {key} did not pass its gates")
    if not re.search(r"^\[build\] all gates passed$", output, re.M):
        failed = re.search(r"^\[build\] FAILED gates \(details above\): (.*)$", output, re.M)
        problems.append("build failed" + (f": {failed.group(1)}" if failed else
                                          " before its summary"))
    return problems


def placements_only(output: str, images: list[str]) -> bool:
    """Whether a full build failed only on editor images' placements tables,
    after compiling and delinking each of them: `placements --write` then
    has real objects to place (never a game-only compile's empty set)."""
    failed = re.search(r"^\[build\] FAILED gates \(details above\): (.*?)"
                       r"(?: \(images NOT built.*)?$", output, re.M)
    if not failed:
        return False
    for item in failed.group(1).split("; "):
        key = item.removeprefix("image ")
        if not item.startswith("image ") or key not in images:
            return False                         # a game gate failed
        gates = re.search(rf"^\[build\] {re.escape(key)}: FAILED gates: (.*)$", output, re.M)
        if not gates or not _image_line(key, output):
            return False                         # the image did not compile/delink
        if any(not gate.startswith("placements") for gate in gates.group(1).split("; ")):
            return False
    return True


def compiled_images(output: str, images: list[str]) -> list[str]:
    return [key for key in images if _image_line(key, output)]


# ------------------------------------------------------------------ Mac relevance

def mac_paths(paths: list[str], root: Path = ROOT) -> list[str]:
    """The changed paths the Mac (CodeWarrior) build compiles or reads.

    `homm3 mac build` compiles every game unit of config/units.toml with
    config/mac/units.toml's flags and the game's include roots (`src`,
    `include` and config/units.toml's [build].includes; homm3.mac.cc_wrap).
    The editors' own trees (src/<dir>, include/<dir> of every other pinned
    image, homm3.core.images.source_dir) are never on that path.
    """
    from homm3 import manifest
    from homm3.core import images
    game = root / "config/units.toml"
    sources = {unit["source"] for unit in manifest.units(game) if "source" in unit}
    roots = ["src", "include", *manifest.load(game).get("build", {}).get("includes", [])]
    foreign = [f"{top}/{images.source_dir(key, root)}/" for key in images.images(root)[1:]
               for top in ("src", "include")]
    relevant = []
    for path in paths:
        if path in sources or path == "config/units.toml" or path.startswith("config/mac/"):
            relevant.append(path)
        elif any(path.startswith(prefix) for prefix in foreign):
            continue
        elif any(path.startswith(directory.rstrip("/") + "/") for directory in roots):
            relevant.append(path)
    return relevant


# ------------------------------------------------------------------ rebase

def _generated(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in REFRESHED)


def score_block_conflicts_only(text: str) -> bool:
    """Whether every conflict hunk of README.md lies inside a generated
    `<!-- *match-score:start/end -->` block (which the build rewrites)."""
    inside = False
    seen = False
    for line in text.splitlines():
        block = SCORE_BLOCK.match(line)
        if block:
            inside = block.group(2) == "start"
        elif line.startswith("<<<<<<<"):
            seen = True
            if not inside:
                return False
    return seen


def resolve_conflict(log: Log, path: str) -> bool:
    """Resolve one conflicted generated file in place; False when it is not
    one the gate cycle regenerates."""
    from homm3.match.merge_baseline import _pick_side
    ledger = re.fullmatch(r"config/match_baseline(?:\.([a-z0-9_]+))?\.tsv", path)
    if ledger:
        image = ledger.group(1)
        rc, _ = run(log, *homm3(*(["--image", image] if image else []),
                                "status", "merge-baseline"))
        return rc == 0
    if fnmatch.fnmatchcase(path, "config/retail/*/placements.tsv") or path == "build.ninja":
        # Regenerated by the cycle (placements --write, configure): take origin's.
        git("checkout", "--ours", "--", path)
        return True
    if path == "README.md":
        text = (ROOT / path).read_text()
        if not score_block_conflicts_only(text):
            return False
        # During a rebase side 0 ("ours") is origin; the build rewrites the blocks.
        (ROOT / path).write_text("\n".join(_pick_side(text.splitlines(), 0)) + "\n")
        return True
    return False


def rebase_in_progress() -> bool:
    return any((ROOT / git("rev-parse", "--git-path", name).strip()).exists()
               for name in ("rebase-merge", "rebase-apply"))


def rebase(log: Log, base: str) -> None:
    log(f"rebasing onto {base[:10]}")
    out = subprocess.run(["git", "rebase", base], cwd=ROOT, capture_output=True, text=True)
    log.raw(out.stdout + out.stderr)
    while out.returncode:
        if not rebase_in_progress():
            raise GateFailed("rebase", f"`git rebase {base}` failed (see the log)")
        conflicted = git("diff", "--name-only", "--diff-filter=U").split()
        unresolved = [path for path in conflicted if not _generated(path)]
        for path in conflicted:
            if path in unresolved:
                continue
            if resolve_conflict(log, path):
                git("add", "--", path)
                log(f"resolved generated {path}")
            else:
                unresolved.append(path)
        if unresolved or not conflicted:
            subprocess.run(["git", "rebase", "--abort"], cwd=ROOT, capture_output=True)
            raise GateFailed("rebase", "conflicts in " + (", ".join(unresolved) or
                             "the rebase (see the log)") + "; the rebase was aborted. "
                             f"Rebase onto {REMOTE}/{BRANCH} by hand, then run `homm3 land` again")
        env = dict(os.environ, GIT_EDITOR="true")
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode
        step = ["rebase", "--continue"] if staged else ["rebase", "--skip"]
        out = subprocess.run(["git", *step], cwd=ROOT, env=env, capture_output=True, text=True)
        log.raw(out.stdout + out.stderr)


# ------------------------------------------------------------------ the cycle

def changed_files(ignore=frozenset()) -> list[str]:
    lines = git("status", "--porcelain", "--untracked-files=all").splitlines()
    return sorted(path for path in (line[3:].split(" -> ")[-1] for line in lines if line.strip())
                  if path not in ignore)


def refresh_commit(log: Log, untracked) -> str | None:
    changed = changed_files(untracked)
    if not changed:
        log("nothing refreshed; no commit")
        return None
    unexpected = [path for path in changed if not _generated(path)]
    if unexpected:
        raise GateFailed("refresh commit", "the gate cycle changed files it does not own: "
                         + ", ".join(unexpected))
    placements = any(path.endswith("/placements.tsv") for path in changed)
    mac = any(path.startswith("config/mac/") for path in changed)
    what = ("scores" + (" and placements" if placements else "")
            + (" (Mac ledger included)" if mac else ""))
    git("add", "--", *changed)
    message = f"Refresh {what} after the rebase"
    git("commit", "-q", "-m", message)
    log(f"committed {git('rev-parse', '--short', 'HEAD').strip()} {message}: {', '.join(changed)}")
    return message


def full_build(log: Log, jobs: int) -> str:
    _, output = run(log, *homm3("build", "--", f"-j{jobs}"))
    return output


def cycle(log: Log, turn, args, timings: list, untracked) -> int:
    def phase(name: str):
        timings.append((name, time.monotonic()))
        turn.phase(name)
        log(f"== {name}")

    phase("fetch")
    run(log, "git", "fetch", REMOTE, args.branch, check="fetch")
    # Pin the fetched commit: refs/remotes is shared by every worktree, and
    # another lane's fetch moves origin/<branch> while this turn runs.
    base = git("rev-parse", "FETCH_HEAD^{commit}").strip()
    log(f"{REMOTE}/{args.branch} is {base[:10]}")
    phase("rebase")
    rebase(log, base)
    ahead = git("rev-list", "--reverse", f"{base}..HEAD").split()
    if not ahead:
        log(f"nothing to land: HEAD is {REMOTE}/{args.branch} {base[:10]}")
        turn.record["result"] = "nothing to land"
        return 0
    log(f"{len(ahead)} commit(s) to land:")
    log.raw(git("log", "--oneline", f"{base}..HEAD"))
    own_paths = git("diff", "--name-only", f"{base}..HEAD").split()

    images = editor_images()
    phase("build")
    output = full_build(log, args.jobs)
    green = not build_problems(output, images)
    if not green and not placements_only(output, images):
        raise GateFailed("build", "; ".join(build_problems(output, images)))
    phase("placements")
    rewritten = []
    for key in compiled_images(output, images):
        table = ROOT / "config/retail" / key / "placements.tsv"
        before = table.read_bytes() if table.is_file() else None
        run(log, *homm3("--image", key, "placements", "--write"),
            check=f"{key} placements --write")
        if (table.read_bytes() if table.is_file() else None) != before:
            rewritten.append(key)
    log("placements rewritten: " + (", ".join(rewritten) or "none"))
    if rewritten or not green:
        phase("build (after placements)")
        output = full_build(log, args.jobs)
        problems = build_problems(output, images)
        if problems:
            raise GateFailed("build (after placements)", "; ".join(problems))
    relevant = mac_paths(own_paths)
    if relevant or args.mac:
        phase("mac build")
        log("Mac build: " + ("forced (--mac)" if not relevant else
                             f"own commits touch {len(relevant)} Mac input(s): "
                             + ", ".join(relevant[:8]) + (" ..." if len(relevant) > 8 else "")))
        run(log, *homm3("mac", "build"), check="mac build")
    else:
        log("Mac build: skipped (own commits touch no Mac input)")
    phase("commit")
    refresh_commit(log, untracked)
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=ROOT).returncode:
        raise GateFailed("fast-forward check", f"HEAD does not contain {base[:10]}")
    if args.dry_run:
        phase("dry run: push skipped")
        log(f"dry run: would push {git('rev-parse', '--short', 'HEAD').strip()} "
            f"to {REMOTE} {args.branch}")
        turn.record["result"] = "dry run green"
        return 0
    phase("push")
    rc, output = run(log, "git", "push", REMOTE, f"HEAD:{args.branch}")
    if rc:
        hint = (" (origin moved outside the landing lock: someone pushed without "
                "`homm3 land`; run it again)" if "non-fast-forward" in output
                or "fetch first" in output else "")
        raise GateFailed("push", f"git push exited {rc}{hint}")
    turn.record["pushed"] = git("rev-parse", "HEAD").strip()
    turn.record["result"] = "landed"
    log(f"landed {len(ahead)} commit(s) at {turn.record['pushed'][:10]}")
    return 0


def preflight(args) -> frozenset:
    """Refuse an unready worktree; the untracked files the lane already has."""
    if rebase_in_progress():
        raise GateFailed("clean tree", "a rebase is in progress in this worktree")
    dirty = git("status", "--porcelain", "--untracked-files=no").splitlines()
    if dirty:
        raise GateFailed("clean tree", "uncommitted changes (commit or discard them first):\n  "
                         + "\n  ".join(dirty[:20]))
    import shutil
    missing = [tool for tool in ("ninja", "wine") if shutil.which(tool) is None]
    if missing:
        raise GateFailed("build shell", f"{', '.join(missing)} not on PATH; run inside "
                         "`nix develop .#build`")
    from homm3.build.build import _image_problems
    problems = _image_problems(set())
    if problems:
        raise GateFailed("image inputs", "; ".join(problems))
    return frozenset(changed_files())


def land(args) -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log = Log(ROOT / "build/land" / f"{stamp}{'-dry-run' if args.dry_run else ''}.log")
    branch = (subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip() or "(detached)")
    log(f"{'dry run' if args.dry_run else 'landing'} {branch} from {ROOT} onto "
        f"{REMOTE}/{args.branch}; log: {log.path}")
    timings: list = []
    started = time.monotonic()
    untracked = frozenset()
    try:
        untracked = preflight(args)
        from homm3.core import worktree_lock
        queue = land_queue.Queue.for_checkout(ROOT)
        info = {"worktree": str(ROOT), "branch": branch, "dry_run": args.dry_run,
                "log": str(log.path), "command": "homm3 land" + (" --dry-run" if args.dry_run else "")}
        with worktree_lock.hold(info["command"]), \
                queue.turn(info, report=log, poll=args.poll) as turn:
            locked = time.monotonic()
            log(f"holding the landing lock (waited {locked - started:.0f}s)")
            try:
                rc = cycle(log, turn, args, timings, untracked)
            except GateFailed as exc:
                turn.record["result"] = f"failed: {exc.gate}"
                raise
            finally:
                if rebase_in_progress():
                    subprocess.run(["git", "rebase", "--abort"], cwd=ROOT, capture_output=True)
                    log("aborted the unfinished rebase")
                timings.append(("end", time.monotonic()))
                for (name, at), (_, until) in zip(timings, timings[1:]):
                    log(f"  {name:<26} {until - at:7.0f}s")
                log(f"turn took {time.monotonic() - locked:.0f}s holding the lock "
                    f"({time.monotonic() - started:.0f}s in all)")
        return rc
    except GateFailed as exc:
        log(f"FAILED gate: {exc.gate}" + (f": {exc.detail}" if exc.detail else ""))
        dirty = [path for path in changed_files(untracked) if _generated(path)]
        if dirty:
            log("the gate cycle left refreshed files uncommitted: " + ", ".join(dirty)
                + " (`git checkout HEAD -- <files>` discards them)")
        log(f"log: {log.path}")
        return 1
    finally:
        log.close()


def status(args) -> int:
    queue = land_queue.Queue.for_checkout(ROOT)
    state = queue.status()
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        for line in land_queue.render(state):
            print(line)
    return 0


def _terminate(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="homm3 land", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true",
                        help="print the landing lock's holder, queue and recent turns")
    parser.add_argument("--json", action="store_true", help="with --status: JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="everything but the push (rebase and refresh commit stay local)")
    parser.add_argument("--mac", action="store_true",
                        help="run `homm3 mac build` even when no own commit touches a Mac input")
    parser.add_argument("--jobs", type=int, default=4, metavar="N",
                        help="ninja parallelism for the full builds (default 4)")
    parser.add_argument("--branch", default=BRANCH, help=argparse.SUPPRESS)
    parser.add_argument("--poll", type=float, default=land_queue.POLL_SECONDS,
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.status:
        return status(args)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _terminate)
    return land(args)


def logged_main(argv=None) -> int:
    import shlex
    from homm3.core.usage import append, run_logged
    argv = list(sys.argv[1:] if argv is None else argv)
    command = shlex.join(["homm3", "land", *argv])
    return run_logged(main, argv, lambda rc, **meta: append(
        ROOT / "build/homm3_usage.log", command, rc, **meta), failure_rc=1)


if __name__ == "__main__":
    sys.exit(logged_main())
