"""Home rotativo con 3 páginas — Network, Latency, System."""

import time as _time
from lib.theme import *

PAGES = ['network', 'latency', 'system']
ROTATE_INTERVAL = 6.0

# Latency test definitions: (key, label_for_display)
LATENCY_KEYS = [
    ('gateway',    'GW:'),
    ('dns_local',  'DNS:'),
    ('google_dns', 'Google:'),
    ('cloudflare', 'Cloudfl:'),
]


def render(ctx):
    page = ctx.get('home_page', 'network')
    page_idx = PAGES.index(page) if page in PAGES else 0

    img, draw = new_image()
    draw_header(draw, ctx)

    # Short title + pagination dots
    titles = {'network': 'NETWORK', 'latency': 'LATENCY', 'system': 'SYSTEM'}
    title = titles.get(page, page.upper())
    draw.text((4, HEADER_H + 1), title, font=FONT_TTL, fill=ACCENT)

    # Dots right-aligned
    dot_x = W - 4 - (len(PAGES) * 8)
    for i in range(len(PAGES)):
        color = ACCENT if i == page_idx else FG_DIM
        draw.text((dot_x + i * 8, HEADER_H + 2), '\u2022', font=FONT_SM, fill=color)

    draw.line([(0, HEADER_H + TITLE_H), (W, HEADER_H + TITLE_H)], fill=BORDER)

    if page == 'network':
        _render_network(draw, ctx)
    elif page == 'latency':
        _render_latency(draw, ctx)
    elif page == 'system':
        _render_system(draw, ctx)

    # Footer hint
    auto = ctx.get('home_auto_rotate', True)
    hint = "\u25cf auto 6s" if auto else "\u25c0\u25b6 manual"
    draw_footer(draw, hint, GRAY)

    return img


def _render_network(draw, ctx):
    hd = ctx.get('home_data', {})
    net = ctx.get("network") or {}
    ifaces = net.get("interfaces", [])

    cidrs = hd.get('cidrs', {})
    eth0_cidr = cidrs.get('eth0')
    eth1_cidr = cidrs.get('eth1')
    gateway = net.get("gateway")
    public_ip = hd.get('public_ip')

    # Hotspot info
    hotspot = hd.get('hotspot', {})
    hotspot_active = hotspot.get('enabled', False)
    hotspot_ssid = hotspot.get('ssid')
    hotspot_clients = len(hotspot.get('clients', [])) if hotspot.get('clients') else 0

    y = CONTENT_Y + 2
    rows = [
        ('eth0:', eth0_cidr),
        ('eth1:', eth1_cidr),
        ('GW:',   gateway),
        ('WAN:',  public_ip),
    ]

    # Add AP line if hotspot active
    if hotspot_active and hotspot_ssid:
        rows.append(('AP:', f"{hotspot_ssid} ({hotspot_clients})"))

    for label, value in rows:
        draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)
        draw.text((32, y), str(value) if value else '\u2014', font=FONT_SM,
                  fill=FG if value else FG_DIM)
        y += 12


def _render_latency(draw, ctx):
    hd = ctx.get('home_data', {})
    lat = hd.get('latency', {})
    hist = hd.get('latency_history', {})
    timestamps = hd.get('latency_ts', {})

    y = CONTENT_Y + 2
    now = _time.time()

    for key, label in LATENCY_KEYS:
        ms = lat.get(key)
        draw.text((4, y), label, font=FONT_SM, fill=FG_DIM)

        if ms is None:
            draw.text((42, y), '\u2014', font=FONT_SM, fill=FG_DIM)
        else:
            # Value
            if ms < 10:
                val_str = f"{ms:.1f}"
            else:
                val_str = f"{int(ms)}"
            draw.text((42, y), val_str, font=FONT_SM, fill=FG)
            draw.text((66, y), 'ms', font=FONT_SM, fill=FG_DIM)

            # Color dot
            color = OK if ms < 50 else (WARN if ms < 200 else ERROR)
            draw.text((82, y), '\u2022', font=FONT_SM, fill=color)

        # Sparkline
        values = list(hist.get(key, []))
        if values:
            _draw_sparkline(draw, 92, y + 1, 24, 8, values)

        # Age indicator (right edge)
        ts = timestamps.get(key)
        if ts:
            age = int(now - ts)
            if age < 99:
                draw.text((118, y), f"{age}", font=FONT_SM, fill=FG_DIM)

        y += 13


