"""Generic submenu renderer — used by tools, captures, services screens."""

from lib.theme import *
from lib.actions import ACTIONS, SUBMENUS

ROW_H = 14
MAX_VISIBLE = 5  # fits in content area with header+title+footer


def _status_badge(draw, x, y, action_type, status):
    """Draw a colored pill badge with label."""
    if action_type == "oneshot":
        label, bg_color, fg_color = "RUN", (30, 35, 50), FG_DIM
    elif action_type == "info":
        label, bg_color, fg_color = "INFO", (10, 20, 40), INFO
    elif status == "running":
        label, bg_color, fg_color = "ON", (0, 40, 20), OK
    elif status == "transitioning":
        label, bg_color, fg_color = "...", (40, 30, 0), WARN
    elif status == "error":
        label, bg_color, fg_color = "ERR", (40, 10, 10), ERROR
    else:
        label, bg_color, fg_color = "OFF", (30, 35, 50), FG_DIM

    tw = draw.textlength(label, font=FONT_SM)
    pad = 4
    pill_w = int(tw) + pad * 2
    rx = x - pill_w
    draw.rounded_rectangle([rx, y, rx + pill_w, y + 12], radius=3, fill=bg_color)
    draw.text((rx + pad, y + 1), label, font=FONT_SM, fill=fg_color)


def render_submenu(ctx, submenu_key, title):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, title)

    items = SUBMENUS[submenu_key]
    sel = ctx.get("submenu_idx", 0)
    statuses = ctx.get("statuses", {})
    total = len(items)

    # Scroll window
    if total <= MAX_VISIBLE:
        scroll_start = 0
    else:
        scroll_start = max(0, min(sel - MAX_VISIBLE // 2, total - MAX_VISIBLE))

    visible = items[scroll_start:scroll_start + MAX_VISIBLE]

    y = CONTENT_Y

    if scroll_start > 0:
        draw.text((W // 2 - 4, y - 4), "\u25b2", font=FONT_SM, fill=BORDER)

    for vi, action_id in enumerate(visible):
        i = scroll_start + vi
        action = ACTIONS[action_id]
        is_sel = (i == sel)
        status = statuses.get(action_id, "stopped")

        if is_sel:
            draw.rectangle([1, y - 1, 127, y + ROW_H - 3], fill=(10, 14, 24))

        draw.text((3, y), "\u25b6" if is_sel else " ", font=FONT_SM, fill=ACCENT if is_sel else BG)
        draw.text((13, y), action["title"], font=FONT_MD, fill=FG if is_sel else FG_DIM)
        _status_badge(draw, W - 3, y, action["type"], status)

        y += ROW_H

    if scroll_start + MAX_VISIBLE < total:
        draw.text((W // 2 - 4, y - 2), "\u25bc", font=FONT_SM, fill=BORDER)

    draw_footer(draw, "\u2191\u2193 nav  \u25cf act  \u2190 back", BORDER)
    return img
