import asyncio

import flet as ft

from cache_engine import CacheConfig, CacheEngine, InputUnit, ReadPolicy, ReplacementPolicy
from stats_analysis import (
    DEFAULT_SEED,
    compute_stats,
    format_log,
    random_sequence,
    seq_mid_repeat,
    seq_sequential,
    verify_against_engine,
)

# HARDCODED STUFF.
WAYS = 4
MEMORY_BLOCKS = 1024
STAT_LABELS = [
    "Memory Access Count",
    "Cache Hit Count",
    "Cache Miss Count",
    "Cache Hit Rate",
    "Cache Miss Rate",
    "Average Memory Access Time",
    "Total Memory Access Time",
]
READ_LABELS = {
    "Non-load-through": ReadPolicy.NON_LOAD_THROUGH,
    "Load-through": ReadPolicy.LOAD_THROUGH,
}

# validation helpers
# Size Check: Power of 2 ka ba?
def _pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0

# Int checker: whole number lang ba?
def _int(text: str, label: str) -> int:
    text = str(text).strip()
    if not text.lstrip("-").isdigit():
        raise ValueError(f"{label} must be a whole number.")
    return int(text)

# Float checker: whole number or decimal number lang ba? <- for time values
def _float(text: str, label: str) -> float:
    try:
        value = float(str(text).strip())
    except ValueError:
        raise ValueError(f"{label} must be a number.") from None
    if value < 0:
        raise ValueError(f"{label} cannot be negative.")
    return value

# Parse the sequence of numbers in the Data box. It can be in Blocks, Address (Decimal), or Address (Hex) format.
def parse_sequence(text: str, unit: str, block_size: int) -> list[int]:
    """Parse the Data box. unit is 'Blocks', 'Address (Decimal)' or 'Address (Hex)'."""
    tokens = [t for t in text.replace(",", " ").split() if t]
    if not tokens:
        raise ValueError("Enter some data first.")
    limit = MEMORY_BLOCKS if unit == "Blocks" else MEMORY_BLOCKS * block_size
    values = []
    for token in tokens:
        try:
            value = int(token, 16) if unit == "Address (Hex)" else int(token, 10)
        except ValueError:
            raise ValueError(f"'{token}' is not a valid {unit.lower()} value.") from None
        if not 0 <= value < limit:
            raise ValueError(f"{token} is outside main memory (0 to {limit - 1}).")
        values.append(value)
    return values


# STYLES
BG, FIELD, TEXT, MUTED, ACCENT = "#323232", "#141414", "#DCDCDC", "#9A9A9A", "#005064"
BTN, BTN_HOVER, BTN_TEXT = "#AFACAC", "#DCDCDC", "#141414"
HIT, MISS = ft.Colors.GREEN_800, ft.Colors.DEEP_ORANGE_800
FONT = "Helvetica"


def label(text, **kw):
    return ft.Text(text, color=TEXT, font_family=FONT, **kw)


def text_input(value="", width=200, hint="Enter a number", **kw):
    return ft.TextField(
        value=value, width=width, hint_text=hint, dense=True, filled=True, bgcolor=FIELD,
        color=TEXT, border_color=ACCENT, hint_style=ft.TextStyle(color=MUTED), **kw,
    )


def dropdown(options, value, width=150, on_select=None):
    return ft.Dropdown(
        value=value, width=width, dense=True, filled=True, bgcolor=FIELD, color=TEXT,
        border_color=ACCENT, options=[ft.DropdownOption(text=o) for o in options],
        on_select=on_select,
    )


def grey_button(text, on_click, width=None, height=40):
    return ft.Button(
        content=ft.Text(text, color=BTN_TEXT, font_family=FONT),
        on_click=on_click, width=width, height=height,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.HOVERED: BTN_HOVER, ft.ControlState.DEFAULT: BTN},
            shape=ft.RoundedRectangleBorder(radius=3),
        ),
    )


