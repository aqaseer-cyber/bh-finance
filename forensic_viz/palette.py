"""Design tokens for the dashboard renderer.

Light-mode instance of a validated categorical palette (worst adjacent
colour-vision-deficiency deltaE 24.2; aqua/yellow sit below 3:1 contrast on the
surface, so any series drawn in them must carry direct value labels — the
renderer does this, and the CSV export is the table-view fallback).
"""

# Chart surface & ink
SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

# Categorical slots — fixed order, never cycled
SERIES = [
    "#2a78d6",  # 1 blue
    "#1baf7a",  # 2 aqua
    "#eda100",  # 3 yellow
    "#008300",  # 4 green
    "#4a3aa7",  # 5 violet
    "#e34948",  # 6 red
]
BLUE, AQUA, YELLOW, GREEN, VIOLET, RED = SERIES

# Diverging pair (blue <-> red, neutral gray midpoint)
DIVERGING_POS_BAD = RED    # e.g. accruals above zero = earnings ahead of cash
DIVERGING_NEG = BLUE

# Delta text (direction x whether up is good)
DELTA_GOOD = "#006300"
DELTA_BAD = "#d03b3b"

# De-emphasis hue for context series
DEEMPHASIS = "#c3c2b7"

FONT_STACK = ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]
