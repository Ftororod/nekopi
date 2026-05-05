"""Power screen — Cancel / Reboot / Shutdown."""

from lib.theme import *

ITEMS = [
    ("Cancelar",  FG),
    ("Reboot",    ORANGE),
    ("Shutdown",  ERROR),
]


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "POWER", ERROR)

    idx = ctx.get("power_idx", 0)
    confirm = ctx.get("power_confirm", False)
    confirm_remaining = ctx.get("power_confirm_remaining", 0)

    y = CONTENT_Y + 4

    for i, (label, color) in enumerate(ITEMS):
        row_y = y + i * 22
        if i == idx:
            draw.rectangle([2, row_y - 2, 126, row_y + 16], fill=(18, 8, 10))
            draw.text((6, row_y), ">", font=FONT_LG, fill=FG)
            draw.text((18, row_y), label, font=FONT_LG, fill=color)
            if confirm and i > 0:
                draw.text((18, row_y + 14), f"Confirmar? ({confirm_remaining}s)",
                          font=FONT_SM, fill=WARN)
        else:
            draw.text((18, row_y), label, font=FONT_MD, fill=FG_DIM)

    draw_footer(draw, "\u2191\u2193 nav  \u25cf sel  \u2190 back", BORDER)
    return img
