"""
LCD theme — synchronized with nekopi-gui dark palette.

CSS source: /opt/nekopi/ui/index.html :root (dark mode)
  --bg: #060810       --text: #c8d6e5     --white: #f0f4f8
  --card-bg: #0c0f1a  --input-bg: #080b14 --terminal: #020408
  --blue: #2196f3     --cyan: #00e5ff     --green: #00e676
  --amber: #ffab00    --red: #ff1744      --orange: #ff6d00
  --purple: #7c4dff
"""

import datetime
from PIL import Image, ImageDraw, ImageFont

# Display
W, H = 128, 128

# Layout zones
HEADER_H  = 16    # top bar: clock + status icons
TITLE_H   = 14    # screen title
CONTENT_Y = HEADER_H + TITLE_H + 2  # 32 — content starts here
FOOTER_H  = 13

# --- Palette from GUI CSS variables (dark mode) ---

# Backgrounds
BG       = (0, 0, 0)        # pure black for max contrast on small LCD
BG_PANEL = (8, 12, 20)      # subtle tint — only for thin separators

# Foreground / text
FG       = (240, 244, 248)  # --white: #f0f4f8
FG_DIM   = (140, 156, 178)  # --text dimmed for LCD

# Accent
ACCENT     = (0, 229, 255)  # --cyan: #00e5ff
ACCENT_DIM = (33, 150, 243) # --blue: #2196f3

# States
OK    = (0, 230, 118)       # --green: #00e676
WARN  = (255, 171, 0)       # --amber: #ffab00
ERROR = (255, 23, 68)       # --red: #ff1744
INFO  = (33, 150, 243)      # --blue: #2196f3

# Extra
ORANGE  = (255, 109, 0)     # --orange: #ff6d00
PURPLE  = (124, 77, 255)    # --purple: #7c4dff

# Border / divider
BORDER = (30, 35, 50)

# --- Aliases ---
WHITE   = FG
CYAN    = ACCENT
GREEN   = OK
RED     = ERROR
YELLOW  = WARN
GRAY    = FG_DIM
DIM     = BORDER
BLUE    = INFO
MAGENTA = PURPLE

# --- Fonts ---
_SANS     = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_SANS_B   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

FONT_SM  = ImageFont.truetype(_SANS, 9)
FONT_MD  = ImageFont.truetype(_SANS, 10)
FONT_LG  = ImageFont.truetype(_SANS_B, 12)
FONT_XL  = ImageFont.truetype(_SANS_B, 16)
FONT_TTL = ImageFont.truetype(_SANS_B, 14)


def new_image():
    """Return a fresh 128x128 black image + draw context."""
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def draw_header(draw, ctx):
    """Global header (16px) — clock left + status icons right.
    Drawn on every screen except splash."""
    now = datetime.datetime.now().strftime("%H:%M")
    draw.text((4, 2), now, font=FONT_MD, fill=FG)

    # Status icons: PR KS OT RM
    statuses = ctx.get("statuses", {}) if isinstance(ctx, dict) else {}
    icons = [
        ("PR", statuses.get("profiler", "stopped")),
        ("KS", statuses.get("kismet", "stopped")),
        ("OT", statuses.get("ota_smart", "stopped")),
        ("RM", statuses.get("roaming", "stopped")),
    ]
    x = W - 4
    for label, status in reversed(icons):
        color = OK if status == "running" else (40, 45, 55)
        tw = draw.textlength(label, font=FONT_SM)
        x -= int(tw)
        draw.text((x, 4), label, font=FONT_SM, fill=color)
        x -= 4

    draw.line([(0, HEADER_H), (W, HEADER_H)], fill=BORDER)


def draw_title(draw, title, color=ACCENT):
    """Title bar (14px) — screen name below header."""
    draw.text((4, HEADER_H + 1), title, font=FONT_TTL, fill=color)
    draw.line([(0, HEADER_H + TITLE_H), (W, HEADER_H + TITLE_H)], fill=BORDER)


def draw_footer(draw, text, color=FG_DIM):
    """Bottom footer line."""
    draw.line([0, H - FOOTER_H, W, H - FOOTER_H], fill=BORDER)
    draw.text((3, H - FOOTER_H + 1), text, font=FONT_SM, fill=color)
