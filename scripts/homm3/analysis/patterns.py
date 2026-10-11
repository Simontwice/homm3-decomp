"""homm3 patterns - image-wide sweeps for compiler mechanisms that closed a wall once.

Each subcommand reads every selected image's paired comparison objects
(build/<image>/objdiff/normalized/{base,target}, the bodies the ledger scores),
joins them with the image's ledger (CUR/MAX) and unit profiles, and prints a
scored candidate list. Nothing here edits source or profiles.

  homm3 patterns cc [--images game,h3maped,h3ccmped] [--json] [--limit N]
        Calling conventions. Per compared function: the bytes the callee pops
        (`ret N`) and whether ecx/edx are live on entry, ours vs retail; per
        callee: the stack cleanup each paired call site performs after the
        call (`add esp, N` / `pop ecx`), ours vs retail. A disagreement means
        the declaration's convention (an explicit keyword, or the image's
        default: /Gr game and RMG, __cdecl editors) differs from the one the
        retail image compiled. Rows say whether the source spells the
        convention explicitly.

  homm3 patterns flags [--images ...] [--json] [--limit N]
        Per-profile flag signatures. /Op: retail inlines `fabs`
        (D9 E1) where we call _fabs, or keeps float temporaries on the x87
        stack where we store and reload them (fst/fstp to a frame slot
        followed by a load of the same slot). Rows list each function whose
        x87 store/reload count or fabs form differs, grouped by profile.
  homm3 patterns flags --try UNIT[,UNIT...] [--drop FLAG] [--add FLAG] [--image KEY]
        A/B control: compile the units with the changed profile into
        build/<image>/patterns/, score every function with the build's
        objdiff normalization and print each function whose score moves.

  homm3 patterns inline [--images ...] [--all-units] [--json] [--limit N]
        Call-set asymmetries, aggregated per callee: calls we emit where the
        paired retail body has none (retail expanded the callee) and calls
        retail emits where ours has none (we expanded it). By default only
        /Ob1 units (/O1 or /O2 without /Ob2), where only functions declared
        inline (in-class or `inline`) expand.

  homm3 patterns loops [--images ...] [--json] [--limit N]
        Loop shapes. Per function: unconditional and conditional back edges,
        ours vs retail. A rotated loop closes with a conditional back edge
        and tests once before entry; an unrotated one jumps back to its head.
        Rows where the back-edge kinds differ are rotation candidates.

  homm3 patterns ctors [--images ...] [--json] [--limit N]
        Constructor shape. Non-exact functions where both sides emit the
        same stores to one base register in a different order (masked
        instruction rows, adjacent permutation blocks), ranked by the share
        of the difference those blocks explain. The usual sources: member
        initializers vs body assignments, default arguments vs a separate
        default constructor, another constructor expanded at the site, or a
        later store to the same member that kills the constructor's
        (type_sacrifice_window::createArtifactWidgets).

Scores: `gap` is 100 - MAX; rows sort by evidence weight, then gap.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from homm3.core import paths

REL32 = 20
CALL = 0xE8
#: Registers that carry arguments: ecx (thiscall / fastcall 1st), edx
#: (fastcall 2nd).
ARG_REGS = ("ecx", "edx")
_REG_FAMILY = {
    "ecx": "ecx", "cx": "ecx", "cl": "ecx", "ch": "ecx",
    "edx": "edx", "dx": "edx", "dl": "edx", "dh": "edx",
}
CONVENTIONS = ("__cdecl", "__stdcall", "__fastcall", "__thiscall")
#: Source trees each image owns alone; everything else is shared/game.
EDITOR_TREES = ("src/editor", "include/editor", "src/campaign_editor",
                "include/campaign_editor")


# --- pairing ---------------------------------------------------------------------

@dataclass
class Function:
    image: str
    unit: str
    name: str
    flags: tuple
    ours: bytes
    ours_relocs: dict
    retail: bytes
    retail_relocs: dict
    cur: float | None = None
    max: float | None = None
    rva: int | None = None

    @property
    def gap(self) -> float:
        return round(100.0 - (self.max if self.max is not None else 0.0), 4)


def _ledger(image: str) -> dict:
    from homm3.match import status
    path = paths.baseline(image)
    return status.parse_baseline(path.read_text()) if path.is_file() else {}


def unit_flags(image: str) -> dict[str, tuple]:
    from homm3 import manifest
    path = paths.manifest(image)
    profiles = manifest.flag_profiles(path)
    return {u["unit"]: tuple(profiles.get(u.get("flags"), ()))
            for u in manifest.units(path)}


def ob1(flags) -> bool:
    """True when only functions declared inline expand: /O1 or /O2 without
    an explicit /Ob2 (both imply /Ob1)."""
    flags = set(flags)
    return bool(flags & {"/O1", "/O2"}) and "/Ob2" not in flags


def functions(image: str, units: set[str] | None = None, scored_only: bool = True):
    """Every function present in both normalized comparison objects of the
    image's units, with its ledger row (only ledger rows unless
    `scored_only` is false: an unscored name can pair two different bodies)."""
    from homm3.census.placements import _functions_of
    from homm3.delink.coffx import Obj
    root = paths.image_build(image) / "objdiff/normalized"
    ledger = _ledger(image)
    for unit, flags in unit_flags(image).items():
        if units and unit not in units:
            continue
        base, target = root / "base" / f"{unit}.obj", root / "target" / f"{unit}.c.obj"
        if not base.is_file() or not target.is_file():
            continue
        ours = {n: (b, r) for n, _s, _o, b, r in _functions_of(Obj(base))}
        theirs = {n: (b, r) for n, _s, _o, b, r in _functions_of(Obj(target))}
        for name in ours.keys() & theirs.keys():
            row = ledger.get((unit, name))
            if scored_only and row is None:
                continue
            yield Function(image, unit, name, flags, ours[name][0], ours[name][1],
                           theirs[name][0], theirs[name][1],
                           row.cur if row else None, row.max if row else None,
                           row.rva if row else None)


# --- disassembly -----------------------------------------------------------------

@lru_cache(maxsize=1)
def _capstone():
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return md


def decode(body: bytes) -> dict[int, object]:
    """{offset: instruction} reached from offset 0 (recursive descent: jump
    tables and data embedded after the code are never decoded)."""
    md = _capstone()
    out, work = {}, [0]
    while work:
        at = work.pop()
        while 0 <= at < len(body) and at not in out:
            insn = next(md.disasm(body[at:at + 16], at), None)
            if insn is None:
                break
            out[at] = insn
            target = _branch_target(insn)
            mnem = insn.mnemonic
            if mnem == "jmp":
                if target is not None:
                    work.append(target)
                break
            if mnem.startswith("j") or mnem.startswith("loop"):
                if target is not None:
                    work.append(target)
            if mnem.startswith("ret") or mnem in ("int3", "hlt"):
                break
            at += insn.size
    return out


def _branch_target(insn) -> int | None:
    if not (insn.mnemonic.startswith("j") or insn.mnemonic.startswith("loop")):
        return None
    op = insn.op_str
    return int(op, 0) if re.fullmatch(r"0x[0-9a-f]+|[0-9]+", op) else None


def _successors(insns: dict, at: int) -> list[int]:
    insn = insns[at]
    mnem = insn.mnemonic
    nxt = at + insn.size
    target = _branch_target(insn)
    if mnem.startswith("ret") or mnem in ("int3", "hlt"):
        return []
    if mnem == "jmp":
        return [target] if target in insns else []
    succ = [nxt] if nxt in insns else []
    if target is not None and target in insns:
        succ.append(target)
    return succ


def _use_def(insn) -> tuple[set, set]:
    mnem = insn.mnemonic
    if mnem == "call":
        return set(), {"ecx", "edx"}
    try:
        reads, writes = insn.regs_access()
    except Exception:
        return set(), set()
    use = {_REG_FAMILY[insn.reg_name(r)] for r in reads if insn.reg_name(r) in _REG_FAMILY}
    defs = {_REG_FAMILY[insn.reg_name(r)] for r in writes if insn.reg_name(r) in _REG_FAMILY}
    ops = [o.strip() for o in insn.op_str.split(",")]
    if mnem in ("xor", "sub", "sbb") and len(ops) == 2 and ops[0] == ops[1]:
        use -= defs
    if mnem == "push" and insn.op_str in ("ecx", "edx"):
        use = set()                   # `push ecx` reserves a frame slot
    if mnem in ("movzx", "movsx", "mov", "lea") and _REG_FAMILY.get(ops[0]) in defs \
            and ops[0] in ("ecx", "edx"):
        pass
    return use, defs


def signature(body: bytes) -> tuple[frozenset, frozenset]:
    """(bytes popped by each return, argument registers live on entry)."""
    insns = decode(body)
    pops = set()
    for insn in insns.values():
        if insn.mnemonic.startswith("ret"):
            pops.add(int(insn.op_str, 0) if insn.op_str else 0)
    live: dict[int, set] = {at: set() for at in insns}
    order = sorted(insns, reverse=True)
    changed = True
    while changed:
        changed = False
        for at in order:
            use, defs = _use_def(insns[at])
            out = set().union(*(live[s] for s in _successors(insns, at))) if insns else set()
            new = use | (out - defs)
            if new != live[at]:
                live[at] = new
                changed = True
    return frozenset(pops), frozenset(live.get(0, set()))


# --- names -----------------------------------------------------------------------

def demangle(names) -> dict[str, str]:
    from homm3.core import undname
    return undname.demangle(names)


def convention(name: str, demangled: dict) -> str | None:
    text = demangled.get(name)
    if text:
        for cc in CONVENTIONS:
            if cc in text:
                return cc
        return None
    if name.startswith("@") and re.search(r"@\d+$", name):
        return "__fastcall"
    if name.startswith("_") and re.search(r"@\d+$", name):
        return "__stdcall"
    if name.startswith("_"):
        return "__cdecl"
    return None


def short_name(name: str, demangled: dict) -> str:
    text = demangled.get(name)
    if not text:
        return name
    from homm3.core import undname
    return undname.qualified(text) or text


@lru_cache(maxsize=1)
def explicit_declarations() -> dict[str, list[str]]:
    """{identifier: [file:line ...]} for every identifier declared with an
    explicit calling-convention keyword in the shared/game tree."""
    out: dict[str, list[str]] = defaultdict(list)
    pattern = re.compile(r"\b(__fastcall|__cdecl|__stdcall)\s+(?:[A-Za-z_]\w*::)*"
                         r"(~?[A-Za-z_]\w*|operator\s*\S+?)\s*\(")
    for top in ("src", "include"):
        for path in sorted((paths.ROOT / top).rglob("*")):
            if path.suffix not in (".h", ".hpp", ".c", ".cpp", ".inl"):
                continue
            rel = path.relative_to(paths.ROOT).as_posix()
            if rel.startswith(EDITOR_TREES):
                continue
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                for match in pattern.finditer(line):
                    out[match.group(2)].append(f"{rel}:{number}")
    return out


def _bare(qualified: str) -> str:
    return re.split(r"::", qualified.split("(")[0])[-1].strip()


# --- cc --------------------------------------------------------------------------

def _cleanup_after(body: bytes, end: int) -> int:
    """Bytes a caller releases right after a call ending at `end`."""
    if body[end:end + 2] == b"\x83\xc4":
        return body[end + 2] if end + 2 < len(body) else 0
    if body[end:end + 2] == b"\x81\xc4":
        return int.from_bytes(body[end + 2:end + 6], "little")
    if body[end:end + 1] == b"\x59":
        return 8 if body[end + 1:end + 2] == b"\x59" else 4
    return 0


def call_sites(body: bytes, relocs: dict) -> dict[str, list[int]]:
    """{callee: [cleanup bytes after each direct call, in body order]}."""
    sites = defaultdict(list)
    for site in sorted(relocs):
        ref, kind = relocs[site]
        if kind == REL32 and site >= 1 and body[site - 1] == CALL:
            sites[ref].append(_cleanup_after(body, site + 4))
    return sites


def sweep_cc(images, *, limit=None) -> dict:
    callee_rows: dict[tuple, dict] = {}
    function_rows = []
    pending = []
    for image in images:
        for fn in functions(image):
            pending.append(fn)
    demangled = demangle({fn.name for fn in pending}
                         | {ref for fn in pending for ref, _k in fn.ours_relocs.values()})
    explicit = explicit_declarations()
    for fn in pending:
        ours, theirs = signature(fn.ours), signature(fn.retail)
        if ours != theirs:
            cc = convention(fn.name, demangled)
            bare = _bare(short_name(fn.name, demangled))
            function_rows.append({
                "image": fn.image, "unit": fn.unit, "function": short_name(fn.name, demangled),
                "symbol": fn.name, "convention": cc, "max": fn.max, "gap": fn.gap,
                "ours_pops": sorted(ours[0]), "retail_pops": sorted(theirs[0]),
                "ours_live": sorted(ours[1]), "retail_live": sorted(theirs[1]),
                "explicit": explicit.get(bare, []),
                "weight": 2 * (ours[0] != theirs[0]) + (ours[1] != theirs[1]),
            })
        a, b = call_sites(fn.ours, fn.ours_relocs), call_sites(fn.retail, fn.retail_relocs)
        for callee in a.keys() & b.keys():
            for x, y in zip(a[callee], b[callee]):
                key = (fn.image, callee)
                row = callee_rows.setdefault(key, {
                    "image": fn.image, "callee": short_name(callee, demangled),
                    "symbol": callee, "convention": convention(callee, demangled),
                    "agree": 0, "differ": 0, "examples": [],
                    "explicit": explicit.get(_bare(short_name(callee, demangled)), [])})
                if x == y:
                    row["agree"] += 1
                else:
                    row["differ"] += 1
                    if len(row["examples"]) < 4:
                        row["examples"].append(
                            f"{fn.unit}:{short_name(fn.name, demangled)} ours {x} retail {y}")
    unplaced = unplaced_conventions(images, demangled)
    callees = sorted((r for r in callee_rows.values() if r["differ"]),
                     key=lambda r: (-r["differ"] / (r["differ"] + r["agree"]), -r["differ"]))
    function_rows.sort(key=lambda r: (-r["weight"], -r["gap"]))
    return {"functions": function_rows[:limit] if limit else function_rows,
            "callees": callees[:limit] if limit else callees,
            "unplaced": unplaced}


@lru_cache(maxsize=None)
def _retail_image(image: str):
    from homm3.core.image import Image
    from homm3.core.tsv import read as read_tsv
    exe = paths.ROOT / "build/orig" / ("HEROES3.EXE" if image == "game" else f"{image}.exe")
    sizes = {int(r["rva"], 16): int(r["size"])
             for r in read_tsv(paths.retail_dir(image) / "functions.tsv")[2]}
    return Image(str(exe)), sizes


def retail_body(image: str, rva: int) -> bytes | None:
    exe, sizes = _retail_image(image)
    size = sizes.get(rva)
    section = exe.section_of(rva)
    if size is None or section is None:
        return None
    start = section.raw_offset + rva - section.rva
    return exe.data[start:start + size]


def unplaced_conventions(images, demangled) -> list[dict]:
    """Our callees that pair site for site with an unnamed retail body whose
    entry disagrees with our declared convention: a register convention
    whose retail body reads neither register and pops nothing, or a stack
    convention whose retail body pops its arguments or reads ecx/edx."""
    rows = []
    for pair in unnamed_pairs([i for i in images if i != "game"], demangled):
        body = retail_body(pair["image"], int(pair["retail"][3:], 16)) \
            if pair["retail"].startswith("fn_") else None
        if body is None:
            continue
        pops, live = signature(body)
        cc = convention(pair["ours"], demangled)
        register = cc in ("__fastcall",)
        if (register and not live and pops <= {0}) or (cc == "__cdecl" and (live or pops - {0})):
            rows.append({**pair, "convention": cc, "retail_pops": sorted(pops),
                         "retail_live": sorted(live)})
    return rows


def render_cc(result) -> None:
    rows = result.get("unplaced", [])
    print(f"== unplaced callees whose retail entry contradicts our convention ({len(rows)})")
    for r in rows:
        print(f"  {r['image']:8} {r['retail']:>12} {r['convention'] or '?':10} {r['callee']}"
              f"  retail pops {r['retail_pops']} live {r['retail_live']} ({r['sites']} sites)")
    rows = result["functions"]
    print(f"== callee signatures that differ ({len(rows)}): pops / live-in argument registers")
    for r in rows:
        print(f"  [{r['weight']}] {r['image']:8} {r['unit']:22} gap {r['gap']:7.3f} "
              f"{r['convention'] or '?':10} {r['function']}\n"
              f"        pops ours {r['ours_pops']} retail {r['retail_pops']}; "
              f"live ours {r['ours_live']} retail {r['retail_live']}"
              + (f"; explicit at {', '.join(r['explicit'][:2])}" if r["explicit"] else ""))
    rows = result["callees"]
    print(f"\n== call sites whose caller cleanup differs ({len(rows)} callees)")
    for r in rows:
        print(f"  {r['image']:8} differ {r['differ']:3} agree {r['agree']:3} "
              f"{r['convention'] or '?':10} {r['callee']}"
              + (f"  [explicit {r['explicit'][0]}]" if r["explicit"] else ""))
        for example in r["examples"]:
            print(f"        {example}")


# --- flags (x87) -------------------------------------------------------------------

_FRAME_SLOT = re.compile(r"\[(?:ebp|esp)(?: [+-] 0x[0-9a-f]+)?\]")


def x87_profile(body: bytes, relocs: dict) -> dict | None:
    insns = [insns for _at, insns in sorted(decode(body).items())]
    if not any(i.mnemonic.startswith("f") for i in insns):
        return None
    stores = Counter()
    reloads = 0
    for i, insn in enumerate(insns):
        m = insn.mnemonic
        if m in ("fst", "fstp") and _FRAME_SLOT.search(insn.op_str):
            slot = _FRAME_SLOT.search(insn.op_str).group(0)
            nxt = insns[i + 1] if i + 1 < len(insns) else None
            if nxt is not None and nxt.mnemonic.startswith("fld") \
                    and slot in nxt.op_str:
                reloads += 1
            stores[slot] += 1
    calls = {ref for site, (ref, kind) in relocs.items()
             if kind == REL32 and site and body[site - 1] == CALL}
    return {
        "fabs": sum(1 for i in insns if i.mnemonic == "fabs"),
        "fabs_calls": sum(1 for ref in calls if ref in ("_fabs",)),
        "reloads": reloads,
        "x87": sum(1 for i in insns if i.mnemonic.startswith("f")),
        "ftol_calls": sum(1 for ref in calls if ref == "__ftol"),
    }


def sweep_flags(images, *, limit=None) -> dict:
    rows = []
    names = []
    for image in images:
        for fn in functions(image):
            a = x87_profile(fn.ours, fn.ours_relocs)
            b = x87_profile(fn.retail, fn.retail_relocs)
            if a is None and b is None:
                continue
            a = a or {}
            b = b or {}
            differs = [k for k in ("fabs", "fabs_calls", "reloads", "ftol_calls")
                       if a.get(k, 0) != b.get(k, 0)]
            names.append(fn.name)
            rows.append({"image": fn.image, "unit": fn.unit, "symbol": fn.name,
                         "profile": " ".join(f for f in fn.flags if f.startswith("/O")),
                         "op": "/Op" in fn.flags, "max": fn.max, "gap": fn.gap,
                         "ours": a, "retail": b, "differs": differs})
    demangled = demangle(names)
    for r in rows:
        r["function"] = short_name(r["symbol"], demangled)
    summary = defaultdict(lambda: Counter())
    for r in rows:
        key = (r["image"], "with /Op" if r["op"] else "without /Op")
        summary[key]["float functions"] += 1
        summary[key]["exact"] += r["gap"] == 0
        for k in r["differs"]:
            summary[key][k] += 1
            more = r["ours"].get(k, 0) > r["retail"].get(k, 0)
            summary[key][f"{k} ours>retail" if more else f"{k} ours<retail"] += 1
    candidates = sorted((r for r in rows if r["differs"]),
                        key=lambda r: (-len(r["differs"]), -r["gap"]))
    return {"summary": {f"{i} {o}": dict(c) for (i, o), c in sorted(summary.items())},
            "candidates": candidates[:limit] if limit else candidates}


def render_flags(result) -> None:
    print("== float-using functions per image and /Op state")
    for key, counts in result["summary"].items():
        print(f"  {key}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    rows = result["candidates"]
    print(f"\n== functions whose x87 signature differs ({len(rows)})")
    for r in rows:
        keys = ", ".join(f"{k} {r['ours'].get(k, 0)}/{r['retail'].get(k, 0)}" for k in r["differs"])
        print(f"  {r['image']:8} {r['unit']:22} gap {r['gap']:7.3f} "
              f"{'/Op' if r['op'] else '   '} {r['function']}  [{keys}] (ours/retail)")


_CC_TEXT = re.compile(r"\b(?:__cdecl|__stdcall|__fastcall|__thiscall)\s*")


def rename_symbols(data: bytes, mapping: dict[str, str]) -> bytes:
    """The COFF object with each symbol named in `mapping` renamed (new
    names are appended to the string table)."""
    import struct
    from homm3.delink.coffx import Obj
    obj = Obj(data)
    buf = bytearray(data)
    strtab = bytearray(buf[obj.strtab_off:])
    for idx, _value, _sec in obj.iter_symbols():
        new = mapping.get(obj.sym_name(idx))
        if new is None:
            continue
        base = obj.symptr + idx * 18
        struct.pack_into("<II", buf, base, 0, len(strtab))
        strtab += new.encode("latin1") + b"\0"
    struct.pack_into("<I", strtab, 0, len(strtab))
    return bytes(buf[:obj.strtab_off]) + bytes(strtab)


def convention_aliases(ours: set[str], targets: set[str]) -> dict[str, str]:
    """{compiled name: target name} for functions whose only naming change
    is their calling convention (a profile's /Gr or an explicit keyword)."""
    loose = sorted(ours - targets), sorted(targets - ours)
    text = demangle(loose[0] + loose[1])
    key = lambda name: _CC_TEXT.sub("", text[name]) if name in text else None
    wanted = defaultdict(list)
    for name in loose[1]:
        if key(name):
            wanted[key(name)].append(name)
    return {name: wanted[key(name)][0] for name in loose[0]
            if key(name) and len(wanted.get(key(name), ())) == 1}


def try_flags(image: str, units: list[str], drop: list[str], add: list[str],
              jobs: int = 4) -> list[dict]:
    """Compile each unit with its profile changed and score it like the
    build; return the functions whose score moves."""
    import os
    from concurrent.futures import ThreadPoolExecutor
    from homm3 import manifest
    from homm3.vc6.unstable_state import score_object
    from homm3.match import status
    os.environ[paths.IMAGE_ENV] = image
    by_unit = manifest.by_unit(paths.manifest(image))
    profiles = manifest.flag_profiles(paths.manifest(image))
    work = paths.image_build(image) / "patterns" / "flags"
    work.mkdir(parents=True, exist_ok=True)
    report = status.fn_fuzzy(json.loads(
        (paths.image_build(image) / "objdiff/report.json").read_text()))
    ledger = _ledger(image)

    def one(unit):
        spec = by_unit[unit]
        if not (paths.image_build(image) / "objdiff/target" / f"{unit}.c.obj").is_file():
            return unit, {}, ""           # nothing of the unit is compared
        flags = [f for f in profiles[spec["flags"]] if f not in drop] + list(add)
        out = work / f"{unit}.obj"
        out.unlink(missing_ok=True)
        proc = subprocess.run(
            [sys.executable, "-m", "homm3.core.cc_wrap", "--out", str(out),
             "--src", str(paths.ROOT / spec["source"]), "--", *flags],
            capture_output=True, text=True, cwd=paths.ROOT,
            env=dict(os.environ, HOMM3_IMAGE=image))
        if proc.returncode or not out.is_file():
            return unit, None, (proc.stdout + proc.stderr)[-800:]
        from homm3.delink.coffx import Obj
        target = Obj(paths.image_build(image) / "objdiff/target" / f"{unit}.c.obj")
        compiled = Obj(out)
        names = lambda o: {o.sym_name(i) for i, _v, _s in o.iter_symbols()}
        aliases = convention_aliases(names(compiled), names(target))
        if aliases:
            out.write_bytes(rename_symbols(out.read_bytes(), aliases))
        return unit, score_object(unit, out), ""

    rows = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for unit, scores, error in pool.map(one, units):
            if scores is None:
                rows.append({"unit": unit, "error": error})
                continue
            for name, after in scores.items():
                before = report.get((unit, name), report.get(name))
                if isinstance(before, dict):
                    before = before.get("fuzzy")
                row = ledger.get((unit, name))
                if before is None and row is not None:
                    before = row.cur
                if before is None or abs(after - before) > 1e-6:
                    rows.append({"unit": unit, "symbol": name, "before": before, "after": after,
                                 "max": row.max if row else None})
    names = demangle([r["symbol"] for r in rows if "symbol" in r])
    for r in rows:
        if "symbol" in r:
            r["function"] = short_name(r["symbol"], names)
    return rows


def render_try(rows) -> None:
    moved = [r for r in rows if "symbol" in r]
    better = sum(1 for r in moved if r["before"] is not None and r["after"] > r["before"])
    worse = sum(1 for r in moved if r["before"] is not None and r["after"] < r["before"])
    print(f"== {len(moved)} function(s) move: {better} better, {worse} worse")
    for r in rows:
        if "error" in r:
            print(f"  {r['unit']}: compile failed\n{r['error']}")
            continue
        b = "-" if r["before"] is None else f"{r['before']:.4f}"
        print(f"  {r['unit']:22} {b:>9} -> {r['after']:8.4f}  (MAX {r['max']})  {r['function']}")


# --- inline ----------------------------------------------------------------------

UNNAMED = re.compile(r"^(?:\$|fn_[0-9a-f]+$)")


def _call_sequence(body: bytes, relocs: dict) -> list[str]:
    return [relocs[site][0] for site in sorted(relocs)
            if relocs[site][1] == REL32 and site >= 1 and body[site - 1] == CALL]


def _calls(body: bytes, relocs: dict) -> Counter:
    return Counter(ref for site, (ref, kind) in relocs.items()
                   if kind == REL32 and site >= 1 and body[site - 1] == CALL)


def sweep_inline(images, *, all_units=False, limit=None) -> dict:
    per_callee: dict[tuple, dict] = {}
    names = set()
    for image in images:
        for fn in functions(image):
            if not all_units and not ob1(fn.flags):
                continue
            a, b = _calls(fn.ours, fn.ours_relocs), _calls(fn.retail, fn.retail_relocs)
            names.add(fn.name)
            for callee in a.keys() | b.keys():
                key = (image, callee)
                row = per_callee.setdefault(key, {
                    "image": image, "symbol": callee, "we_call_retail_expands": 0,
                    "retail_calls_we_expand": 0, "both_call": 0, "callers": [],
                    "unnamed": bool(UNNAMED.match(callee))})
                names.add(callee)
                extra = a[callee] - b[callee]
                if a[callee] and b[callee]:
                    row["both_call"] += min(a[callee], b[callee])
                if extra > 0:
                    row["we_call_retail_expands"] += extra
                elif extra < 0:
                    row["retail_calls_we_expand"] -= extra
                if extra and len(row["callers"]) < 6:
                    row["callers"].append((fn.unit, fn.name, fn.gap, extra))
    demangled = demangle(names)
    rows = []
    for row in per_callee.values():
        if row["unnamed"] or not (row["we_call_retail_expands"] or row["retail_calls_we_expand"]):
            continue
        row["callee"] = short_name(row["symbol"], demangled)
        row["callers"] = [f"{u}:{short_name(n, demangled)} gap {g:.3f} ({e:+d})"
                          for u, n, g, e in row["callers"]]
        row["weight"] = row["we_call_retail_expands"] + row["retail_calls_we_expand"]
        rows.append(row)
    rows.sort(key=lambda r: -r["weight"])
    return {"callees": rows[:limit] if limit else rows,
            "unnamed": sorted(unnamed_pairs(images, demangled), key=lambda r: -r["sites"])}


def unnamed_pairs(images, demangled=None) -> list[dict]:
    """Retail callees without a name that pair, site for site, with one
    callee of ours in equal-length call sequences: identity leads for the
    image's census or runtime map, not inlining differences."""
    pairs: dict[tuple, dict] = {}
    for image in images:
        for fn in functions(image):
            a, b = _call_sequence(fn.ours, fn.ours_relocs), _call_sequence(fn.retail, fn.retail_relocs)
            if len(a) != len(b):
                continue
            for x, y in zip(a, b):
                if x != y and UNNAMED.match(y) and not UNNAMED.match(x):
                    row = pairs.setdefault((image, x, y), {"image": image, "ours": x, "retail": y,
                                                           "sites": 0, "functions": set()})
                    row["sites"] += 1
                    row["functions"].add(fn.name)
    demangled = demangled or demangle({k[1] for k in pairs})
    out = []
    for row in pairs.values():
        row["callee"] = short_name(row["ours"], demangled)
        row["functions"] = len(row["functions"])
        out.append(row)
    return out


def render_inline(result) -> None:
    rows = result["unnamed"]
    print(f"== unnamed retail callees paired with ours site for site ({len(rows)}): identity leads")
    for r in rows:
        print(f"  {r['image']:8} {r['retail']:>12} <- {r['callee']}  ({r['sites']} sites in {r['functions']} functions)")
    rows = result["callees"]
    print()
    print(f"== callees whose call/expansion differs ({len(rows)}); "
          "+N = we call where retail expands, -N = retail calls where we expand")
    for r in rows:
        print(f"  {r['image']:8} +{r['we_call_retail_expands']:<3} -{r['retail_calls_we_expand']:<3} "
              f"both {r['both_call']:<3} {r['callee']}" + ("  (unnamed retail callee)" if r["unnamed"] else ""))
        for caller in r["callers"]:
            print(f"        {caller}")


# --- loops -----------------------------------------------------------------------

def loop_shape(body: bytes) -> dict:
    insns = decode(body)
    shape = Counter()
    for at, insn in insns.items():
        target = _branch_target(insn)
        if target is None:
            continue
        kind = "jmp" if insn.mnemonic == "jmp" else "jcc"
        shape[f"{kind}_back" if target <= at else f"{kind}_fwd"] += 1
    shape["ret"] = sum(1 for i in insns.values() if i.mnemonic.startswith("ret"))
    return dict(shape)


def sweep_loops(images, *, limit=None) -> dict:
    rows, names = [], set()
    for image in images:
        for fn in functions(image):
            if fn.gap == 0 and fn.max is not None:
                continue
            a, b = loop_shape(fn.ours), loop_shape(fn.retail)
            if not (a.get("jmp_back") or a.get("jcc_back") or b.get("jmp_back") or b.get("jcc_back")):
                continue
            uncond = a.get("jmp_back", 0) - b.get("jmp_back", 0)
            cond = a.get("jcc_back", 0) - b.get("jcc_back", 0)
            if not uncond and not cond:
                continue
            names.add(fn.name)
            rotation = uncond > 0 and cond < 0 or uncond < 0 and cond > 0
            rows.append({"image": image, "unit": fn.unit, "symbol": fn.name, "gap": fn.gap,
                         "max": fn.max, "ours": a, "retail": b,
                         "kind": ("retail rotates, ours does not" if uncond > 0 and cond < 0 else
                                  "ours rotates, retail does not" if rotation else
                                  "back-edge count differs"),
                         "weight": 2 * rotation + 1})
    demangled = demangle(names)
    for r in rows:
        r["function"] = short_name(r["symbol"], demangled)
    rows.sort(key=lambda r: (-r["weight"], -r["gap"]))
    return {"functions": rows[:limit] if limit else rows}


def render_loops(result) -> None:
    rows = result["functions"]
    print(f"== non-exact functions whose back edges differ ({len(rows)}); jmp/jcc back, ours vs retail")
    for r in rows:
        a, b = r["ours"], r["retail"]
        print(f"  [{r['weight']}] {r['image']:8} {r['unit']:22} gap {r['gap']:7.3f} "
              f"jmp {a.get('jmp_back', 0)}/{b.get('jmp_back', 0)} "
              f"jcc {a.get('jcc_back', 0)}/{b.get('jcc_back', 0)} "
              f"ret {a.get('ret', 0)}/{b.get('ret', 0)}  {r['kind']}: {r['function']}")


# --- ctors -----------------------------------------------------------------------

_ADDRESS = re.compile(r"0x[0-9a-f]{5,}")
_STORE = re.compile(r"^mov (?:byte|word|dword) ptr \[(?P<base>[a-z]+)")


def masked_rows(body: bytes) -> list[str]:
    """The body's instructions in address order, addresses and branch
    displacements masked."""
    rows = []
    for _at, insn in sorted(decode(body).items()):
        ops = insn.op_str
        if _branch_target(insn) is not None or insn.mnemonic == "call":
            ops = "@"
        rows.append(f"{insn.mnemonic} {_ADDRESS.sub('A', ops)}".strip())
    return rows


def store_permutations(ours: bytes, retail: bytes, gap: int = 3) -> dict:
    """Regions where both sides emit the same rows in another order and
    every displaced row is a store through one base register. Neighbouring
    edits separated by at most `gap` equal rows form one region (difflib
    reports a swap as a delete plus an insert around an equal row)."""
    import difflib
    a, b = masked_rows(ours), masked_rows(retail)
    ops = [op for op in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()]
    regions, current = [], None
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            if current and i2 - i1 <= gap:
                current["tail"] = (i2, j2)
            elif current:
                regions.append(current)
                current = None
            continue
        if current is None:
            current = {"start": (i1, j1), "tail": (i2, j2)}
        current["tail"] = (i2, j2)
    if current:
        regions.append(current)
    blocks, differing = [], sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in ops if t != "equal")
    for region in regions:
        (i1, j1), (i2, j2) = region["start"], region["tail"]
        left, right = a[i1:i2], b[j1:j2]
        if left == right or sorted(left) != sorted(right):
            continue
        moved = [x for x, y in zip(left, right) if x != y]
        stores = [_STORE.match(row) for row in moved]
        if moved and all(stores) and len({m.group("base") for m in stores}) == 1:
            blocks.append({"ours": left, "retail": right, "rows": len(moved)})
    permuted = sum(x["rows"] for x in blocks)
    return {"blocks": blocks, "permuted": permuted, "differing": differing}


