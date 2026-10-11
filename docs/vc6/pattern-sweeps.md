# Pattern sweeps: mechanisms that closed a wall once, checked image-wide

`homm3 patterns` (scripts/homm3/analysis/patterns.py) turns each mechanism
that closed a function once into a scored candidate list over every image
(game, h3maped, h3ccmped). It reads the paired comparison objects
(`build/<image>/objdiff/normalized/{base,target}`) with each image's ledger
and unit profiles; it edits nothing. Rows without a ledger row are skipped:
an unscored name can pair two unrelated bodies.

| Command | Mechanism | Signal |
| --- | --- | --- |
| `cc` | wrong calling convention (explicit keyword or image default) | callee `ret N` and ecx/edx live on entry; caller cleanup after each paired call site |
| `flags` | per-profile flags (`/Op`) | x87 store/reload pairs, inline `fabs` vs `_fabs` calls |
| `flags --try UNITS --drop F --add F` | profile A/B control | compiles the units with the changed profile and scores every body with the build's normalization; calling-convention-only renames are paired |
| `inline` | /Ob1 expansion (only declared-inline bodies expand) | per-callee call/expand asymmetries; unnamed retail callees that pair with ours site for site |
| `loops` | rotated vs unrotated loops | conditional vs unconditional back edges |
| `ctors` | constructor shape behind store order | same-base store permutations |

## Profile decisions (retail-backed controls, 2026-10-11)

Each control compiles every unit of the profile both ways and scores every
function against retail (`homm3 patterns flags --try`).

| Image / profile | Change tested | Result | Decision |
| --- | --- | --- | --- |
| game `game_o2_mt_gr_windows` | drop `/Op` | 282 bodies worse, 0 better (AdjustHSV, the army damage/value math, bolt/chain-lightning geometry, AI valuations) | keep `/Op` |
| h3maped `editor_o1_ob2_gr_windows` | drop `/Op` | 5 better, 0 worse: placeExtraMines 97.06 -> 100, TRmgVector::length 82.86 -> 100, readBitset 99.82 -> 100 (two copies), TTownDistanceLess::operator() 67.38 -> 72.59 | drop `/Op` |
| h3maped `editor_fastcall_o1_ob2_gr_windows` (gzinflatebuf) | drop `/Op` | no body moves | drop, as the map-editor profile it extends |
| h3maped `libraries_o2_gr_windows` | add `/Ob2` | 33 worse, 0 better | keep `/O2` (= `/Ob1`) |
| h3ccmped `ccmped_o2_gr_windows` | add `/Ob2` | 135 worse, 4 better | keep `/O2` (= `/Ob1`) |
| h3ccmped `ccmped_o2_gr_windows` | drop `/Op` | no body moves | no evidence; unchanged |
| h3maped RMG (`rmg_river`, `rmg_road`, `rmg_voronoi`) | drop `/Gr` | both onTerrainTypeChanged hooks 94.35 -> 100, addSite 99.08 -> 100 once the two ecx helpers are explicit `__fastcall` | the RMG uses the map-editor profile (`__cdecl`) |

The `/Op` signature in the editors: `/Op` stores each float temporary and
reloads it (`fstp [ebp-x]; fld [ebp-x]`) and calls `_fabs`; without it VC6
keeps temporaries on the x87 stack and emits `fabs`. The game's float code
has the stores (282 bodies prove it), the map editor's own objects and both
editors' Libraries do not.

## Calling conventions

The game builds with `/Gr`, so an explicit `__fastcall` there is redundant
and an omitted one is invisible; the editors default to `__cdecl`, which is
where a wrong declaration shows. `cc` compares, per compared function, the
bytes the callee pops and whether ecx/edx are live on entry, and per paired
call site whether the caller pops the arguments.

- isRmgPointInsideCircle (h3maped 0x4ccc7a) pops nothing and its caller
  releases 32 bytes: the editor RMG is `__cdecl`, not `/Gr`.
- flipRmgEdge (0x4cc68e) and isRmgPointOnSegment (0x4cc6f2, `ret 8`) still
  take the edge in ecx under `__cdecl`: explicit `__fastcall`. As
  TRmgHalfEdge members (thiscall, the same bytes in the editor) the game's
  addSite stops expanding them (100 -> 54.82), so the members are wrong.

## Library identities the census cannot see

`inline`'s unnamed-callee list found 26 statically linked library bodies
(MFC NAFXCW, LIBCMT, LIBCPMT) whose masked bytes equal the archive member
exactly but that the census leaves unnamed: an empty release body is a lone
`ret` (CPropertyPage::OnOK, CDocument::DeleteContents), or several identical
starts compete. They are reviewed rows in each image's
`runtime-contributions.tsv`. One such row closed 41 property pages' OnOK.

## Constructor shape behind store order

When retail stores one object's fields in another order than ours, the
source shape of the construction differs. Seen so far:

- **A later store to the same member.** type_sacrifice_window::
  createArtifactWidgets: the default-constructed offering stores its payload
  -1 before its id. Dreamcast line 455 assigns the id again after the
  generated constructor; VC6 drops the constructor's id store and keeps the
  later one, so the payload lands first. Other default type_artifact
  constructions keep id first. Measured flat: a member initializer list, a
  defaulted second payload parameter (two regressions; DC's constructor has
  one parameter), user-written offering constructors.
- **Member initializer vs body assignment.** type_spell_scroll: the map
  editor's expansion stores the vtable before m_spell. A member initializer
  runs before the vptr store, a body assignment after it.
- Not yet resolved by shape: calculateNormalDialogSize's zero loop (both
  arrays, retail second array first), SCampaign::completeCurrentMap,
  fillZoneArea's flag byte, TObstacleToolkit's constructor locals.
