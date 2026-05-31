"""Splash screen — supports boot/ready/rebooting/shutdown/api_wait variants."""

import os
import time
from PIL import Image
from lib.theme import *

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "nekopi_logo.png")
_CODENAME = "ToManchas"

_MESSAGES = {
    'boot':       ('NekoPi v1.3',      ACCENT),
    'ready':      ('NekoPi v1.3',      OK),
    'rebooting':  ('Rebooting...',     ERROR),
    'shutdown':   ('Shutting down...', ERROR),
}


def _read_hostname():
    try:
        with open('/etc/hostname') as f:
            return f.read().strip()
    except Exception:
        return 'nekopi'


def render(ctx=None, variant='boot'):
    """Render splash screen.

    variant: 'boot' | 'ready' | 'rebooting' | 'shutdown' | 'api_wait'
    ctx: optional context dict (used for version in boot/ready)
    """
    img, draw = new_image()

    # Load and draw official logo (top portion)
    try:
        logo = Image.open(_LOGO_PATH).convert("RGB")
        logo = logo.resize((96, 96), Image.LANCZOS)
        img.paste(logo, ((W - 96) // 2, 2))
    except Exception:
        draw.text((28, 35), "NekoPi", font=FONT_XL, fill=WHITE)

    if variant == 'api_wait':
        # Show useful info while backend starts
        y = 100
        draw.text((4, y), _read_hostname(), font=FONT_SM, fill=FG)
        y += 12
        draw.text((4, y), '192.168.99.1', font=FONT_SM, fill=ACCENT)
        y += 14
        # Animated dots
        dots_count = int(time.time() * 2) % 4
        msg = 'Booting' + '.' * dots_count
        msg = msg.ljust(11)
        tw = draw.textlength(msg, font=FONT_SM)
        draw.text(((W - tw) // 2, y), msg, font=FONT_SM, fill=WARN)
    else:
        # Message below logo
        msg, color = _MESSAGES.get(variant, ('NekoPi', ACCENT))
        tw = draw.textlength(msg, font=FONT_TTL)
        draw.text(((W - tw) // 2, 100), msg, font=FONT_TTL, fill=color)

        # Codename / version at bottom
        if variant in ('boot', 'ready'):
            ver = ""
            if ctx:
                ver = (ctx.get("about") or {}).get("nekopi", {}).get("version", "")
            sub = f"v{ver}" if ver else _CODENAME
            sw = draw.textlength(sub, font=FONT_SM)
            draw.text(((W - sw) // 2, 117), sub, font=FONT_SM, fill=GRAY)

    return img
