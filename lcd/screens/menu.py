"""Menu screen — main navigation."""

from lib.theme import *

ITEMS = [
    ("Dashboard",  CYAN),
    ("Tools",      OK),
    ("Captures",   ORANGE),
    ("Services",   PURPLE),
    ("Quick Check", INFO),
    ("WiFi Scan",  WARN),
    ("System",     FG),
    ("Power",      ERROR),
]


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "MENU")

    idx = ctx.get("menu_idx", 0)
    y = CONTENT_Y

    avail = H - CONTENT_Y - FOOTER_H - 2
    row_h = min(14, avail // len(ITEMS))

    for i, (label, color) in enumerate(ITEMS):
        row_y = y + i * row_h
        if i == idx:
            draw.rectangle([2, row_y - 1, 126, row_y + row_h - 2], fill=(10, 14, 24))
            draw.text((4, row_y), "\u25b6", font=FONT_SM, fill=ACCENT)
            draw.text((14, row_y), label, font=FONT_MD, fill=color)
        else:
            draw.text((14, row_y), label, font=FONT_SM, fill=FG_DIM)

    draw_footer(draw, "\u2191\u2193 nav  \u25cf/\u25b6 enter  \u2190 back", BORDER)

    return img
