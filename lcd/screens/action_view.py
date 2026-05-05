"""
Generic action view — renders toggle/oneshot/info/custom screens.
"""

import time as _time
from lib.theme import *
from lib.actions import ACTIONS
from lib.util import resolve_field, format_field

_SPINNER = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827"]


def render(action_id, ctx):
    """Dispatch to the correct renderer."""
    action = ACTIONS.get(action_id)
    if not action:
        return _render_error(f"Unknown: {action_id}")

    if action_id == "iperf_server":
        return _render_iperf_server(action, ctx)
    if action_id == "iperf_client":
        return _render_iperf_client(action, ctx)
    if action_id == "network_traffic":
        return _render_network_traffic(ctx)
    if action_id == "hotspot":
        return _render_hotspot(action, ctx)
    if action_id == "profiler":
        return _render_profiler(action, ctx)

    t = action["type"]
    if t == "toggle":
        return _render_toggle(action_id, action, ctx)
    if t == "oneshot":
        return _render_oneshot(action_id, action, ctx)
    if t == "info":
        return _render_info(action_id, action, ctx)

    return _render_error(f"Type: {t}")


# ── COMMON ────────────────────────────────────────────────────

def _draw_status_line(draw, y, is_on, suffix=""):
    """Draw STATUS: ON/OFF badge at y."""
    draw.text((4, y), "STATUS:", font=FONT_SM, fill=FG_DIM)
    if is_on:
        draw.rounded_rectangle([50, y - 1, 78, y + 11], radius=3, fill=(0, 40, 20))
        draw.text((55, y), "ON", font=FONT_SM, fill=OK)
    else:
        draw.rounded_rectangle([50, y - 1, 82, y + 11], radius=3, fill=(30, 35, 50))
        draw.text((55, y), "OFF", font=FONT_SM, fill=FG_DIM)
    if suffix:
        draw.text((85, y), suffix, font=FONT_SM, fill=FG_DIM)


# ── TOGGLE ────────────────────────────────────────────────────

def _render_toggle(action_id, action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, action["title"])

    status = ctx.get("statuses", {}).get(action_id, "stopped")
    is_on = status == "running"
    status_data = ctx.get("status_data", {}).get(action_id, {})

    y = CONTENT_Y
    _draw_status_line(draw, y, is_on)
    y += 16

    for label, path, fmt in action.get("display_fields", []):
        val = resolve_field(status_data, path)
        formatted = format_field(val, fmt)
        if isinstance(val, bool):
            draw.text((4, y), "\u25cf", font=FONT_SM, fill=OK if val else FG_DIM)
            draw.text((14, y), label, font=FONT_SM, fill=FG_DIM)
        else:
            draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)
            draw.text((55, y), formatted, font=FONT_SM, fill=FG)
        y += 12

    draw_footer(draw, f"\u25cf {'Stop' if is_on else 'Start'}  \u2190 back", BORDER)
    return img


# ── ONESHOT ───────────────────────────────────────────────────

def _render_oneshot(action_id, action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, action["title"])

    cache = ctx.get("results_cache", {}).get(action_id)
    cache_ts = ctx.get("results_ts", {}).get(action_id)

    y = CONTENT_Y

    if cache_ts:
        ago = int(_time.time() - cache_ts)
        age = f"{ago}s ago" if ago < 60 else f"{ago//60}m ago" if ago < 3600 else f"{ago//3600}h ago"
        draw.text((4, y), f"Last run: {age}", font=FONT_SM, fill=FG_DIM)
        y += 14

    if cache is not None:
        result_fields = action.get("result_fields", [])
        result_source = action.get("result_source")

        if result_source == "rows" and isinstance(cache, dict):
            rows = cache.get("rows", [])
            row_map = {r.get("label", ""): r.get("value", "") for r in rows}
            for label, key, fmt in result_fields:
                draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)
                draw.text((55, y), str(row_map.get(key, "—"))[:14], font=FONT_SM, fill=FG)
                y += 12
        elif result_fields:
            for label, path, fmt in result_fields:
                val = resolve_field(cache, path) if isinstance(cache, dict) else None
                draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)
                draw.text((55, y), format_field(val, fmt)[:14], font=FONT_SM, fill=FG)
                y += 12
        else:
            if isinstance(cache, dict):
                ok = cache.get("ok")
                if ok is not None:
                    draw.text((4, y), "OK" if ok else "FAILED", font=FONT_LG, fill=OK if ok else ERROR)
                    y += 16
                err = cache.get("error")
                if err:
                    draw.text((4, y), str(err)[:20], font=FONT_SM, fill=ERROR)
    else:
        draw.text((4, y + 12), "(No previous run)", font=FONT_SM, fill=FG_DIM)

    draw_footer(draw, "\u25cf Run  \u2190 back", BORDER)
    return img


