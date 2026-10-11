# Landing lane commits: `homm3 land`

Several lanes publish to `decomp-complete-4.0` from their own worktrees. After
every rebase a lane must run the full gate cycle (about 20-30 minutes), and
the branch moves more often than that, so lanes that rebase and push by hand
starve each other: each push invalidates every other lane's running cycle.
`homm3 land` serializes the cycle. Only the holder of a repository-wide lock
rebases, gates and pushes, so nothing lands between its rebase and its push
and the cycle runs once per turn. Lanes keep their edit/measure loop
(`homm3 build --fast TU`, commits) outside the lock.

```sh
homm3 land --dry-run    # the whole turn except the push
homm3 land              # land this worktree's commits
homm3 land --status     # holder, queue, recent turns (--json)
```

## The turn

Preflight, before queueing: no rebase in progress, no uncommitted tracked
changes, ninja and wine on PATH (the `nix develop .#build` shell), every
editor image staged (the same check a full build makes). Then `homm3 land` takes this worktree's build lock and waits for the landing
lock. While holding both it:

1. fetches `origin decomp-complete-4.0` and rebases the current branch onto
   it. Conflicts in generated files are resolved as lanes resolve them by
   hand: score ledgers three ways with `homm3 [--image KEY] status
   merge-baseline`, README score blocks, `config/retail/*/placements.tsv` and
   `build.ninja` from origin (the cycle regenerates them). A README conflict
   outside a `<!-- *match-score:start/end -->` block, or any other conflicted
   file, aborts the rebase, releases the lock and fails gate `rebase`;
2. runs the full `homm3 build -- -j4` and reads its summary: every pinned
   editor image must have been built (`image KEY: building`, never
   `SKIPPED`). Its only acceptable failure is an editor image whose own gates
   failed on `placements` after that image compiled and delinked;
3. runs `homm3 --image KEY placements --write` for each image the build
   compiled (never after a game-only compile, which would blank the tables),
   and the full build again when a table changed or the first build was not
   green. That build must pass every gate for every image;
4. runs `homm3 mac build` when the lane's own commits (`origin..HEAD` after
   the rebase) touch a Mac build input, or always with `--mac`. Inputs are
   derived from the build configuration: the `source` of every
   `config/units.toml` unit, files under the game's include roots (`src`,
   `include`, `[build].includes`) outside the editors' own trees
   (`src/<dir>`, `include/<dir>` of each image's `sources`),
   `config/units.toml` and `config/mac/`. Upstream commits are not
   re-checked: their own landing ran the Mac build when they needed it;
5. commits what the cycle rewrote (README score blocks, `build.ninja`, the
   ledgers, placements tables, the Mac ledger and profiles, cleanliness
   floors) as `Refresh scores [and placements] after the rebase`. Any other
   changed file fails gate `refresh commit`;
6. checks that HEAD contains `origin/decomp-complete-4.0` and pushes
   `git push origin HEAD:decomp-complete-4.0`, a plain fast-forward. A
   rejected push means someone pushed without `homm3 land`; run it again.

The output of every command goes to the terminal and to
`build/land/<time>.log` (`build/land/latest.log` links the newest), ending
with the time each phase took. A failure exits 1 and names the gate
(`clean tree`, `build shell`, `image inputs`, `fetch`, `rebase`, `build`,
`KEY placements --write`, `build (after placements)`, `mac build`,
`refresh commit`, `fast-forward check`, `push`). After a gate failure the
rebased branch stays rebased; files the cycle rewrote stay uncommitted for
inspection (the log names them; `git checkout HEAD -- FILES` discards them).

`--dry-run` stops before the push. The rebase and the refresh commit stay in
the local branch, so a later `homm3 land` starts from them.

## The lock and the queue

The state lives in the repository's common git directory
(`git rev-parse --git-common-dir`, shared by all linked worktrees), in
`homm3-land/` (homm3.core.land_queue):

- `lock`: an flock(2) held for the whole turn. The kernel releases it when
  the holder exits, however it exits.
- `queue.json`: waiters in ticket order. Only the head of the queue tries
  the lock, so waiters are served in arrival order. A waiter whose process
  is gone (or whose pid now belongs to a process with another start time) is
  pruned by the next waiter that reads the queue; Ctrl-C withdraws a waiter.
- `holder.json`: worktree, branch, pid, start time and current phase of the
  holder. Waiters print their position and the holder whenever either
  changes. When the holder's process has exited, `--status` reports the
  record as stale (the lock is already free) and the next holder overwrites
  it.
- `history.jsonl`: one line per finished turn (result, phase reached, log).

Interrupting the holder (Ctrl-C, SIGTERM, SIGHUP) aborts an unfinished
rebase, records the turn and releases the lock. Do not kill the build
children by pattern; stop `homm3 land` itself by its pid.
