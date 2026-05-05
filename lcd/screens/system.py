"""System screen — uptime, RAM, disk, GUI URL."""

from lib.theme import *


def _fmt_uptime(secs):
    if not secs: return "—"
    d = int(secs) // 86400
    h = (int(secs) % 86400) // 3600
    m = (int(secs) % 3600) // 60
    if d > 0: return f"{d}d {h}h {m}m"
    if h > 0: return f"{h}h {m}m"
    return f"{m}m"


def render(ctx):
    img, draw = new_image()
    draw_header(draw, ctx)
    draw_title(draw, "SYSTEM")

    met = ctx.get("metrics") or {}
    net = ctx.get("network") or {}

    ram = met.get("ram", {})
    disk = met.get("disk", {})
    uptime = met.get("uptime_s", 0)
    temp = met.get("cpu_temp", 0)
    cpu = met.get("cpu_pct", 0)

    y = CONTENT_Y

    draw.text((3, y), "Uptime", font=FONT_SM, fill=FG_DIM)
    draw.text((50, y), _fmt_uptime(uptime), font=FONT_SM, fill=FG)
    y += 13

    draw.text((3, y), "CPU", font=FONT_SM, fill=FG_DIM)
    draw.text((50, y), f"{cpu:.0f}%  {temp:.0f}\u00b0C", font=FONT_SM,
              fill=ERROR if temp > 70 else WARN)
    y += 13

    ram_used = ram.get("used_mb", 0)
    ram_total = ram.get("total_mb", 0)
    draw.text((3, y), "RAM", font=FONT_SM, fill=FG_DIM)
    draw.text((50, y), f"{ram_used}M/{ram_total}M {ram.get('pct',0):.0f}%", font=FONT_SM, fill=PURPLE)
    y += 13

    draw.text((3, y), "Disk", font=FONT_SM, fill=FG_DIM)
    draw.text((50, y), f"{disk.get('used_gb',0):.0f}G/{disk.get('total_gb',0):.0f}G {disk.get('pct',0):.0f}%",
              font=FONT_SM, fill=INFO)
    y += 15

    mgmt_ip = "192.168.99.1"
    for ifc in net.get("interfaces", []):
        if ifc.get("name") == "eth1" and ifc.get("ip"):
            mgmt_ip = ifc["ip"]
            break
    draw.text((3, y), "Web:", font=FONT_SM, fill=FG_DIM)
    draw.text((24, y), f"{mgmt_ip}:8080", font=FONT_SM, fill=OK)

    draw_footer(draw, "K2 refresh  \u2190 back", BORDER)
    return img
