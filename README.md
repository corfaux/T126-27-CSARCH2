# 4-Way BSA Cache Simulation (LRU and MRU)

4-way block set associative cache, LRU vs MRU.

**Live site:** TODO (GitHub Pages link)

## Specifications
| Parameter | Value |
|---|---|
| Associativity | 4-way block set associative |
| Replacement | LRU or MRU (selectable) |
| Cache blocks (n) | parameterized, power of 2, >= 4 |
| Block size | parameterized, power of 2, >= 2 words (default 16) |
| Main memory | fixed, 1024 blocks |
| Read policy | non-load-through or load-through (selectable) |
| Tc / Tm | 1 ns / 10 ns per word (editable) |
| Test C | 64 random blocks, seed 126 |

Miss time: non-load-through = Tc + B*Tm + Tc; load-through = Tc + Tm. Hit = Tc.

## Files
- `cache_engine.py` - simulation engine
- `stats_analysis.py` - test sequences, the seven statistics, text log, log export
- `main.py` - Flet GUI (shows the engine's trace; contains no cache logic)
- `logs/` - exported traces for tests A/B/C, LRU/MRU, both read policies, n = 4/16/64
- `m2_stats_and_analysis.md` - analysis of the three test cases

## Run locally
   python -m venv .venv
   .venv\Scripts\activate 
   pip install -r requirements.txt
   python main.py

Static site: `flet publish main.py`

## Analysis
TODO: copy/link the LRU vs MRU analysis from `m2_stats_and_analysis.md`.
