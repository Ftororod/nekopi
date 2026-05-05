"""Quick Check screen — runs /api/qc/run, shows results."""

from lib.theme import *

_LABELS = {
    "ping":    "Ping",
    "dns":     "DNS",
    "gateway": "GW",
    "captive": "Portal",
    "speed":   "Speed",
}


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "Quick Check")

    qc = ctx.get("qc_result")
    state = ctx.get("qc_state", "idle")

    y = CONTENT_Y

    if state == "running":
        draw.text((20, y + 15), "Running...", font=FONT_LG, fill=WARN)
        draw_footer(draw, "please wait", BORDER)
        return img

    if not qc or state == "idle":
        draw.text((10, y + 10), "Press \u25cf to", font=FONT_MD, fill=FG_DIM)
        draw.text((10, y + 23), "run checks", font=FONT_MD, fill=FG_DIM)
        draw_footer(draw, "\u25cf run  \u2190 back", BORDER)
        return img

    checks = qc.get("checks", qc.get("results", {}))
    if isinstance(checks, dict):
        for key, label in _LABELS.items():
            val = checks.get(key, {})
            if isinstance(val, dict):
                ok = val.get("ok", val.get("pass", False))
                detail = val.get("ms", val.get("detail", ""))
            else:
                ok = bool(val)
                detail = ""
            color = OK if ok else ERROR
            status = "OK" if ok else "FAIL"
            draw.text((3, y), label, font=FONT_SM, fill=FG)
            draw.text((50, y), status, font=FONT_SM, fill=color)
            if detail:
                draw.text((80, y), str(detail)[:8], font=FONT_SM, fill=FG_DIM)
            y += 12

    score = qc.get("score")
    if score is not None:
        y += 2
        draw.text((3, y), f"Score: {score}/100", font=FONT_LG,
                  fill=OK if score >= 80 else WARN if score >= 50 else ERROR)

    draw_footer(draw, "\u25cf rerun  \u2190 back", BORDER)
    return img