def sweep_ctors(images, *, limit=None) -> dict:
    rows, names = [], set()
    for image in images:
        for fn in functions(image):
            if fn.max is None or fn.gap == 0:
                continue
            found = store_permutations(fn.ours, fn.retail)
            if not found["blocks"]:
                continue
            names.add(fn.name)
            share = found["permuted"] / max(found["differing"], 1)
            rows.append({"image": image, "unit": fn.unit, "symbol": fn.name, "gap": fn.gap,
                         "max": fn.max, "share": round(share, 3), **found})
    demangled = demangle(names)
    for r in rows:
        r["function"] = short_name(r["symbol"], demangled)
    rows.sort(key=lambda r: (-r["share"], r["gap"]))
    return {"functions": rows[:limit] if limit else rows}


def render_ctors(result) -> None:
    rows = result["functions"]
    print(f"== non-exact functions with same-base store permutations ({len(rows)}); "
          "share = permuted rows / differing rows")
    for r in rows:
        print(f"  {r['image']:8} {r['unit']:22} gap {r['gap']:7.3f} share {r['share']:.2f} "
              f"({r['permuted']}/{r['differing']})  {r['function']}")
        for block in r["blocks"][:2]:
            print(f"        ours   {' ; '.join(block['ours'])}\n"
                  f"        retail {' ; '.join(block['retail'])}")