# ── INFO ──────────────────────────────────────────────────────

def _render_info(action_id, action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, action["title"])

    status_data = ctx.get("status_data", {}).get(action_id, {})

    y = CONTENT_Y
    for label, path, fmt in action.get("display_fields", []):
        val = resolve_field(status_data, path)
        formatted = format_field(val, fmt)
        if isinstance(val, bool):
            draw.text((4, y), "\u25cf", font=FONT_SM, fill=OK if val else FG_DIM)
            draw.text((14, y), label, font=FONT_SM, fill=FG_DIM)
            draw.text((70, y), "online" if val else "offline", font=FONT_SM, fill=OK if val else FG_DIM)
        else:
            draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)
            draw.text((55, y), formatted[:14], font=FONT_SM, fill=FG)
        y += 14

    draw_footer(draw, "K2 refresh  \u2190 back", BORDER)
    return img


# ── PROFILER (custom) ─────────────────────────────────────────

def _render_profiler(action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "Profiler")

    status = ctx.get("statuses", {}).get("profiler", "stopped")
    is_on = status == "running"

    y = CONTENT_Y
    _draw_status_line(draw, y, is_on)
    y += 18

    if is_on:
        draw.text((4, y), "Connect a client to", font=FONT_SM, fill=FG_DIM)
        y += 11
        draw.text((4, y), "the active SSID for", font=FONT_SM, fill=FG_DIM)
        y += 11
        draw.text((4, y), "fingerprinting", font=FONT_SM, fill=FG_DIM)
        y += 16
        draw.text((4, y), "See GUI for details", font=FONT_SM, fill=ACCENT)
    else:
        draw.text((4, y), "Client Profiler", font=FONT_SM, fill=FG_DIM)
        y += 11
        draw.text((4, y), "uses hostapd virtual", font=FONT_SM, fill=FG_DIM)
        y += 11
        draw.text((4, y), "AP for fingerprinting", font=FONT_SM, fill=FG_DIM)

    draw_footer(draw, f"\u25cf {'Stop' if is_on else 'Start'}  \u2190 back", BORDER)
    return img


# ── HOTSPOT (custom with QR) ─────────────────────────────────

def _gen_wifi_qr(ssid, password=None, size=48):
    """Generate WiFi QR code as PIL Image."""
    try:
        import qrcode
        from PIL import Image as PILImage
        if password:
            wifi_str = f"WIFI:T:WPA2;S:{ssid};P:{password};;"
        else:
            wifi_str = f"WIFI:T:nopass;S:{ssid};;"
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=2, border=1)
        qr.add_data(wifi_str)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="white", back_color="black").convert("RGB")
        return qr_img.resize((size, size), PILImage.NEAREST)
    except Exception:
        return None


def _render_hotspot(action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "Hotspot AP")

    status = ctx.get("statuses", {}).get("hotspot", "stopped")
    is_on = status == "running"
    data = ctx.get("status_data", {}).get("hotspot", {})

    y = CONTENT_Y
    _draw_status_line(draw, y, is_on)
    y += 16

    ssid = data.get("ssid")
    password = data.get("password")
    clients = data.get("clients", [])

    if is_on and ssid:
        # QR on the left, info on the right
        qr_img = _gen_wifi_qr(ssid, password, size=48)
        if qr_img:
            img.paste(qr_img, (4, y))

        # Info next to QR
        rx = 58
        draw.text((rx, y), "SSID:", font=FONT_SM, fill=FG_DIM)
        draw.text((rx, y + 11), ssid[:11], font=FONT_SM, fill=FG)
        if password:
            draw.text((rx, y + 24), "Pass:", font=FONT_SM, fill=FG_DIM)
            draw.text((rx, y + 35), password[:10], font=FONT_SM, fill=FG)
        y += 52
        draw.text((4, y), f"Clients: {len(clients)}", font=FONT_SM, fill=ACCENT)
    else:
        draw.text((4, y), "NekoPi-Field SSID", font=FONT_SM, fill=FG_DIM)
        y += 12
        err = data.get("error")
        if err:
            draw.text((4, y), str(err)[:22], font=FONT_SM, fill=WARN)

    draw_footer(draw, f"\u25cf {'Stop' if is_on else 'Start'}  \u2190 back", BORDER)
    return img


# ── IPERF SERVER (custom) ────────────────────────────────────

