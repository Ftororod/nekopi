"""
Input handler — Waveshare 1.44" HAT joystick + 3 keys
RPi5 via gpiochip4, active-low with internal pull-ups.
Uses polling thread (~50ms) — lgpio alerts unreliable on RPi5.
"""

import time
import threading
import lgpio

# Pin → event name mapping (active-low)
_PIN_MAP = {
    6:  "UP",
    19: "DOWN",
    5:  "LEFT",
    26: "RIGHT",
    13: "PRESS",
    21: "KEY1",
    20: "KEY2",
    16: "KEY3",
}

_POLL_S = 0.05
_DEBOUNCE_S = 0.15


class Input:
    """GPIO input with polling-based detection and debounce."""

    def __init__(self, callback, chip=4, gpio_handle=None):
        self._cb = callback
        if gpio_handle is not None:
            self._h = gpio_handle
            self._owns_gpio = False
        else:
            self._h = lgpio.gpiochip_open(chip)
            self._owns_gpio = True
        self._last = {pin: 0.0 for pin in _PIN_MAP}
        self._prev = {pin: 1 for pin in _PIN_MAP}

        for pin in _PIN_MAP:
            lgpio.gpio_claim_input(self._h, pin, lgpio.SET_PULL_UP)

        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll(self):
        while self._running:
            now = time.monotonic()
            for pin, name in _PIN_MAP.items():
                val = lgpio.gpio_read(self._h, pin)
                # Detect falling edge (1→0)
                if val == 0 and self._prev[pin] == 1:
                    if now - self._last[pin] >= _DEBOUNCE_S:
                        self._last[pin] = now
                        if self._cb:
                            self._cb(name)
                self._prev[pin] = val
            time.sleep(_POLL_S)

    def close(self):
        self._running = False
        try:
            self._thread.join(timeout=1)
        except Exception:
            pass
        if self._owns_gpio:
            try:
                lgpio.gpiochip_close(self._h)
            except Exception:
                pass

    def __del__(self):
        self.close()
