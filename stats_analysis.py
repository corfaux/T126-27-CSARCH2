"""
M2 (Noms): Statistics, text trace log, seeded random generator, and
LRU-vs-MRU comparison tables for Machine 7 (4-Way BSA).

Depends only on the public interface of cache_engine.py:
    CacheEngine(config).run(sequence) -> List[AccessTrace]
    AccessTrace fields: step, raw_address, block_address, set_index, tag,
                        way_index, is_hit, evicted_block, access_time_ns

Statistics are recomputed here INDEPENDENTLY from the trace list and from
the closed-form timing formulas, then cross-checked against the engine's own
counters (verify_against_engine). A mismatch means a bug in one of the two.

Run `python stats_analysis.py` to print the comparison tables (Markdown) and
write per-run logs to ./logs/. Run `python stats_analysis.py --selftest` for
the verification checks.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Any, Dict, List, Sequence

from cache_engine import (
    AccessTrace,
    CacheConfig,
    CacheEngine,
    ReadPolicy,
    ReplacementPolicy,
)

DEFAULT_SEED = 126  # fixed so screenshots / README tables are reproducible
MEMORY_BLOCKS = 1024


# --------------------------------------------------------------------------
# Seeded random generator (test case c)
# --------------------------------------------------------------------------
def random_sequence(seed: int = DEFAULT_SEED, length: int = 64,
                    memory_blocks: int = MEMORY_BLOCKS) -> List[int]:
    """64 block accesses in [0, memory_blocks-1]. Same seed -> same sequence.
    Uses a private Random instance so global RNG state never interferes."""
    rng = random.Random(seed)
    return [rng.randrange(memory_blocks) for _ in range(length)]


# --------------------------------------------------------------------------
# Test sequences (M4 owns these; provided so the tables can be generated.
# Replace/delete if M4 ships their own module -- interface is just List[int].)
# --------------------------------------------------------------------------
def seq_sequential(n: int) -> List[int]:
    """Test A: blocks 0..2n-1, repeated twice."""
    return list(range(2 * n)) * 2


def seq_mid_repeat(n: int) -> List[int]:
    """Test B: 0..n-1, then 0..2n-1 twice, then the reverse pattern
    (n-1..0, 2n-1..0, 2n-1..0). For n=4 this matches the spec example."""
    fwd = list(range(n)) + list(range(2 * n)) * 2
    rev = list(range(n - 1, -1, -1)) + list(range(2 * n - 1, -1, -1)) * 2
    return fwd + rev


# --------------------------------------------------------------------------
# Timing model (documented in README)
# --------------------------------------------------------------------------
def hit_time(cfg: CacheConfig) -> float:
    """Hit: one cache access, Tc."""
    return cfg.cache_access_time_ns


def miss_time(cfg: CacheConfig) -> float:
    """Miss time (total time for an access that misses).
    Non-load-through: Tc (detect miss) + B*Tm (load whole block) + Tc (CPU reads from cache)
    Load-through:     Tc (detect miss) + Tm  (requested word forwarded to CPU as it arrives;
                      the rest of the block fills the cache in parallel, off the critical path)
    """
    tc, tm, b = cfg.cache_access_time_ns, cfg.memory_access_time_ns, cfg.block_size_words
    if cfg.read_policy == ReadPolicy.LOAD_THROUGH:
        return tc + tm
    return tc + b * tm + tc


# --------------------------------------------------------------------------
# The seven statistics
# --------------------------------------------------------------------------
def compute_stats(traces: Sequence[AccessTrace], cfg: CacheConfig) -> Dict[str, Any]:
    """1 total accesses, 2 hits, 3 misses, 4 hit rate, 5 miss rate,
    6 average memory access time, 7 total memory access time.

    Computed from the trace hit/miss flags + closed-form times (NOT from the
    engine's running totals) so it serves as an independent check.
    """
    total = len(traces)
    hits = sum(1 for t in traces if t.is_hit)
    misses = total - hits
    total_time = hits * hit_time(cfg) + misses * miss_time(cfg)
    hit_rate = hits / total if total else 0.0
    miss_rate = misses / total if total else 0.0
    return {
        "total_accesses": total,
        "hits": hits,
        "misses": misses,
        "hit_rate": hit_rate,
        "miss_rate": miss_rate,
        # AMAT == total_time / total; equivalently Th*hit_rate + Tmiss*miss_rate
        "amat_ns": total_time / total if total else 0.0,
        "total_time_ns": total_time,
    }


def verify_against_engine(engine: CacheEngine, cfg: CacheConfig) -> None:
    """Raise AssertionError if our independent stats disagree with the engine."""
    mine = compute_stats(engine.traces, cfg)
    eng = engine.get_stats()
    assert mine["total_accesses"] == eng["total_accesses"], "total accesses differ"
    assert mine["hits"] == eng["hits"], "hit count differs"
    assert mine["misses"] == eng["misses"], "miss count differs"
    assert abs(mine["total_time_ns"] - eng["total_access_time_ns"]) < 1e-9, "total time differs"
    assert abs(mine["amat_ns"] - eng["average_access_time_ns"]) < 1e-9, "AMAT differs"
    # internal identity: AMAT = hit_rate*Th + miss_rate*Tmiss
    ident = mine["hit_rate"] * hit_time(cfg) + mine["miss_rate"] * miss_time(cfg)
    assert abs(ident - mine["amat_ns"]) < 1e-9, "AMAT identity violated"


# --------------------------------------------------------------------------
# Text trace log (required for both animated and final-snapshot modes)
# --------------------------------------------------------------------------
def format_log(traces: Sequence[AccessTrace], cfg: CacheConfig,
               title: str = "", seed: int | None = None) -> str:
    lines: List[str] = []
    if title:
        lines.append(f"# {title}")
    lines.append(
        f"# n={cfg.cache_blocks} blocks, {cfg.ways}-way ({cfg.num_sets} sets), "
        f"block size={cfg.block_size_words} words, memory={cfg.memory_blocks} blocks, "
        f"replacement={cfg.replacement_policy.value}, read={cfg.read_policy.value}"
    )
    lines.append(
        f"# Tc={cfg.cache_access_time_ns}ns  Tm={cfg.memory_access_time_ns}ns/word  "
        f"hit={hit_time(cfg)}ns  miss={miss_time(cfg)}ns"
        + (f"  seed={seed}" if seed is not None else "")
    )
    lines.append(f"{'Step':>4} | {'Block':>5} | {'Set':>3} | {'Tag':>4} | {'Way':>3} | "
                 f"{'Result':<4} | {'Evicted':>7} | {'Time(ns)':>8}")
    lines.append("-" * 62)
    for t in traces:
        ev = "-" if t.evicted_block is None else str(t.evicted_block)
        lines.append(
            f"{t.step:>4} | {t.block_address:>5} | {t.set_index:>3} | {t.tag:>4} | "
            f"{t.way_index:>3} | {'HIT' if t.is_hit else 'MISS':<4} | {ev:>7} | "
            f"{t.access_time_ns:>8.1f}"
        )
    return "\n".join(lines)


def format_stats(stats: Dict[str, Any]) -> str:
    return "\n".join([
        f"Total memory accesses : {stats['total_accesses']}",
        f"Cache hits            : {stats['hits']}",
        f"Cache misses          : {stats['misses']}",
        f"Hit rate              : {stats['hit_rate'] * 100:.2f}%",
        f"Miss rate             : {stats['miss_rate'] * 100:.2f}%",
        f"Average access time   : {stats['amat_ns']:.2f} ns",
        f"Total access time     : {stats['total_time_ns']:.1f} ns",
    ])


def export_log(path: Path, traces, cfg, stats, title="", seed=None) -> None:
    """Write log + stats to a .txt file (the 'log export' deliverable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_log(traces, cfg, title, seed) + "\n\n" + format_stats(stats) + "\n",
                    encoding="utf-8")


# --------------------------------------------------------------------------
# Running experiments + comparison tables
# --------------------------------------------------------------------------
def make_config(n: int, repl: ReplacementPolicy, read: ReadPolicy,
                block_size: int = 16, ways: int = 4) -> CacheConfig:
    return CacheConfig(cache_blocks=n, ways=ways, block_size_words=block_size,
                       replacement_policy=repl, read_policy=read)


def run_case(seq: List[int], cfg: CacheConfig):
    eng = CacheEngine(cfg)
    eng.run(seq, include_snapshots=False)
    verify_against_engine(eng, cfg)  # every run is cross-checked
    return eng, compute_stats(eng.traces, cfg)


def sequences_for(n: int, seed: int = DEFAULT_SEED) -> Dict[str, List[int]]:
    return {"A (sequential)": seq_sequential(n),
            "B (mid-repeat)": seq_mid_repeat(n),
            "C (random)": random_sequence(seed)}


def comparison_table(n: int = 16, block_size: int = 16, seed: int = DEFAULT_SEED) -> str:
    """Markdown table: every test case x read policy, LRU vs MRU side by side."""
    rows = ["| Test | Read policy | Policy | Accesses | Hits | Misses | Hit % | Miss % | AMAT (ns) | Total (ns) |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for name, seq in sequences_for(n, seed).items():
        for read in (ReadPolicy.NON_LOAD_THROUGH, ReadPolicy.LOAD_THROUGH):
            for repl in (ReplacementPolicy.LRU, ReplacementPolicy.MRU):
                _, s = run_case(seq, make_config(n, repl, read, block_size))
                rows.append(
                    f"| {name} | {read.value} | {repl.value} | {s['total_accesses']} | "
                    f"{s['hits']} | {s['misses']} | {s['hit_rate']*100:.2f} | "
                    f"{s['miss_rate']*100:.2f} | {s['amat_ns']:.2f} | {s['total_time_ns']:.1f} |")
    return "\n".join(rows)


def export_all_logs(out_dir: Path, sizes=(16, 4, 64), seed: int = DEFAULT_SEED) -> int:
    """Write one log file per run in the test matrix. Returns number written."""
    count = 0
    for n in sizes:
        for name, seq in sequences_for(n, seed).items():
            tag = name[0].lower()
            for read in (ReadPolicy.NON_LOAD_THROUGH, ReadPolicy.LOAD_THROUGH):
                for repl in (ReplacementPolicy.LRU, ReplacementPolicy.MRU):
                    cfg = make_config(n, repl, read)
                    eng, s = run_case(seq, cfg)
                    lt = "LT" if read == ReadPolicy.LOAD_THROUGH else "nonLT"
                    fname = f"m7_test{tag}_{repl.value}_{lt}_n{n}.txt"
                    export_log(out_dir / fname, eng.traces, cfg, s,
                               title=f"Machine 7 test {name}",
                               seed=seed if tag == "c" else None)
                    count += 1
    return count


# --------------------------------------------------------------------------
# Self-test (hand-verifiable cases + reproducibility)
# --------------------------------------------------------------------------
def selftest() -> None:
    # 1. Seeded RNG: reproducible, in range, length 64, different seed differs
    a, b = random_sequence(7), random_sequence(7)
    assert a == b and len(a) == 64 and all(0 <= x < 1024 for x in a)
    assert random_sequence(8) != a

    # 2. Spec example for test B at n=4
    assert seq_mid_repeat(4) == (
        [0, 1, 2, 3, 0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 2, 3, 4, 5, 6, 7,
         3, 2, 1, 0, 7, 6, 5, 4, 3, 2, 1, 0, 7, 6, 5, 4, 3, 2, 1, 0])
    assert seq_sequential(4) == list(range(8)) * 2

    # 3. Hand-computed: n=4 (1 set, 4 ways), sequential 0..7,0..7, LRU.
    #    Cyclic 8-block pattern through 4 ways under LRU thrashes: 16 misses, 0 hits.
    cfg = make_config(4, ReplacementPolicy.LRU, ReadPolicy.NON_LOAD_THROUGH)
    _, s = run_case(seq_sequential(4), cfg)
    assert (s["hits"], s["misses"]) == (0, 16), s
    #    miss = 1 + 16*10 + 1 = 162 ns -> total 16*162 = 2592
    assert s["total_time_ns"] == 16 * 162 and s["amat_ns"] == 162
    #    MRU on same pattern: 0-3 fill (4 miss); 4 evicts 3; 5 evicts 4; 6 evicts 5; 7 evicts 6
    #    -> set {0,1,2,7}; second pass: 0,1,2 hit; 3 miss (evicts 2, the MRU) -> {0,1,3,7};
    #    4 miss (evicts 3), 5 miss (evicts 4), 6 miss (evicts 5) -> {0,1,6,7}; 7 hit.
    #    Total: 4 hits, 12 misses.
    _, m = run_case(seq_sequential(4), make_config(4, ReplacementPolicy.MRU, ReadPolicy.NON_LOAD_THROUGH))
    assert (m["hits"], m["misses"]) == (4, 12), m

    # 4. Load-through is strictly cheaper per miss; hit/miss counts are identical
    _, lt = run_case(seq_sequential(4), make_config(4, ReplacementPolicy.LRU, ReadPolicy.LOAD_THROUGH))
    assert lt["hits"] == s["hits"] and lt["total_time_ns"] == 16 * 11

    # 5. Reproducible: same seed -> identical stats on two fresh runs
    r1 = run_case(random_sequence(), make_config(16, ReplacementPolicy.LRU, ReadPolicy.NON_LOAD_THROUGH))[1]
    r2 = run_case(random_sequence(), make_config(16, ReplacementPolicy.LRU, ReadPolicy.NON_LOAD_THROUGH))[1]
    assert r1 == r2

    # 6. Engine cross-check over the full matrix (run_case asserts each run)
    for n in (4, 16, 64):
        for seq in sequences_for(n).values():
            for read in ReadPolicy:
                for repl in ReplacementPolicy:
                    run_case(seq, make_config(n, repl, read))
    print("All self-tests passed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--logs", default="logs", help="directory for exported logs")
    ap.add_argument("--n", type=int, nargs="*", default=[16, 4, 64])
    args = ap.parse_args()
    if args.selftest:
        selftest()
    else:
        for n in args.n:
            print(f"\n### n = {n} (block size 16, seed {DEFAULT_SEED})\n")
            print(comparison_table(n))
        k = export_all_logs(Path(args.logs), tuple(args.n))
        print(f"\nWrote {k} log files to {args.logs}/")
