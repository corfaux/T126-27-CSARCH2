# M2 – Statistics, Timing Model & LRU vs MRU Analysis (Machine 7)

> Draft for M5 to merge into README.md. All numbers are produced by
> `python stats_analysis.py` (seed **126**, block size 16 words, Tc = 1 ns, Tm = 10 ns/word)
> and cross-checked against the engine counters on every run.

## Timing model

| Quantity | Formula |
|---|---|
| Hit time | `Tc` = 1 ns |
| Miss time, non-load-through | `Tc + B·Tm + Tc` = 1 + 16·10 + 1 = **162 ns** (detect miss, load whole block, then CPU reads from cache) |
| Miss time, load-through | `Tc + Tm` = 1 + 10 = **11 ns** (requested word forwarded to the CPU as it arrives; the rest of the block fills in parallel, off the critical path) |
| Hit rate / miss rate | hits / total, misses / total |
| Average memory access time | `total time / total accesses` = `hit% · Th + miss% · Tmiss` |
| Total memory access time | `hits · Th + misses · Tmiss` |

Seeded random: `random.Random(126)`, 64 draws from `[0, 1023]`. Same seed gives the same sequence (verified in `--selftest`).

## Results, n = 16 (4 sets × 4 ways)

| Test | Read policy | Policy | Hits | Misses | Hit % | AMAT (ns) | Total (ns) |
|---|---|---|---|---|---|---|---|
| A sequential (64) | Non-LT | LRU | 0 | 64 | 0.00 | 162.00 | 10368 |
| A sequential (64) | Non-LT | MRU | 16 | 48 | 25.00 | 121.75 | 7792 |
| A sequential (64) | LT | LRU | 0 | 64 | 0.00 | 11.00 | 704 |
| A sequential (64) | LT | MRU | 16 | 48 | 25.00 | 8.50 | 544 |
| B mid-repeat (160) | Non-LT | LRU | 16 | 144 | 10.00 | 145.90 | 23344 |
| B mid-repeat (160) | Non-LT | MRU | 68 | 92 | 42.50 | 93.58 | 14972 |
| B mid-repeat (160) | LT | LRU | 16 | 144 | 10.00 | 10.00 | 1600 |
| B mid-repeat (160) | LT | MRU | 68 | 92 | 42.50 | 6.75 | 1080 |
| C random (64) | Non-LT | LRU | 1 | 63 | 1.56 | 159.48 | 10207 |
| C random (64) | Non-LT | MRU | 1 | 63 | 1.56 | 159.48 | 10207 |
| C random (64) | LT | LRU | 1 | 63 | 1.56 | 10.84 | 694 |
| C random (64) | LT | MRU | 1 | 63 | 1.56 | 10.84 | 694 |

Edge runs (n = 4 single set, n = 64) are in `python stats_analysis.py` output and `logs/`.
Hit/miss counts do not depend on read policy; only the miss time does.

## Analysis

**Test A (sequential, 0..2n-1 twice).** The working set (2n blocks) is twice the cache. LRU always evicts the
block that will be needed soonest in a cyclic scan, so it **thrashes: 0 hits** at every n. MRU evicts the
newest block, which keeps the older blocks resident, so some blocks stay resident for the second pass
(16 of 64 at n = 16; exactly 25% for n = 4, 16, 64, i.e. n hits per run). MRU lowers non-LT AMAT from 162 to 121.75 ns (−25%).

**Test B (mid-repeat, then reverse).** The first segment (0..n-1) fits and gives early reuse; the repeated
0..2n-1 passes and the reversed passes re-touch recently used blocks. Reversal makes the most recently used
block the next one needed, which is exactly the case LRU handles poorly and MRU handles well. Result: MRU hit rate
**42.5% vs 10%** for LRU, and non-LT total time drops 23344 → 14972 ns (−36%). This is the largest MRU advantage.

**Test C (random, 64 accesses over 1024 blocks).** There is almost no reuse (1 hit at n = 16; 0 hits at n = 4;
2 at n = 64), so there is no recency pattern for either policy to exploit and LRU and MRU are **identical**.
Differences here would come only from the seed, not the policy.

**Read policy.** Because load-through only shortens the miss path, it cuts AMAT by about 15× here (162 → 11 ns on a
100%-miss run) regardless of replacement policy; the ranking of LRU vs MRU is unchanged, but the *absolute*
saving from MRU is smaller under load-through (e.g. B: 1600 → 1080 ns vs 23344 → 14972 ns).

**Takeaway.** MRU beats LRU on looping / scanning patterns larger than the cache (A, B); they tie on patterns
with no locality (C). LRU would win on workloads with temporal locality, which none of the three required tests
contains.

## Verification done
- Independent stat recomputation (from trace hit/miss flags + closed-form times) matches engine totals on all
  36 runs (3 tests × 2 repl × 2 read × n ∈ {4, 16, 64}).
- Hand-computed n = 4 cases: LRU sequential = 0 hits / 16 misses (2592 ns non-LT, 176 ns LT);
  MRU sequential = 4 hits / 12 misses.
- Test B sequence at n = 4 equals the spec example exactly.
