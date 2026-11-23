# 4-Way BSA Cache Simulation (LRU and MRU)

## Specifications
1. **Block Size:** Minimum of 16 words.
2. **Number of Cache Blocks:** Minimum of 16.
3. **Main Memory Size:** 1024 Blocks.
4. **Read Policy:** Load-through or Non-load-through

## Test Cases [Attach here the Snapshots]
Let _n_ be the total number of cache blocks. 
1. Sequential: Access up to 2n cache blocks. Repeat the sequence two times.
   a. LRU
   b. MRU
2. Mid-repeat blocks: Start at block 0 to n-1, then repeat the sequence up to 2n-1 twice. Afterward, reverse the sequence pattern.
   a. LRU
   b. MRU
3. Random: Generate a random sequence of 64 block accesses.
   a. LRU
   b. MRU



