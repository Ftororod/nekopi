#!/usr/bin/env python3
"""
NekoPi Field Unit — OLED Daemon v1.1
Waveshare 1.3" SH1106 · Portrait 64x128 · RPi5 lgpio
Codename: Tomás
"""
import time, threading, subprocess, urllib.request, json
import spidev, lgpio
from PIL import Image, ImageDraw, ImageFont

# ── Hardware ─────────────────────────────────────────────────
GPIOCHIP  = 4
DC_PIN    = 24
RST_PIN   = 25
WIDTH     = 64    # portrait width
HEIGHT    = 128   # portrait height
SPI_BUS   = 0
SPI_DEV   = 0
SPI_HZ    = 8_000_000

# Pines joystick y botones (BCM)
JOY_UP    = 6
JOY_DOWN  = 19
JOY_LEFT  = 5
JOY_RIGHT = 26
JOY_PRESS = 13
KEY1      = 21
KEY2      = 20
KEY3      = 16

API_BASE  = "http://localhost:8080/api"
API_TO    = 3

# ── Display driver ───────────────────────────────────────────
class SH1106:
    # Init para SH1106 con display montado en portrait
    # A1+C8 = mirror X+Y — HAT montado invertido físicamente
    INIT_SEQ = [
        0xAE, 0x02, 0x10, 0x40, 0x81, 0x7F,
        0xA1, 0xC8,
        0xA6, 0xA8, 0x3F, 0xD3, 0x00, 0xD5, 0x80,
        0xD9, 0xF1, 0xDA, 0x12, 0xDB, 0x40, 0x20, 0xAF
    ]

    def __init__(self):
        self.h = lgpio.gpiochip_open(GPIOCHIP)
        lgpio.gpio_claim_output(self.h, DC_PIN)
        lgpio.gpio_claim_output(self.h, RST_PIN)
        self.spi = spidev.SpiDev()
        self.spi.open(SPI_BUS, SPI_DEV)
        self.spi.max_speed_hz = SPI_HZ
        self.spi.mode = 0
        self._reset()
        for c in self.INIT_SEQ:
            self._cmd(c)

    def _reset(self):
        lgpio.gpio_write(self.h, RST_PIN, 1); time.sleep(0.05)
        lgpio.gpio_write(self.h, RST_PIN, 0); time.sleep(0.05)
        lgpio.gpio_write(self.h, RST_PIN, 1); time.sleep(0.05)

    def _cmd(self, c):
        lgpio.gpio_write(self.h, DC_PIN, 0)
        self.spi.writebytes([c])

    def display(self, img: Image.Image):
        """Enviar imagen 128x64 al SH1106 en modo landscape."""
        # Rotar 180° — el HAT Waveshare está montado invertido
        img = img.convert("1").resize((WIDTH, HEIGHT)).rotate(180)
        pixels = img.load()
        for page in range(8):
            self._cmd(0xB0 + page)
            # SH1106: columna inicial = 2 (offset físico del chip)
            self._cmd(0x02)   # lower col = 2 (SH1106 offset)
            self._cmd(0x10)   # upper col = 0
            lgpio.gpio_write(self.h, DC_PIN, 1)
            row_data = []
            for col in range(WIDTH):
                byte = 0
                for bit in range(8):
                    row = page * 8 + bit
                    if row < HEIGHT and pixels[col, row]:
                        byte |= (1 << bit)
                row_data.append(byte)
            self.spi.writebytes(row_data)

    def clear(self):
        self.display(Image.new('1', (WIDTH, HEIGHT), 0))

    def close(self):
        self.clear()
        self.spi.close()
        lgpio.gpiochip_close(self.h)


# ── Fonts ────────────────────────────────────────────────────
try:
    FONT_SM = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 8)
    FONT_MD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 10)
    FONT_LG = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 12)
except Exception:
    FONT_SM = FONT_MD = FONT_LG = ImageFont.load_default()


