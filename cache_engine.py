from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Optional, Dict, Any


class ReplacementPolicy(str, Enum):
    LRU = "LRU"
    MRU = "MRU"


class ReadPolicy(str, Enum):
    LOAD_THROUGH = "LOAD_THROUGH"
    NON_LOAD_THROUGH = "NON_LOAD_THROUGH"


class InputUnit(str, Enum):
    BLOCKS = "BLOCKS"
    WORDS = "WORDS"


@dataclass
class CacheConfig:
    cache_blocks: int = 32
    ways: int = 4
    block_size_words: int = 16
    memory_blocks: int = 1024
    replacement_policy: ReplacementPolicy = ReplacementPolicy.LRU
    read_policy: ReadPolicy = ReadPolicy.NON_LOAD_THROUGH
    input_unit: InputUnit = InputUnit.BLOCKS
    cache_access_time_ns: float = 1.0
    memory_access_time_ns: float = 10.0

    def __post_init__(self) -> None:
        if self.cache_blocks % self.ways != 0:
            raise ValueError("cache_blocks must be divisible by ways.")
        if self.memory_blocks < 1024:
            raise ValueError("memory_blocks must be at least 1024.")
        if self.block_size_words <= 0:
            raise ValueError("block_size_words must be positive.")

    @property
    def num_sets(self) -> int:
        return self.cache_blocks // self.ways

    @property
    def memory_words(self) -> int:
        return self.memory_blocks * self.block_size_words


@dataclass
class CacheLine:
    way: int
    valid: bool = False
    tag: Optional[int] = None
    block_address: Optional[int] = None
    last_used: int = -1  # Logical timestamp for LRU/MRU

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccessTrace:
    step: int
    raw_address: int
    block_address: int
    word_offset: Optional[int]
    set_index: int
    tag: int
    way_index: int
    is_hit: bool
    evicted_block: Optional[int]
    access_time_ns: float
    cache_snapshot: List[List[Dict[str, Any]]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CacheEngine:
    """4-Way Block Set Associative (BSA) Cache Simulator Engine."""

    def __init__(self, config: Optional[CacheConfig] = None) -> None:
        self.config = config or CacheConfig()
        self.reset()

    def reset(self) -> None:
        """Reset cache state, counters, and trace history."""
        self.sets: List[List[CacheLine]] = [
            [CacheLine(way=w) for w in range(self.config.ways)]
            for _ in range(self.config.num_sets)
        ]
        self.step_count: int = 0
        self.hits: int = 0
        self.misses: int = 0
        self.total_access_time_ns: float = 0.0
        self.traces: List[AccessTrace] = []

    @property
    def miss_penalty_ns(self) -> float:
        """
        Miss penalty based on read policy:
        - Non-load-through: Tc (miss detect) + (block_size * Tm) + Tc (read from cache)
        - Load-through:     Tc (miss detect) + Tm (word forwarded directly to CPU)
        """
        tc = self.config.cache_access_time_ns
        tm = self.config.memory_access_time_ns
        if self.config.read_policy == ReadPolicy.LOAD_THROUGH:
            return tc + tm
        return tc + (self.config.block_size_words * tm) + tc

    def _decode_address(self, raw_address: int) -> tuple[int, Optional[int], int, int]:
        """Convert raw block/word address into (block_addr, word_offset, set_idx, tag)."""
        if raw_address < 0:
            raise ValueError(f"Address cannot be negative: {raw_address}")

        if self.config.input_unit == InputUnit.WORDS:
            if raw_address >= self.config.memory_words:
                raise ValueError(
                    f"Word address {raw_address} out of bounds (max {self.config.memory_words - 1})."
                )
            block_addr = raw_address // self.config.block_size_words
            word_offset: Optional[int] = raw_address % self.config.block_size_words
        else:
            if raw_address >= self.config.memory_blocks:
                raise ValueError(
                    f"Block address {raw_address} out of bounds (max {self.config.memory_blocks - 1})."
                )
            block_addr = raw_address
            word_offset = None

        set_index = block_addr % self.config.num_sets
        tag = block_addr // self.config.num_sets
        return block_addr, word_offset, set_index, tag

    def _select_victim_way(self, cache_set: List[CacheLine]) -> int:
        """Return first invalid way; otherwise apply LRU or MRU replacement."""
        for line in cache_set:
            if not line.valid:
                return line.way

        if self.config.replacement_policy == ReplacementPolicy.LRU:
            victim = min(cache_set, key=lambda line: line.last_used)
        else:
            victim = max(cache_set, key=lambda line: line.last_used)
        return victim.way

    def get_snapshot(self) -> List[List[Dict[str, Any]]]:
        """Return a serializable snapshot of all sets and ways."""
        return [
            [line.to_dict() for line in cache_set]
            for cache_set in self.sets
        ]

    def access(self, raw_address: int, include_snapshot: bool = True) -> AccessTrace:
        """Process a single memory access and return its trace record."""
        block_addr, word_offset, set_index, tag = self._decode_address(raw_address)
        self.step_count += 1
        cache_set = self.sets[set_index]

        # Check for cache hit
        hit_line = next((line for line in cache_set if line.valid and line.tag == tag), None)

        if hit_line is not None:
            is_hit = True
            self.hits += 1
            hit_line.last_used = self.step_count
            way_index = hit_line.way
            evicted_block = None
            access_time = self.config.cache_access_time_ns
        else:
            is_hit = False
            self.misses += 1
            way_index = self._select_victim_way(cache_set)
            target_line = cache_set[way_index]
            evicted_block = target_line.block_address if target_line.valid else None

            target_line.valid = True
            target_line.tag = tag
            target_line.block_address = block_addr
            target_line.last_used = self.step_count
            access_time = self.miss_penalty_ns

        self.total_access_time_ns += access_time

        trace = AccessTrace(
            step=self.step_count,
            raw_address=raw_address,
            block_address=block_addr,
            word_offset=word_offset,
            set_index=set_index,
            tag=tag,
            way_index=way_index,
            is_hit=is_hit,
            evicted_block=evicted_block,
            access_time_ns=access_time,
            cache_snapshot=self.get_snapshot() if include_snapshot else [],
        )
        self.traces.append(trace)
        return trace

    def run(self, sequence: List[int], include_snapshots: bool = True) -> List[AccessTrace]:
        """Execute a full sequence of memory accesses."""
        return [self.access(addr, include_snapshot=include_snapshots) for addr in sequence]

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate simulation metrics."""
        total = self.hits + self.misses
        return {
            "total_accesses": total,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
            "miss_rate": (self.misses / total) if total else 0.0,
            "miss_penalty_ns": self.miss_penalty_ns,
            "total_access_time_ns": self.total_access_time_ns,
            "average_access_time_ns": (self.total_access_time_ns / total) if total else 0.0,
        }