# --- CLI -------------------------------------------------------------------------

def _images(text: str | None) -> list[str]:
    known = paths.images()
    if not text:
        return known
    chosen = [k.strip() for k in text.split(",") if k.strip()]
    unknown = [k for k in chosen if k not in known]
    if unknown:
        raise SystemExit(f"[patterns] unknown image(s) {unknown}; pinned: {known}")
    return chosen


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="homm3 patterns", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, text in (("cc", "calling-convention signatures and caller cleanup"),
                       ("flags", "x87 /Op signatures, or an A/B compile with --try"),
                       ("inline", "call-set asymmetries per callee (/Ob1 units)"),
                       ("loops", "back-edge shapes of non-exact functions"),
                       ("ctors", "store-order permutations (constructor shape)")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--images", help="comma-separated image keys (default: every pinned image)")
        p.add_argument("--json", action="store_true")
        p.add_argument("--limit", type=int, default=None, help="rows per list")
        if name == "inline":
            p.add_argument("--all-units", action="store_true",
                           help="include /Ob2 units too")
        if name == "flags":
            p.add_argument("--try", dest="try_units", metavar="UNIT[,UNIT]",
                           help="A/B compile these units with the changed profile")
            p.add_argument("--profile", help="with --try: every unit of this profile")
            p.add_argument("--image", default="game", help="with --try: the image")
            p.add_argument("--drop", action="append", default=[], help="with --try: flag to remove")
            p.add_argument("--add", action="append", default=[], help="with --try: flag to add")
            p.add_argument("--jobs", type=int, default=4)
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "flags" and (args.try_units or args.profile):
        from homm3 import manifest
        units = [u for u in (args.try_units or "").split(",") if u]
        if args.profile:
            units += [u["unit"] for u in manifest.units(paths.manifest(args.image))
                      if u.get("flags") == args.profile and u["unit"] not in units]
        rows = try_flags(args.image, units, args.drop, args.add, args.jobs)
        print(json.dumps(rows, indent=1)) if args.json else render_try(rows)
        return 0
    images = _images(args.images)
    if args.cmd == "cc":
        result, render = sweep_cc(images, limit=args.limit), render_cc
    elif args.cmd == "flags":
        result, render = sweep_flags(images, limit=args.limit), render_flags
    elif args.cmd == "inline":
        result, render = sweep_inline(images, all_units=args.all_units, limit=args.limit), render_inline
    elif args.cmd == "ctors":
        result, render = sweep_ctors(images, limit=args.limit), render_ctors
    else:
        result, render = sweep_loops(images, limit=args.limit), render_loops
    if args.json:
        print(json.dumps(result, indent=1, default=list))
    else:
        render(result)
    return 0


def logged_main(argv=None) -> int:
    from homm3.core.usage import append, run_logged
    import shlex
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = shlex.join(["homm3", "patterns", *argv])
    return run_logged(main, argv,
                      lambda rc, **meta: append(paths.SHARED_BUILD / "homm3_usage.log",
                                                cmd, rc, **meta), failure_rc=2)


if __name__ == "__main__":
    sys.exit(logged_main())
