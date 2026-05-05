# NekoPi Field Unit — Installation & Hardware Notes

## 8.12 LCD HAT — Hardware findings

### Panel: Waveshare 1.44" ST7735S 128x128

- **MADCTL register**: Must be `0x68` (BGR byte order), NOT `0x60` (RGB). This specific ST7735S panel has R/B channels swapped.
- **SPI**: `/dev/spidev0.0`, DC=GPIO25, RST=GPIO27, BL=GPIO18 (active high)
- **Backlight**: PWM via GPIO18 or simple on/off

### GPIO / Input (RPi5 gpiochip4)

- **lgpio.callback() does NOT work** on RPi5/gpiochip4 — edge detection via callbacks is unsupported. Solution: polling thread at 50ms interval with software debounce.
- **Group access**: User must be in `dialout` group for `/dev/gpiochip4` (not `gpio` as on Raspbian/RPi OS).
- **Pull-ups**: Must be configured in `/boot/firmware/config.txt`:
  ```
  gpio=6,19,5,26,13,21,20,16=pu
  ```
- **Joystick + keys pinout** (active LOW with pull-ups):
  - Joystick: UP=6, DOWN=19, LEFT=5, RIGHT=26, CENTER=13
  - Keys: K1=21, K2=20, K3=16

### Network interfaces (discovered)

| Interface | Driver | Chipset | Role |
|---|---|---|---|
| eth0 | r8125 | RTL8125B 2.5GbE HAT | TEST — client network |
| eth1 | macb | RPi5 native NIC | MGMT — 192.168.99.1/24 |
| wlan0 | iwlwifi | Intel AX210 WiFi 6E | Home/office (2.4/5/6 GHz) |
| wlan1 | brcmfmac | Broadcom BCM43455 (onboard) | UNUSED — should be disabled |
| wlan2 | mt7921u | MediaTek MT7921AU USB | Monitor/profiling (2.4/5/6 GHz) |

### API / Services

- **HTTPS only** on `:8080` with self-signed cert — all API calls use `verify=False`
- No HTTP on `:8000` (redirected or not exposed)
- `/api/about` has >2s response time — LCD uses `timeout=5`
- Reboot/shutdown via `sudo systemctl reboot|poweroff` (permitted by `/etc/sudoers.d/nekopi`)

### Systemd service

```ini
# /etc/systemd/system/nekopi-lcd.service
[Unit]
Description=NekoPi LCD HAT daemon
After=network.target nekopi.service

[Service]
Type=simple
User=nekopi
Group=nekopi
WorkingDirectory=/opt/nekopi/lcd
ExecStart=/opt/nekopi/venv/bin/python3 nekopi_lcd.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## 8.13 Estado v1.3.0 y roadmap

**Funcional en v1.3.0:**
- 20 pantallas: Home rotativo (Network/Latency/System), Dashboard, Quick Check, WiFi Scan, System, Power, Tools/Captures/Services con action_view para 16 acciones
- State machine con doble confirmación + timeout 5s
- Background workers: status polling 8s, data refresh 5-10s, latency rotativa 10s
- Reboot/shutdown end-to-end desde LCD
- QR del Hotspot WiFi
- Polling de WiFi connection info (SSID/canal/RSSI)

**Pendientes para v1.4 — ver `lcd/TODO.md`:**
- 5 fixes funcionales (DHCP Test selector, iPerf Server filtrado, Captive/Quick Check/WiFi Scan resultados visibles)
- Pantalla About con logo + versión
- DNS Benchmark comparativo (vs hoy: solo lookup time)
- iPerf Client con selector de target
- Profiler `/api/profiler/status` enriquecido con clients/SSID/RSSI