def _log_line(t) -> ft.Text:
    ev = "-" if t.evicted_block is None else f"evicted {t.evicted_block}"
    return ft.Text(
        f"{t.step:04d} | block {t.block_address:04d} | set {t.set_index:03d} | tag {t.tag:03d} "
        f"| way {t.way_index} | {'HIT ' if t.is_hit else 'MISS'} | {ev} | {t.access_time_ns:g} ns",
        size=12, font_family="monospace", color=ft.Colors.GREEN_300 if t.is_hit else ft.Colors.ORANGE_300,
    )


def main(page: ft.Page):
    page.title = "Cache Simulator"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 0

    state = {"cfg": None, "traces": [], "pos": 0, "token": 0}

    # home
    cache_size = text_input("16")
    cache_size_dt = dropdown(["Blocks", "Words"], "Blocks", 121)
    memory_size = text_input(str(MEMORY_BLOCKS), read_only=True)
    memory_dt = dropdown(["Blocks"], "Blocks", 121)
    memory_dt.disabled = True
    set_size = text_input(str(WAYS), 133, read_only=True)
    block_size = text_input("16", 133)
    cache_time = text_input("1", 133)
    memory_time = text_input("10", 133)
    replacement = ft.RadioGroup(
        value="LRU",
        content=ft.Row([
            ft.Radio(value="LRU", label="LRU", label_style=ft.TextStyle(color=TEXT), active_color=ACCENT),
            ft.Radio(value="MRU", label="MRU", label_style=ft.TextStyle(color=TEXT), active_color=ACCENT),
        ]),
    )
    read_mode = ft.RadioGroup(
        value="Non-load-through",
        content=ft.Row([
            ft.Radio(value="Non-load-through", label="Non Load-Through",
                     label_style=ft.TextStyle(color=TEXT), active_color=ACCENT),
            ft.Radio(value="Load-through", label="Load-Through",
                     label_style=ft.TextStyle(color=TEXT), active_color=ACCENT),
        ]),
    )
    data = text_input("", 200, hint="e.g. 0, 1, 2, 3", multiline=True, min_lines=6, max_lines=6)
    data_type = dropdown(["Blocks", "Address (Hex)", "Address (Decimal)"], "Blocks", 160)
    loops = dropdown([str(i) for i in range(1, 11)], "1", 150)
    seed_box = text_input(str(DEFAULT_SEED), 100)
    error = ft.Text("", color=ft.Colors.RED_300, font_family=FONT)

    def row(name, control, extra=None):
        return ft.Row(
            [ft.Container(label(name), width=200), control,
             ft.Container(extra, width=170) if extra is not None else ft.Container(width=170)],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def unit(text):
        return label(text)

    # button hepers
    def blocks_in_cache() -> int:
        n = _int(cache_size.value, "Cache size")
        b = _int(block_size.value, "Block size")
        if not _pow2(b) or b < 2:
            raise ValueError("Block size must be a power of 2 and at least 2 words.")
        if cache_size_dt.value == "Words":
            if n % b:
                raise ValueError("Cache size in words must be a multiple of the block size.")
            n //= b
        if not _pow2(n) or n < 4:
            raise ValueError("Cache size must be a power of 2 and at least 4 blocks.")
        return n

    def load_case(letter):
        def handler():
            try:
                n = blocks_in_cache()
                if letter == "A":
                    seq = seq_sequential(n)
                elif letter == "B":
                    seq = seq_mid_repeat(n)
                else:
                    seq = random_sequence(_int(seed_box.value, "Seed"))
            except ValueError as exc:
                error.value = str(exc)
                page.update()
                return
            error.value = ""
            data_type.value = "Blocks"
            loops.value = "1"
            data.value = ", ".join(map(str, seq))
            page.update()

        return handler

    # output
    out_header = ft.Text("Cache Simulator (BSA)", size=32, color="white", font_family=FONT)
    out_subheader = ft.Text("Group 7: Inocencio, Lu, Reyes A., Reyes N., Weng", size=20, color="white", font_family=FONT)
    step_label = ft.Text("", weight=ft.FontWeight.BOLD, color=TEXT, font_family=FONT)
    detail_label = ft.Text("", color=MUTED, size=12, font_family=FONT)
    cache_table = ft.DataTable(
        columns=[ft.DataColumn(label("Set"))],
        rows=[],
        heading_row_color=ACCENT,
        data_row_color=FIELD,
        column_spacing=14,
        data_row_min_height=34,
        data_row_max_height=34,
    )
    log_view = ft.ListView(spacing=2, auto_scroll=True, expand=True)
    stat_names = [
        "Memory Access Count", "Cache Hit Count", "Cache Miss Count", "Cache Hit Rate",
        "Cache Miss Rate", "Miss Penalty", "Average Memory Access Time", "Total Memory Access Time",
    ]
    stat_labels = [label("") for _ in stat_names]
    previous_button = grey_button("Previous", lambda: step_by(-1), width=120)
    next_button = grey_button("Next", lambda: step_by(1), width=120)
    play_button = grey_button("Auto-play", lambda: None, width=120)
    skip_button = grey_button("Skip Simulation", lambda: skip(), width=200)
    back_button = grey_button("Back", lambda: show_setup(), width=120)

    def render():
        cfg, traces, pos = state["cfg"], state["traces"], state["pos"]
        if cfg is None:
            return
        shown = traces[:pos]
        last = shown[-1] if shown else None

        # cache table
        sets = (
            last.cache_snapshot
            if last
            else [[{"valid": False} for _ in range(cfg.ways)] for _ in range(cfg.num_sets)]
        )
        cache_table.columns = [ft.DataColumn(label("Set"))] + [
            ft.DataColumn(label(f"Way {w + 1}")) for w in range(cfg.ways)
        ]
        rows = []
        for s_idx, ways in enumerate(sets):
            cells = [ft.DataCell(label(str(s_idx)))]
            for w_idx, line in enumerate(ways):
                bg = None
                if last and last.set_index == s_idx and last.way_index == w_idx:
                    bg = HIT if last.is_hit else MISS
                cells.append(
                    ft.DataCell(
                        ft.Container(
                            label(f"{line['block_address']}" if line["valid"] else "—"),
                            bgcolor=bg, padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                            border_radius=3,
                        )
                    )
                )
            rows.append(ft.DataRow(cells=cells))
        cache_table.rows = rows

        # step label
        step_label.value = f"Step {pos} of {len(traces)}"
        if last:
            extra = f", evicted block {last.evicted_block}" if last.evicted_block is not None else ""
            detail_label.value = (
                f"Block {last.block_address} -> set {last.set_index}, way {last.way_index + 1}: "
                f"{'HIT' if last.is_hit else 'MISS'}{extra}"
            )
        else:
            detail_label.value = "Cache is empty."

        # stats
        if shown:
            st = compute_stats(shown, cfg)
            vals = [
                f"{st['total_accesses']}", f"{st['hits']}", f"{st['misses']}",
                f"{st['hit_rate']:.2%}", f"{st['miss_rate']:.2%}",
                f"{CacheEngine(cfg).miss_penalty_ns:g} ns",
                f"{st['amat_ns']:.2f} ns", f"{st['total_time_ns']:,.1f} ns",
            ]
        else:
            vals = ["0", "0", "0", "0.00%", "0.00%", f"{CacheEngine(cfg).miss_penalty_ns:g} ns",
                    "0.00 ns", "0.00 ns"]
        for ctl, name, v in zip(stat_labels, stat_names, vals):
            ctl.value = f"{name}: {v}"

        # log 
        have = len(log_view.controls)
        if have != len(shown):
            if 0 < have < len(shown):
                log_view.controls.extend(_log_line(t) for t in shown[have:])
            else:
                log_view.controls = [_log_line(t) for t in shown]

        previous_button.disabled = pos <= 0
        next_button.disabled = pos >= len(traces)
        play_button.disabled = pos >= len(traces)
        page.update()

    def step_by(delta):
        state["token"] += 1  # stops auto-play
        n = len(state["traces"])
        state["pos"] = max(0, min(n, state["pos"] + delta))
        render()

    def skip():
        state["token"] += 1
        state["pos"] = len(state["traces"])
        render()

    async def autoplay():
        state["token"] += 1
        token = state["token"]
        while state["token"] == token and state["pos"] < len(state["traces"]):
            state["pos"] += 1
            render()
            await asyncio.sleep(0.3)

    play_button.on_click = autoplay

    # navi
    setup_view = ft.Column(spacing=8)
    output_view = ft.Column(spacing=14, visible=False)

    def show_setup():
        state["token"] += 1
        out_header.value = "Cache Simulator (BSA)"
        out_subheader.value = "Group 7: Inocencio, Lu, Reyes A., Reyes N., Weng"
        setup_view.visible = True
        output_view.visible = False
        page.update()

    def start_simulation():
        try:
            b = _int(block_size.value, "Block size")
            n = blocks_in_cache()
            unit_name = data_type.value
            seq = parse_sequence(data.value, unit_name, b) * int(loops.value)
            cfg = CacheConfig(
                cache_blocks=n, ways=WAYS, block_size_words=b, memory_blocks=MEMORY_BLOCKS,
                replacement_policy=ReplacementPolicy[replacement.value],
                read_policy=READ_LABELS[read_mode.value],
                input_unit=InputUnit.BLOCKS if unit_name == "Blocks" else InputUnit.WORDS,
                cache_access_time_ns=_float(cache_time.value, "Cache access time"),
                memory_access_time_ns=_float(memory_time.value, "Main memory access time"),
            )
            engine = CacheEngine(cfg)
            engine.run(seq)
            verify_against_engine(engine, cfg)  # the group's own cross-check
        except (ValueError, AssertionError) as exc:
            error.value = str(exc) or "The engine's self-check failed."
            page.update()
            return
        error.value = ""
        state.update(cfg=cfg, traces=engine.traces, pos=0, token=state["token"] + 1)
        log_view.controls = []
        out_header.value = f"Cache Simulator (BSA-{replacement.value})"
        out_subheader.value = f"Group 7: Inocencio, Lu, Reyes A., Reyes N., Weng"
        setup_view.visible = False
        output_view.visible = True
        render()

    # layout
    setup_view.controls = [
        row("Cache Size", cache_size, cache_size_dt),
        row("Main Memory Size", memory_size, memory_dt),
        row("Set Size", ft.Row([set_size, unit("block/s")])),
        row("Block Size", ft.Row([block_size, unit("word/s")])),
        row("Cache Access Time", ft.Row([cache_time, unit("ns")])),
        row("Main Memory Access Time", ft.Row([memory_time, unit("ns")])),
        row("Replacement Policy", replacement),
        row("Read Mode/Type", read_mode),
        row("Data", data, data_type),
        row("Test Cases", ft.Row([
            grey_button("A", load_case("A"), width=50),
            grey_button("B", load_case("B"), width=50),
            grey_button("C (random)", load_case("C"), width=110),
        ]), ft.Row([label("Seed"), seed_box], spacing=6)),
        row("No. of Loops", loops),
        row("", error, grey_button("Start Simulation", start_simulation, width=135, height=43)),
    ]

    output_view.controls = [
        step_label,
        detail_label,
        ft.Row(
            [
                ft.Container(
                    ft.Column([cache_table], scroll=ft.ScrollMode.AUTO),
                    width=500, height=462, bgcolor=FIELD,
                    border=ft.Border.all(1, ACCENT),
                ),
                ft.Container(log_view, width=560, height=462, bgcolor=FIELD, padding=8,
                             border=ft.Border.all(1, ACCENT)),
            ],
            wrap=True, vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        ft.Row(
            [
                ft.Column(stat_labels[:4], spacing=8, width=330),
                ft.Column(stat_labels[4:], spacing=8, width=400),
                ft.Row([back_button, previous_button, next_button, play_button, skip_button],
                       spacing=8),
            ],
            wrap=True, vertical_alignment=ft.CrossAxisAlignment.START,
        ),
    ]

    page.add(
        ft.Container(
            padding=ft.Padding.only(left=40, right=40, top=30, bottom=30),
            alignment=ft.Alignment.TOP_CENTER,
            content=ft.Column(
                width=1120,
                spacing=22,
                controls=[
                    ft.Container(padding=ft.Padding.only(left=16, top=16, bottom=8), content=out_header),
                    ft.Container(padding=ft.Padding.only(left=16, bottom=8), content=out_subheader),
                    setup_view,
                    output_view,
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