def _render_iperf_server(action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "iPerf Server")

    status = ctx.get("statuses", {}).get("iperf_server", "stopped")
    is_on = status == "running"

    y = CONTENT_Y
    _draw_status_line(draw, y, is_on, ":5201")
    y += 15

    # IPs
    net = ctx.get("network") or {}
    ifaces = net.get("interfaces", [])
    draw.text((4, y), "Listen on:" if is_on else "Available:", font=FONT_SM, fill=FG_DIM)
    y += 11
    for ifc in ifaces:
        ip = ifc.get("ip") or "—"
        draw.text((8, y), ifc.get("name", "?"), font=FONT_SM, fill=ACCENT)
        draw.text((48, y), ip, font=FONT_SM, fill=FG if ip != "—" else FG_DIM)
        y += 10

    # eth0 traffic (always visible)
    traffic = ctx.get("traffic") or {}
    for ti in traffic.get("interfaces", []):
        if ti.get("name") == "eth0":
            y += 2
            tx = ti.get("tx_mbps", 0)
            rx = ti.get("rx_mbps", 0)
            draw.text((4, y), "eth0:", font=FONT_SM, fill=FG_DIM)
            draw.text((35, y), f"\u2191{_fmt_rate(tx)} \u2193{_fmt_rate(rx)}", font=FONT_SM, fill=ACCENT)
            break

    draw_footer(draw, f"\u25cf {'Stop' if is_on else 'Start'}  \u2190 back", BORDER)
    return img


# ── IPERF CLIENT (custom) ────────────────────────────────────

def _render_iperf_client(action, ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "iPerf Client")

    from lib.util import iperf_client_params
    params = iperf_client_params()

    y = CONTENT_Y
    draw.text((4, y), "Target:", font=FONT_SM, fill=FG_DIM)
    draw.text((48, y), params.get("server", "?"), font=FONT_SM, fill=ACCENT)
    y += 12
    draw.text((4, y), "Duration:", font=FONT_SM, fill=FG_DIM)
    draw.text((48, y), f"{params.get('duration', 10)}s", font=FONT_SM, fill=FG_DIM)
    y += 15

    cache = ctx.get("results_cache", {}).get("iperf_client")
    cache_ts = ctx.get("results_ts", {}).get("iperf_client")

    if cache and isinstance(cache, dict) and cache.get("ok"):
        draw.text((4, y), "Last result:", font=FONT_SM, fill=FG_DIM)
        y += 12
        for label, path, fmt in action.get("result_fields", []):
            val = resolve_field(cache, path)
            draw.text((8, y), label, font=FONT_SM, fill=FG_DIM)
            draw.text((55, y), format_field(val, fmt), font=FONT_SM, fill=OK)
            y += 11
        if cache_ts:
            ago = int(_time.time() - cache_ts)
            age = f"{ago}s" if ago < 60 else f"{ago//60}m"
            draw.text((100, CONTENT_Y), age, font=FONT_SM, fill=BORDER)
    elif cache and isinstance(cache, dict):
        draw.text((4, y), "Last: FAILED", font=FONT_SM, fill=ERROR)
    else:
        draw.text((4, y + 5), "(No previous run)", font=FONT_SM, fill=FG_DIM)

    draw_footer(draw, "\u25cf Run  \u2190 back", BORDER)
    return img


# ── NETWORK TRAFFIC (custom) ─────────────────────────────────

def _render_network_traffic(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "Net Traffic")

    traffic = ctx.get("traffic") or {}
    ifaces = traffic.get("interfaces", [])

    y = CONTENT_Y
    draw.text((4, y), "IFACE", font=FONT_SM, fill=BORDER)
    draw.text((52, y), "\u2191 TX", font=FONT_SM, fill=BORDER)
    draw.text((92, y), "\u2193 RX", font=FONT_SM, fill=BORDER)
    y += 12

    for ifc in ifaces[:6]:
        name = ifc.get("name", "?")
        tx = ifc.get("tx_mbps", 0)
        rx = ifc.get("rx_mbps", 0)
        active = tx > 0.01 or rx > 0.01
        draw.text((4, y), name, font=FONT_SM, fill=ACCENT if active else FG_DIM)
        draw.text((52, y), _fmt_rate(tx), font=FONT_SM, fill=OK if tx > 0.1 else FG_DIM)
        draw.text((92, y), _fmt_rate(rx), font=FONT_SM, fill=OK if rx > 0.1 else FG_DIM)
        y += 12

    # Errors
    y += 2
    for ifc in ifaces:
        rx_err = ifc.get("rx_errors", 0)
        tx_err = ifc.get("tx_errors", 0)
        if rx_err > 0 or tx_err > 0:
            draw.text((4, y), f"{ifc['name']}: rx={rx_err} tx={tx_err}", font=FONT_SM, fill=WARN)
            y += 10

    draw_footer(draw, "K2 refresh  \u2190 back", BORDER)
    return img


