"""WiFi Scan screen — shows nearby APs."""

from lib.theme import *


def _rssi_color(rssi):
    if rssi >= -50: return OK
    if rssi >= -70: return WARN
    if rssi >= -80: return ORANGE
    return ERROR


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "WIFI SCAN")

    state = ctx.get("wifi_state", "idle")
    results = ctx.get("wifi_results")

    y = CONTENT_Y

    if state == "running":
        draw.text((20, y + 15), "Scanning...", font=FONT_LG, fill=WARN)
        draw_footer(draw, "please wait", BORDER)
        return img

    if not results or state == "idle":
        draw.text((10, y + 10), "Press \u25cf to", font=FONT_MD, fill=FG_DIM)
        draw.text((10, y + 23), "scan WiFi", font=FONT_MD, fill=FG_DIM)
        draw_footer(draw, "\u25cf scan  \u2190 back", BORDER)
        return img

    aps = results if isinstance(results, list) else results.get("networks", [])
    offset = ctx.get("wifi_offset", 0)
    avail_rows = (H - CONTENT_Y - FOOTER_H - 2) // 11
    visible = aps[offset:offset + avail_rows]

    for ap in visible:
        ssid = ap.get("ssid", "?")[:12]
        rssi = ap.get("rssi", ap.get("signal", -99))
        ch = ap.get("channel", "")
        draw.text((3, y), ssid, font=FONT_SM, fill=FG)
        draw.text((82, y), f"ch{ch}" if ch else "", font=FONT_SM, fill=FG_DIM)
        draw.text((107, y), f"{rssi}", font=FONT_SM, fill=_rssi_color(rssi))
        y += 11

    draw_footer(draw, f"{len(aps)} APs  \u2191\u2193 scroll  \u2190 back", BORDER)
    return img
