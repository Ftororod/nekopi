"""Utility helpers for LCD daemon."""

import subprocess
from lib.api import get


def format_cidr(ip, mask=None):
    """Format IP with prefix length if mask available, else just IP."""
    if not ip:
        return "—"
    if mask:
        try:
            import ipaddress
            net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            return f"{ip}/{net.prefixlen}"
        except Exception:
            pass
    return ip


def freq_to_channel(freq_mhz):
    """Convert WiFi frequency (MHz) to channel number."""
    if not freq_mhz:
        return None
    freq = int(freq_mhz)
    if 2412 <= freq <= 2484:
        return (freq - 2407) // 5 if freq != 2484 else 14
    elif 5180 <= freq <= 5825:
        return (freq - 5000) // 5
    elif 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return None


def iperf_client_params():
    """Resolve iPerf3 client target — gateway preferred."""
    info = get("/api/network/info") or {}
    gw = info.get("gateway")
    if gw:
        return {"server": gw, "duration": 10}
    return {"server": "192.168.1.1", "duration": 10}


def resolve_field(data, path):
    """Resolve a dot-notation path in a dict. e.g. 'stats.roams' → data['stats']['roams']."""
    if not data or not path:
        return None
    parts = path.split(".")
    val = data
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def format_field(value, fmt):
    """Format a field value using the format string from display_fields."""
    if value is None:
        return "—"
    if fmt == "len":
        if isinstance(value, (list, tuple)):
            return str(len(value))
        return str(value)
    try:
        return fmt.format(value)
    except (ValueError, TypeError):
        return str(value)