# ── CONFIRMATIONS ─────────────────────────────────────────────

def render_confirm(action_id, ctx, level=1, countdown=5):
    action = ACTIONS.get(action_id, {})
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, action.get("title", "?"), color=ERROR if action.get("warn_destructive") else ACCENT)

    is_destructive = action.get("warn_destructive", False)
    status = ctx.get("statuses", {}).get(action_id, "stopped")
    is_on = status == "running"

    y = CONTENT_Y + 4

    if is_destructive and level == 1:
        draw.rectangle([0, y - 2, W, y + 14], fill=(40, 8, 12))
        draw.text((4, y), "\u26a0 DESTRUCTIVE", font=FONT_TTL, fill=ERROR)
        y += 20
        draw.text((4, y), "  RUN?", font=FONT_TTL, fill=WARN)
        y += 18
        draw.text((4, y), "May disrupt network", font=FONT_SM, fill=FG_DIM)
        y += 11
        draw.text((4, y), "services in production", font=FONT_SM, fill=FG_DIM)
        y += 14
        draw.text((4, y), f"\u25cf Continue  {countdown}s", font=FONT_SM, fill=WARN)
    elif is_destructive and level == 2:
        draw.rectangle([0, y - 2, W, y + 14], fill=(40, 8, 12))
        draw.text((4, y), "\u26a0 FINAL CONFIRM", font=FONT_TTL, fill=ERROR)
        y += 20
        draw.text((4, y), "  PROCEED?", font=FONT_TTL, fill=ERROR)
        y += 18
        draw.text((4, y), "Cannot undo", font=FONT_SM, fill=FG_DIM)
        y += 14
        draw.text((4, y), f"\u25cf Execute  {countdown}s", font=FONT_SM, fill=ERROR)
    else:
        verb = "STOP" if is_on else "START"
        color = WARN if is_on else OK
        draw.text((4, y + 8), f"  {verb}?", font=FONT_LG, fill=color)
        y += 32
        draw.text((4, y), action.get("description", ""), font=FONT_SM, fill=FG_DIM)
        y += 14
        draw.text((4, y), f"\u25cf Confirm  {countdown}s", font=FONT_SM, fill=WARN)

    draw_footer(draw, "\u2190 Cancel", BORDER)
    return img


# ── TRANSIENT STATES ──────────────────────────────────────────

def render_transient(state, action_id, ctx=None, spinner_frame=0, message=""):
    action = ACTIONS.get(action_id, {})
    img, draw = new_image()
    if ctx:
        draw_header(draw, ctx)
    draw_title(draw, action.get("title", "?"))

    y = CONTENT_Y

    if state == "running":
        spin = _SPINNER[spinner_frame % len(_SPINNER)]
        draw.text((50, y + 12), spin, font=FONT_XL, fill=ACCENT)
        draw.text((4, y + 38), message or "Working...", font=FONT_MD, fill=FG_DIM)
    elif state == "success":
        draw.text((50, y + 8), "\u25cf", font=FONT_XL, fill=OK)
        draw.text((4, y + 30), "OK", font=FONT_LG, fill=OK)
        if message:
            draw.text((4, y + 48), message, font=FONT_SM, fill=FG_DIM)
    elif state == "error":
        draw.text((45, y + 5), "\u26a0", font=FONT_XL, fill=ERROR)
        draw.text((4, y + 28), "Error", font=FONT_LG, fill=ERROR)
        if message:
            draw.text((4, y + 46), message[:22], font=FONT_SM, fill=FG_DIM)
            if len(message) > 22:
                draw.text((4, y + 57), message[22:44], font=FONT_SM, fill=FG_DIM)

    return img


# ── HELPERS ───────────────────────────────────────────────────

def _fmt_rate(mbps):
    if mbps is None: return "—"
    if mbps >= 1000: return f"{mbps/1000:.1f}G"
    if mbps >= 1: return f"{mbps:.1f}M"
    if mbps >= 0.01: return f"{mbps*1000:.0f}K"
    return "0"


def _render_error(msg):
    img, draw = new_image()
    draw_title(draw, "ERROR", color=ERROR)
    draw.text((4, CONTENT_Y + 10), msg, font=FONT_SM, fill=ERROR)
    return img
