"""
ST7735S LCD Driver — Waveshare 1.44" HAT (128x128, RGB565)
RPi5 via gpiochip4 + SPI0.0
"""

import time
import spidev
import lgpio
from PIL import Image

# Pin definitions (BCM)
DC_PIN  = 25
RST_PIN = 27
BL_PIN  = 24

# Display geometry
WIDTH   = 128
HEIGHT  = 128
COL_OFS = 1
ROW_OFS = 2

# ST7735S commands
_SWRESET = 0x01
_SLPOUT  = 0x11
_DISPON  = 0x29
_DISPOFF = 0x28
_CASET   = 0x2A
_RASET   = 0x2B
_RAMWR   = 0x2C
_COLMOD  = 0x3A
_MADCTL  = 0x36
_INVON   = 0x21


class LCD:
    """ST7735S display driver using lgpio + spidev."""

    def __init__(self, chip=4, spi_bus=0, spi_dev=0, speed_hz=40_000_000, gpio_handle=None):
        if gpio_handle is not None:
            self._h = gpio_handle
            self._owns_gpio = False
        else:
            self._h = lgpio.gpiochip_open(chip)
            self._owns_gpio = True
        for pin in (DC_PIN, RST_PIN, BL_PIN):
            lgpio.gpio_claim_output(self._h, pin, 0)

        self._spi = spidev.SpiDev()
        self._spi.open(spi_bus, spi_dev)
        self._spi.max_speed_hz = speed_hz
        self._spi.mode = 0

        self._init_display()

    def _cmd(self, c):
        lgpio.gpio_write(self._h, DC_PIN, 0)
        self._spi.writebytes([c])

    def _data(self, d):
        lgpio.gpio_write(self._h, DC_PIN, 1)
        if isinstance(d, (list, bytes, bytearray)):
            self._spi.writebytes2(d)
        else:
            self._spi.writebytes([d])

    def _init_display(self):
        # Hardware reset
        lgpio.gpio_write(self._h, RST_PIN, 1)
        time.sleep(0.05)
        lgpio.gpio_write(self._h, RST_PIN, 0)
        time.sleep(0.05)
        lgpio.gpio_write(self._h, RST_PIN, 1)
        time.sleep(0.15)

        self._cmd(_SWRESET); time.sleep(0.15)
        self._cmd(_SLPOUT);  time.sleep(0.5)
        self._cmd(_COLMOD);  self._data(0x05)   # 16-bit RGB565
        self._cmd(_MADCTL);  self._data(0x68)   # Landscape + BGR (joystick right)
        self._cmd(0x20)                           # INVOFF — needed with MADCTL 0x60
        time.sleep(0.01)
        self._cmd(_DISPON);  time.sleep(0.1)

        self.backlight(True)

    def _set_window(self, x0=0, y0=0, x1=None, y1=None):
        if x1 is None:
            x1 = WIDTH - 1
        if y1 is None:
            y1 = HEIGHT - 1
        self._cmd(_CASET)
        self._data([0x00, x0 + COL_OFS, 0x00, x1 + COL_OFS])
        self._cmd(_RASET)
        self._data([0x00, y0 + ROW_OFS, 0x00, y1 + ROW_OFS])

    def backlight(self, on: bool):
        lgpio.gpio_write(self._h, BL_PIN, 1 if on else 0)

    def clear(self, color=(0, 0, 0)):
        """Fill screen with a solid RGB color."""
        r, g, b = color
        c565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        hi = (c565 >> 8) & 0xFF
        lo = c565 & 0xFF

        self._set_window()
        self._cmd(_RAMWR)

        chunk = bytes([hi, lo] * 128)
        for _ in range(HEIGHT):
            self._data(chunk)

    def show_image(self, img: Image.Image):
        """Display a PIL Image (128x128 RGB)."""
        if img.size != (WIDTH, HEIGHT):
            img = img.resize((WIDTH, HEIGHT))
        if img.mode != "RGB":
            img = img.convert("RGB")

        pixels = img.tobytes()
        buf = bytearray(WIDTH * HEIGHT * 2)
        idx = 0
        for i in range(0, len(pixels), 3):
            r, g, b = pixels[i], pixels[i+1], pixels[i+2]
            c565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            buf[idx] = (c565 >> 8) & 0xFF
            buf[idx+1] = c565 & 0xFF
            idx += 2

        self._set_window()
        self._cmd(_RAMWR)
        # Send in 1024-byte chunks
        for i in range(0, len(buf), 1024):
            self._data(buf[i:i+1024])

    def test_pattern(self):
        """Show red/green/blue bands as a hardware test."""
        img = Image.new("RGB", (WIDTH, HEIGHT))
        pixels = img.load()
        third = HEIGHT // 3
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if y < third:
                    pixels[x, y] = (255, 0, 0)
                elif y < third * 2:
                    pixels[x, y] = (0, 255, 0)
                else:
                    pixels[x, y] = (0, 0, 255)
        self.show_image(img)

    def __del__(self):
        try:
            self.backlight(False)
            self._cmd(_DISPOFF)
            self._spi.close()
            if self._owns_gpio:
                lgpio.gpiochip_close(self._h)
        except Exception:
            pass
