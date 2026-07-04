"""Design tokens — house brand palette (Colour Palette 07), applied app-wide.

Brand mandate: the four brand hues #0C3B2E (forest), #BB8A52 (tan), #FFBA00
(amber) and #6D9773 (sage) are fixed by the owner and are used exactly as
given, on the cream surface from the brand mockup. Two derived earth-tone
slots (#7A4A21 brown, #3E6B52 deep sage) extend the categorical set to six.

Validator record (dataviz palette checker, surface #F7F5EF, light mode):
- CVD separation PASSES (worst adjacent ΔE 20.4 protan / 16.6 tritan).
- Lightness-band and chroma-floor checks FAIL for the earth tones (they read
  muted by design); this is an accepted brand-fidelity deviation — the brand
  colours are a user mandate, not a generated placeholder palette.
- Contrast relief: #BB8A52 (2.8:1) and #FFBA00 (1.57:1) sit below 3:1 on the
  surface, so every series drawn in them must carry direct value labels — the
  renderers do this throughout, and the CSV export is the table-view fallback.
- The brand set has no red, so negative/bad states use one functional brick
  red (NEGATIVE, 5.3:1 on the surface — passes as a lone status colour). It
  is a status colour only and is never used as a categorical series slot
  (red next to brown fails protan CVD at ΔE 3.6).
"""

# Chart surface & ink (cream page, forest ink — per the brand mockup)
SURFACE = "#f7f5ef"
PAGE = "#efece2"
INK_PRIMARY = "#0c3b2e"
INK_SECONDARY = "#41584c"
INK_MUTED = "#6e7b6f"
GRIDLINE = "#e2ded0"
BASELINE = "#c9c3ae"

# Categorical slots — fixed order, never cycled
SERIES = [
    "#0c3b2e",  # 1 forest (brand)
    "#bb8a52",  # 2 tan (brand — relief labels required)
    "#ffba00",  # 3 amber (brand — relief labels required)
    "#6d9773",  # 4 sage (brand)
    "#7a4a21",  # 5 brown (derived)
    "#3e6b52",  # 6 deep sage (derived)
]
FOREST, TAN, AMBER, SAGE, BROWN, DEEP_SAGE = SERIES

# Functional status colour — the only red in the app (never a series slot)
NEGATIVE = "#b3402a"

# Diverging pair (bad above zero <-> good/neutral below, e.g. accruals)
DIVERGING_POS_BAD = NEGATIVE  # accruals above zero = earnings ahead of cash
DIVERGING_NEG = DEEP_SAGE

# Delta text (direction x whether up is good)
DELTA_GOOD = "#1e6b45"
DELTA_BAD = NEGATIVE

# De-emphasis hue for context series
DEEMPHASIS = "#c9c3ae"

FONT_STACK = ["Segoe UI", "DejaVu Sans", "Arial", "sans-serif"]

# GUI accents (Tk shell) — brand mockup: forest sidebar, amber accent
GUI_SIDEBAR_BG = "#0c3b2e"
GUI_SIDEBAR_FG = "#f7f5ef"
GUI_SIDEBAR_MUTED = "#a8bdb0"
GUI_ACCENT = "#ffba00"
GUI_ACCENT_ACTIVE = "#e0a300"
GUI_ACCENT_FG = "#0c3b2e"
GUI_SIDEBAR_BTN = "#175a45"
GUI_SIDEBAR_BTN_ACTIVE = "#1e6b52"
