# Disposable TU-state sweep

VC6 code generation can move when the translation unit's include population
changes, even when a function's own source hash does not. The batch runner
searches that state without changing authored source:

```sh
homm3 vc6 state-sweep --trials 30 --jobs 8 --bank
```

The runner discovers every numeric `MAX < HIST` row, and every non-exact row
that a scored `homm3 vc6 compile-m UNIT --score` prediction marks as
state-reachable, and groups them by translation unit. A row is
state-reachable when its unit's `build/vc6/unstable-state/UNIT/compile-m.json`
was made from the unit's current source (its `source_sha256`), is scored, and
has an assembly whose objdiff score rounds above the row's MAX. Stale or
unscored predictions are ignored; `--no-state-reachable` restores the
`MAX < HIST`-only selection.

In each trial the runner chooses five to ten game headers (top-level
`include/*.h`; the editors' MFC headers under `include/editor` and
`include/campaign_editor` cannot parse in a game TU) that the TU does not
include directly or transitively, shuffles their order, inserts that include
block once after the TU's initial include block, and compiles the TU once.
Units with state-reachable rows run every trial a second time with the block
at the top of the file, before the TU's own includes: that is the placement
compile-m's declaration offset models (it shifts every handle, including the
ones the TU's headers create), while the include-block placement shifts only
handles created after it. Each placement keeps its own cache context, and the
reproduction compile uses the placement that won. Every configured function in
the candidate object is scored. Per-trial records keep the selected header
order and every function score; the summary records every function whose
score moved, including drops, rather than reporting only MAX gains. Incompatible header combinations are recorded as
failed trials without aborting other TUs. Generated source copies, objects,
reports, and resumable trial records live only under `build/tu-state-sweep/`.

Banking fails closed:

- each prospective improvement is recompiled and must reproduce to four score
  decimals;
- authored source files and `config/match_baseline.tsv` must not change during
  the sweep;
- headers, compiler/profile, retail targets and scoring code must also stay
  unchanged; their content fingerprints invalidate cached trials after changes;
- a row with a function hash must still have that exact live hash;
- CUR remains the clean canonical-build score;
- only MAX is raised, with HIST raised too if the observation is a new all-time
  peak;
- no experimental include is copied into authored source.

A header trial can only add code before a function. It can give a function
phase 1 (an initializer in an added header) or move its handle offset, but it
can never give a function that is not first in its TU phase 0, and it does not
set the callee-order state. Rows whose better assembly needs those states are
selected and scored but cannot be banked this way.

A sweep can reproduce an existing peak without finding a new one. For rows
still below HIST, verify whether the old result used faithful source before
trying to recover it. See [historical match evidence](../reconstruction/historical-matches.md).