def _render_system(draw, ctx):
    met = ctx.get("metrics") or {}
    hd = ctx.get('home_data', {})

    client_ip = hd.get('dhcp_client_ip')
    cpu = met.get('cpu_pct')
    ram = met.get('ram', {})
    ram_used = ram.get('used_mb')
    ram_total = ram.get('total_mb')
    temp = met.get('cpu_temp')
    uptime_s = met.get('uptime_s')

    y = CONTENT_Y + 2

    # Client IP first (most useful at a glance in the field)
    draw.text((4, y), 'DHCP:', font=FONT_SM, fill=FG_DIM)
    if client_ip:
        draw.text((32, y), client_ip, font=FONT_SM, fill=OK)
    else:
        draw.text((32, y), 'no client', font=FONT_SM, fill=FG_DIM)
    y += 13

    # CPU
    draw.text((4, y), 'CPU:', font=FONT_SM, fill=FG_DIM)
    if cpu is not None:
        draw.text((30, y), f"{int(cpu):>3}%", font=FONT_SM, fill=FG)
        cpu_color = OK if cpu < 50 else (WARN if cpu < 80 else ERROR)
        _draw_bar(draw, 56, y + 2, 60, cpu, cpu_color)
    else:
        draw.text((30, y), '\u2014', font=FONT_SM, fill=FG_DIM)
    y += 12

    # RAM
    draw.text((4, y), 'RAM:', font=FONT_SM, fill=FG_DIM)
    if ram_used is not None and ram_total:
        ram_pct = (ram_used / ram_total) * 100
        draw.text((30, y), f"{int(ram_pct):>3}%", font=FONT_SM, fill=FG)
        ram_color = OK if ram_pct < 70 else (WARN if ram_pct < 90 else ERROR)
        _draw_bar(draw, 56, y + 2, 60, ram_pct, ram_color)
    else:
        draw.text((30, y), '\u2014', font=FONT_SM, fill=FG_DIM)
    y += 12

    # Temp
    draw.text((4, y), 'Temp:', font=FONT_SM, fill=FG_DIM)
    if temp is not None:
        draw.text((30, y), f"{int(temp)}\u00b0C", font=FONT_SM, fill=FG)
        temp_pct = min(100, (temp / 85) * 100)
        temp_color = OK if temp < 60 else (WARN if temp < 75 else ERROR)
        _draw_bar(draw, 56, y + 2, 60, temp_pct, temp_color)
    else:
        draw.text((30, y), '\u2014', font=FONT_SM, fill=FG_DIM)
    y += 12

    # Uptime
    draw.text((4, y), 'Up:', font=FONT_SM, fill=FG_DIM)
    draw.text((30, y), _fmt_uptime(uptime_s), font=FONT_SM,
              fill=FG if uptime_s else FG_DIM)


def _draw_bar(draw, x, y, width, pct, color):
    """Horizontal progress bar."""
    draw.rectangle([x, y, x + width, y + 6], outline=BORDER, fill=None)
    if pct is not None and pct > 0:
        fill_w = max(1, int(width * (min(100, pct) / 100)))
        draw.rectangle([x + 1, y + 1, x + fill_w, y + 5], fill=color)


def _draw_sparkline(draw, x, y, width, height, values):
    """Mini bar chart from deque of values."""
    if not values:
        return
    max_v = max(values) or 1
    n = len(values)
    bar_w = max(2, width // n)
    for i, v in enumerate(values):
        bar_h = max(1, int((v / max_v) * height))
        bx = x + i * bar_w
        draw.rectangle([bx, y + height - bar_h, bx + bar_w - 1, y + height],
                       fill=ACCENT)


def _fmt_uptime(seconds):
    if seconds is None:
        return '\u2014'
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h >= 24:
        d = h // 24
        h = h % 24
        return f"{d}d {h}h"
    return f"{h}h {m}m"
