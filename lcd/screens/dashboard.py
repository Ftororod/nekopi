"""Dashboard — Network interfaces with WiFi detail."""

from lib.theme import *
from lib.util import format_cidr, freq_to_channel

RELEVANT_IFACES = ['eth0', 'eth1', 'wlan0', 'wlan2', 'mon0']

CHIPSET_LABELS = {
    'wlan0': 'AX210',
    'wlan2': 'MT7921AU',
}


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "Dashboard")

    net = ctx.get("network") or {}
    met = ctx.get("metrics") or {}
    traffic = ctx.get("traffic") or {}
    wifi_info = ctx.get("wifi_info") or {}
    monitor_data = ctx.get("status_data", {}).get("mon0", {})

    ifaces = {i.get("name"): i for i in net.get("interfaces", [])}
    traffic_map = {i.get("name"): i for i in traffic.get("interfaces", [])}

    y = CONTENT_Y

    for name in RELEVANT_IFACES:
        if name == 'mon0':
            # Only show if mon0 is active
            mon_status = ctx.get("statuses", {}).get("mon0", "stopped")
            if mon_status != "running":
                continue
            y = _render_mon0(draw, y, monitor_data)
        elif name.startswith('wl'):
            iface = ifaces.get(name, {})
            y = _render_wifi(draw, y, name, iface, wifi_info)
        else:
            iface = ifaces.get(name)
            if not iface:
                continue
            tr = traffic_map.get(name, {})
            y = _render_eth(draw, y, name, iface, tr)

        if y > 110:
            break

    draw_footer(draw, "K2 refresh  \u2190 back", BORDER)
    return img


def _render_eth(draw, y, name, iface, traffic):
    """Ethernet: name STATE speed + IP/prefix."""
    status = iface.get("status", "down")
    ip = iface.get("ip")
    color = OK if status == "up" and ip else (ORANGE if status == "up" else FG_DIM)

    # Line 1: dot + name + IP right-aligned
    draw.text((3, y), "\u25cf", font=FONT_SM, fill=color)
    draw.text((13, y), name, font=FONT_SM, fill=FG)
    display = ip or "\u2014"
    tw = draw.textlength(display, font=FONT_SM)
    draw.text((W - tw - 3, y), display, font=FONT_SM, fill=ACCENT if ip else FG_DIM)
    y += 11
    return y


def _render_wifi(draw, y, name, iface, wifi_info):
    """WiFi: name STATE chipset + SSID/ch/RSSI if connected."""
    status = iface.get("status", "down")
    ip = iface.get("ip")
    color = OK if status == "up" and ip else (ORANGE if status == "up" else FG_DIM)
    chipset = CHIPSET_LABELS.get(name, '')

    # Line 1: dot + name + chipset right
    draw.text((3, y), "\u25cf", font=FONT_SM, fill=color)
    draw.text((13, y), name, font=FONT_SM, fill=FG)

    if chipset:
        tw = draw.textlength(chipset, font=FONT_SM)
        draw.text((W - tw - 3, y), chipset, font=FONT_SM, fill=FG_DIM)
    y += 11

    # Line 2: SSID/ch/signal if connected (from wifi_info API)
    # wifi_info is the response from /api/wifi/info (single iface — wlan0)
    connected = False
    if isinstance(wifi_info, dict) and wifi_info.get("iface") == name and wifi_info.get("connected"):
        ssid = wifi_info.get("ssid", "")[:12]
        freq = wifi_info.get("freq_mhz")
        ch = freq_to_channel(freq)
        signal = wifi_info.get("signal_dbm")

        parts = [ssid]
        if ch:
            parts.append(f"ch{ch}")
        if signal is not None:
            parts.append(f"{signal}dBm")

        line = " \u00b7 ".join(parts)
        draw.text((13, y), line, font=FONT_SM, fill=FG_DIM)
        y += 11
        connected = True

    if not connected and status == "up" and ip:
        draw.text((13, y), ip, font=FONT_SM, fill=FG_DIM)
        y += 11

    return y


def _render_mon0(draw, y, monitor_data):
    """mon0 interface — channel/band."""
    draw.text((3, y), "\u25cf", font=FONT_SM, fill=ACCENT)
    draw.text((13, y), "mon0", font=FONT_SM, fill=FG)

    channel = monitor_data.get("mon0_channel") or monitor_data.get("channel")
    bands = monitor_data.get("mon0_bands") or monitor_data.get("band", "")

    info = "monitor"
    if channel:
        info = f"ch{channel}"
        if bands:
            info += f" {bands}"

    tw = draw.textlength(info, font=FONT_SM)
    draw.text((W - tw - 3, y), info, font=FONT_SM, fill=FG_DIM)
    y += 11
    return y