# ── Helpers ──────────────────────────────────────────────────
def new_canvas():
    img  = Image.new('1', (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(img)
    return img, draw

def header(draw, title: str):
    draw.rectangle([0, 0, WIDTH-1, 13], fill=1)
    draw.text((2, 2), title[:9], font=FONT_SM, fill=0)

def footer(draw, hint: str):
    draw.line([0, HEIGHT-12, WIDTH-1, HEIGHT-12], fill=1)
    draw.text((1, HEIGHT-11), hint[:10], font=FONT_SM, fill=1)

def api_get(path: str):
    try:
        with urllib.request.urlopen(f"{API_BASE}{path}", timeout=API_TO) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── Splash ───────────────────────────────────────────────────
def draw_splash(oled: SH1106):
    img, draw = new_canvas()
    # NekoPi title
    draw.text((2,  4), "NekoPi",    font=FONT_LG, fill=1)
    draw.text((2, 20), "Field Unit", font=FONT_SM, fill=1)
    draw.line([0, 34, WIDTH-1, 34], fill=1)
    # Gato Tomás ASCII — simple pero reconocible
    cat = [
        " /\\_/\\ ",
        "(o . o)",
        " > ^ < ",
        "  ---  ",
    ]
    for i, line in enumerate(cat):
        draw.text((4, 38 + i*12), line, font=FONT_SM, fill=1)
    draw.line([0, 90, WIDTH-1, 90], fill=1)
    draw.text((2,  93), "Tomas", font=FONT_SM, fill=1)
    draw.text((2, 104), "v1.0.0", font=FONT_SM, fill=1)
    oled.display(img)
    time.sleep(3)


# ── Screens ──────────────────────────────────────────────────
def screen_dashboard(data: dict) -> Image.Image:
    img, draw = new_canvas()
    # Header compacto
    draw.rectangle([0, 0, WIDTH-1, 10], fill=1)
    draw.text((2, 1), "DASHBOARD", font=FONT_SM, fill=0)

    net  = data.get("net",  {})
    sys_ = data.get("sys",  {})
    prob = data.get("prob", {})

    y = 13
    ifaces = [i for i in net.get("interfaces", []) if i.get("ip")]
    for iface in ifaces[:2]:
        label = (iface.get("label") or iface["name"])[:6]
        ip    = iface.get("ip", "")
        role  = "[T]" if iface.get("is_test") else "[G]" if iface.get("is_gw") else ""
        draw.text((0, y), f"{label}{role} {ip}", font=FONT_SM, fill=1)
        y += 10

    draw.line([0, y, WIDTH-1, y], fill=1); y += 2

    gw_rtt  = prob.get("gw_rtt")
    loss    = prob.get("loss_pct", 0)
    rtt_str = f"{gw_rtt:.1f}ms" if gw_rtt else "---"
    temp    = sys_.get("cpu_temp", "?")
    draw.text((0, y),    f"GW:{rtt_str}  Loss:{loss:.0f}%", font=FONT_SM, fill=1); y += 10
    draw.text((0, y),    f"Temp:{temp}C", font=FONT_SM, fill=1); y += 10
    draw.line([0, 53, WIDTH-1, 53], fill=1)
    draw.text((2, 55), "PRESS=Menu", font=FONT_SM, fill=1)
    return img


def screen_menu(selected: int) -> Image.Image:
    items = ["Dashboard", "QuickChk", "WiFi Scan", "System", "Power"]
    img, draw = new_canvas()
    # Header compacto
    draw.rectangle([0, 0, WIDTH-1, 10], fill=1)
    draw.text((2, 1), "MENU", font=FONT_SM, fill=0)
    # Items — 10px cada uno, empezando en y=13
    for i, item in enumerate(items):
        y = 13 + i * 10
        if i == selected:
            draw.rectangle([0, y, WIDTH-1, y+9], fill=1)
            draw.text((4, y+1), ">" + item, font=FONT_SM, fill=0)
        else:
            draw.text((4, y+1), " " + item, font=FONT_SM, fill=1)
    return img


def screen_quickcheck(results: list) -> Image.Image:
    img, draw = new_canvas()
    header(draw, "QK CHECK")
    if not results:
        draw.text((2, 30), "No data", font=FONT_MD, fill=1)
        draw.text((2, 50), "K1=Run", font=FONT_SM, fill=1)
        footer(draw, "K1=Run")
        return img
    passed = sum(1 for t in results if t.get("ok"))
    draw.text((2, 17), f"{passed}/{len(results)} PASS", font=FONT_MD, fill=1)
    draw.line([0, 30, WIDTH-1, 30], fill=1)
    for i, t in enumerate(results[:4]):
        y = 34 + i * 20
        ok  = t.get("ok", False)
        sym = "+" if ok else "X"
        name = t.get("name","")[:7]
        val  = t.get("val","")[:6]
        clr  = 1
        if not ok:
            draw.rectangle([0, y-1, WIDTH-1, y+17], outline=1)
        draw.text((0, y),   f"{sym} {name}", font=FONT_SM, fill=clr)
        draw.text((4, y+9), val,              font=FONT_SM, fill=clr)
    footer(draw, "K1=ReRun")
    return img


def screen_wifi(aps: list) -> Image.Image:
    img, draw = new_canvas()
    header(draw, "WIFI APs")
    if not aps:
        draw.text((2, 35), "Sin APs", font=FONT_MD, fill=1)
        draw.text((2, 55), "K2=Scan", font=FONT_SM, fill=1)
        footer(draw, "K2=Scan")
        return img
    draw.text((0, 16), f"{len(aps)} APs", font=FONT_SM, fill=1)
    draw.line([0, 26, WIDTH-1, 26], fill=1)
    for i, ap in enumerate(aps[:4]):
        y = 29 + i * 22
        ssid = (ap.get("ssid") or "(hidden)")[:8]
        rssi = ap.get("signal_dbm", 0)
        band = (ap.get("band") or "?")[:5]
        draw.text((0, y),    ssid,          font=FONT_SM, fill=1)
        draw.text((0, y+11), f"{rssi} {band}", font=FONT_SM, fill=1)
    footer(draw, "K2=Scan")
    return img


def screen_system(data: dict) -> Image.Image:
    img, draw = new_canvas()
    header(draw, "SYSTEM")
    ab   = data.get("about", {})
    sys_ = data.get("sys", {})
    net  = data.get("net", {})

    hostname = ab.get("hostname", "nekopi")
    uptime   = ab.get("uptime", "?")
    temp     = sys_.get("cpu_temp", "?")
    ram      = sys_.get("ram") or {}
    used  = ram.get("used_mb", 0) // 1024
    total = ram.get("total_mb", 0) // 1024
    gw_i  = next((i for i in net.get("interfaces",[]) if i.get("is_gw")), None)
    ip_mgmt = gw_i["ip"] if gw_i else "?"

    lines = [
        f"{hostname}",
        f"Up: {uptime}",
        f"RAM:{used}/{total}G",
        f"T:{temp}C",
        f"{ip_mgmt}",
        f":8080",
    ]
    for i, line in enumerate(lines):
        draw.text((2, 17 + i * 17), line, font=FONT_SM, fill=1)
    footer(draw, "K2=Refresh")
    return img


def screen_power(selected: int, confirm: bool) -> Image.Image:
    img, draw = new_canvas()
    header(draw, "POWER")
    items = ["Cancelar", "Reboot", "Shutdown"]
    for i, item in enumerate(items):
        y = 20 + i * 25
        if i == selected:
            draw.rectangle([0, y-2, WIDTH-1, y+13], fill=1)
            draw.text((2, y), f">{item}", font=FONT_SM, fill=0)
        else:
            draw.text((2, y), f" {item}", font=FONT_SM, fill=1)
    if confirm:
        draw.rectangle([2, 100, WIDTH-3, 116], fill=1)
        draw.text((4, 103), "CONFIRM?", font=FONT_SM, fill=0)
    else:
        footer(draw, "<Back OK=Sel")
    return img


# ── Data cache ───────────────────────────────────────────────
class DataCache:
    def __init__(self):
        self.lock = threading.Lock()
        self._d   = {"net":{}, "sys":{}, "about":{}, "prob":{}, "qc":[], "wifi":[]}
        threading.Thread(target=self._loop, daemon=True).start()

    def _refresh(self):
        net    = api_get("/network/info")   or {}
        sys_   = api_get("/system/metrics") or {}
        about  = api_get("/about")          or {}
        probes = (api_get("/network/probes") or {}).get("probes", [])
        gw_p   = next((p for p in probes if p["name"]=="Gateway"), None)
        loss   = sum(1 for p in probes if p.get("loss"))
        with self.lock:
            self._d.update({
                "net": net, "sys": sys_, "about": about,
                "prob": {
                    "gw_rtt":   gw_p["rtt_ms"] if gw_p and not gw_p.get("loss") else None,
                    "loss_pct": (loss/len(probes)*100) if probes else 0,
                    "probes":   probes,
                }
            })

    def _loop(self):
        self._refresh()
        while True:
            time.sleep(30)
            try: self._refresh()
            except Exception: pass

    def get(self):
        with self.lock: return dict(self._d)

    def run_qc(self):
        r = api_get("/qc/run") or {}
        with self.lock: self._d["qc"] = r.get("tests", [])

    def scan_wifi(self):
        r = api_get("/wifi/scan") or {}
        aps = sorted(r.get("aps",[]), key=lambda a: a.get("signal_dbm",-100), reverse=True)
        with self.lock: self._d["wifi"] = aps


# ── Input ────────────────────────────────────────────────────
class InputHandler:
    PINS = {"up":JOY_UP,"down":JOY_DOWN,"left":JOY_LEFT,
            "right":JOY_RIGHT,"press":JOY_PRESS,"k1":KEY1,"k2":KEY2,"k3":KEY3}

    def __init__(self, h):
        self.h = h; self.last = {}; self.events = []; self.lock = threading.Lock()
        for name, pin in self.PINS.items():
            try: lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_UP)
            except Exception: pass
            self.last[pin] = 1
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        while True:
            time.sleep(0.05)
            for name, pin in self.PINS.items():
                try:
                    val = lgpio.gpio_read(self.h, pin)
                    if val == 0 and self.last[pin] == 1:
                        with self.lock: self.events.append(name)
                    self.last[pin] = val
                except Exception: pass

    def get(self):
        with self.lock: return self.events.pop(0) if self.events else None


# ── App ──────────────────────────────────────────────────────
class NekoPiOLED:
    def __init__(self):
        self.oled       = SH1106()
        self.cache      = DataCache()
        self.input      = InputHandler(self.oled.h)
        self.screen     = "dashboard"
        self.backlight  = True
        self.menu_sel   = 0
        self.power_sel  = 0
        self.power_conf = False
        self.power_ts   = 0

    def run(self):
        draw_splash(self.oled)
        self._render()
        last_refresh = time.time()
        while True:
            event = self.input.get()
            if event:
                self._handle(event)
                self._render()
            else:
                time.sleep(0.05)
                if time.time() - last_refresh > 10:
                    self._render()
                    last_refresh = time.time()
            # Auto-cancel power confirm
            if self.power_conf and (time.time()-self.power_ts) > 5:
                self.power_conf = False
                if self.screen == "power": self._render()

    def _handle(self, event: str):
        if event == "k3":
            self.backlight = not self.backlight
            if not self.backlight: self.oled.clear()
            return
        if not self.backlight:
            self.backlight = True; return

        s = self.screen
        if s == "dashboard":
            if event == "press": self.screen = "menu"; self.menu_sel = 0

        elif s == "menu":
            if event == "up":    self.menu_sel = (self.menu_sel-1) % 5
            elif event == "down":self.menu_sel = (self.menu_sel+1) % 5
            elif event == "left":self.screen = "dashboard"
            elif event == "press":
                self.screen = ["dashboard","quickcheck","wifi","system","power"][self.menu_sel]
                if self.screen == "power": self.power_sel=0; self.power_conf=False

        elif s == "quickcheck":
            if event == "left":  self.screen = "menu"
            elif event in ("k1","k2"):
                threading.Thread(target=self.cache.run_qc, daemon=True).start()

        elif s == "wifi":
            if event == "left":  self.screen = "menu"
            elif event == "k2":
                threading.Thread(target=self.cache.scan_wifi, daemon=True).start()

        elif s == "system":
            if event == "left":  self.screen = "menu"
            elif event == "k2":
                threading.Thread(target=self.cache._refresh, daemon=True).start()

        elif s == "power":
            if event == "left":
                self.screen = "menu"; self.power_conf = False
            elif event == "up":
                self.power_sel = (self.power_sel-1)%3; self.power_conf=False
            elif event == "down":
                self.power_sel = (self.power_sel+1)%3; self.power_conf=False
            elif event == "press":
                if self.power_sel == 0:
                    self.screen = "menu"
                elif not self.power_conf:
                    self.power_conf = True; self.power_ts = time.time()
                else:
                    if self.power_sel == 1:
                        self._msg("Rebooting..."); subprocess.run(["sudo","reboot"])
                    else:
                        self._msg("Shutdown..."); subprocess.run(["sudo","shutdown","-h","now"])

        # K1 = home desde cualquier pantalla
        if event == "k1" and s not in ("quickcheck",):
            self.screen = "dashboard"

    def _msg(self, text: str):
        img, draw = new_canvas()
        draw.text((2, 55), text, font=FONT_MD, fill=1)
        self.oled.display(img); time.sleep(2)

    def _render(self):
        if not self.backlight: return
        d = self.cache.get()
        screens = {
            "dashboard":  lambda: screen_dashboard(d),
            "menu":       lambda: screen_menu(self.menu_sel),
            "quickcheck": lambda: screen_quickcheck(d.get("qc",[])),
            "wifi":       lambda: screen_wifi(d.get("wifi",[])),
            "system":     lambda: screen_system(d),
            "power":      lambda: screen_power(self.power_sel, self.power_conf),
        }
        fn = screens.get(self.screen, lambda: screen_dashboard(d))
        self.oled.display(fn())


if __name__ == "__main__":
    app = NekoPiOLED()
    try:
        app.run()
    except KeyboardInterrupt:
        app.oled.close()
