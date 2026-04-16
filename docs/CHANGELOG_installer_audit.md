# Installer Audit & GPL v3 Migration — CHANGELOG

Date: 2026-04-16
Audit trigger: test install on a generic Linux server (no WiFi, no RTL8125B HAT, no MT7921AU) exposed multiple brittle assumptions about interface naming and hardware availability.

---

## 1. Hardware detection & graceful module degradation

### Installer (`build_installer_v2.py` → `install_nekopi.sh`)
- **New step 0 — HARDWARE DETECTION:** probes `wlan0`, `wlan1`, `eth0`, `eth1` existence and does driver-based lookup (`bcmgenet`/`macb` → MGMT, `r8169`/`r8125` → TEST). Writes results to `/opt/nekopi/data/hw_caps.json` before any service starts.
- **Step 24 — POST-INSTALL VERIFICATION:** `verify_install()` function validates each requirement and skips hardware-conditional checks (MGMT IP, wlan1 monitor mode) when the hardware is absent. Failures increment an error counter; exit banner reflects real status.
- **Backwards compatible:** `hw_caps.json` is optional — if missing (old installs), the backend falls back to live sysfs probing and the UI shows everything.

### Backend (`api/main.py`)
- Added `get_hw_caps()` that merges the on-disk `hw_caps.json` with a live sysfs probe (hot-plug of USB WiFi is picked up without reinstall).
- New endpoint **`GET /api/hw-caps`** returning: `{wlan0, wlan1, eth0, eth1, eth_mgmt, eth_test, wifi_monitor, wifi_uplink, mgmt_iface, test_iface}`.
- New helper `_no_hw_response(missing)` emits `{"status": "no_hardware", "missing": "wlan1", "message": "..."}` — used by every hardware-dependent endpoint.
- Endpoints updated:
  - `GET /api/wifi/scan` — returns `no_hardware` when no WiFi iface exists.
  - `GET /api/wifi/monitor` — NEW, returns `no_hardware` / current monitor-mode state.
  - `GET /api/kismet/status` — NEW, combines hardware check + Kismet daemon ping.
  - `GET /api/roaming/status` — returns `no_hardware` when wlan1 absent.

### Frontend (`ui/index.html`)
- New `HW_REQUIREMENTS` map + `applyHwGating(caps)` function in the main `<script>` block.
- `nkInit()` fetches `/api/hw-caps` on load and disables nav items whose required capabilities are missing, with a tooltip `"No disponible en este hardware" / "Not available on this hardware"` in the active UI language.
- Gated modules: `wifi`, `roaming`, `kismet`, `profiler`, `ota`, `security`, `wired`.
- Demo mode / no-backend / missing caps file → gating is **skipped** (backwards compatible).

---

## 2. Interface mapping — driver-based, name-agnostic

**Root cause:** RPi5 numbers Ethernet interfaces by PCIe enumeration order. With HAT attached, `eth0 = HAT (r8169)` and `eth1 = native (bcmgenet)`. Without HAT, `eth0 = native` and `eth1` doesn't exist — netplan and dnsmasq pointed at a missing interface.

### Fix
- **Netplan** (`/etc/netplan/01-nekopi-mgmt.yaml`):
  - Removed legacy `01-nekopi.yaml` that hardcoded `eth1`.
  - New config uses `match: { driver: bcmgenet }` + `set-name: eth-mgmt`, and `match: { driver: r8169 }` + `set-name: eth-test`.
  - Both marked `optional: true` so boot doesn't block on a missing HAT.
- **dnsmasq** binds to `eth-mgmt` (with fallback to `$MGMT_IFACE` detected in step 0).
- **Backend helpers** `get_mgmt_iface()` / `get_test_iface()` search by driver and fall back to `eth-mgmt`/`eth-test` then kernel names.
- **Security Audit** (`/api/security/start`) and **Kismet URL** (`/api/kismet/url`) auto-detect subnet from `get_test_iface()` instead of hardcoded `eth0`. If no IP is present, endpoint now returns `{"status": "no_subnet", "message": "..."}` instead of scanning a fake `192.168.1.0/24`.

---

## 3. Hardcoded data → real values

### Backend (`api/main.py`)
| Location | Before | After |
|----------|--------|-------|
| `GET /api/network/probes` Gateway target | `"192.168.1.1"` fallback | `None` (UI renders `—`) |
| `GET /api/scan/network` target default | `"192.168.1.0/24"` | Auto-detect from TEST iface; `no_subnet` response if unavailable |
| Security Audit subnet auto-detect | hardcoded `eth0` + `192.168.1.0/24` fallback | Driver-based `get_test_iface()`; `no_subnet` response if no IP |
| ARP scan subnet fallback | `"192.168.1.0/24"` | Error response asking user for subnet |
| Kismet URL fallback | `ip addr show eth0` | `ip addr show $(get_test_iface())` |

### Frontend (`ui/index.html`)
| Location | Before | After |
|----------|--------|-------|
| About tagline (static) | `… · MIT License` | `… · GPL v3 License` |
| About footer (static) | `MIT License · Open Source …` | `GPL v3 License · Open Source …` |
| About tagline (dynamic) | reads `n.license` from API | same — API now returns `GPL-3.0` |
| Security target fallback | `el.value = '192.168.1.0/24'` | placeholder only (no auto-fill) |

### Not changed (intentional)
- Demo-mode simulation data (`DEMO_MODE` branch, lines 5569–5595, 3193–3232) — the `/demo` endpoint is the public `nekopi.net` preview; its data is supposed to be deterministic and obvious.
- Form `placeholder` attributes with example IPs (CIDR tools, subnet calculators) — these are user-education hints, never submitted as real data.
- Default `iface` parameters on toolkit endpoints (e.g. `iface: str = "eth0"`) — UI always passes the real iface; these are schema defaults for Swagger docs only.

---

## 4. Installer robustness fixes

- **Kismet repo conflict:** already-disabled; verified with `sed 's/^deb /# deb /'` on `kismet*.list`.
- **tshark non-interactive:** `debconf-set-selections` feeds `wireshark-common/install-setuid=true` and installs run under `DEBIAN_FRONTEND=noninteractive`.
- **dnsmasq vs systemd-resolved:** installer now sets `DNSStubListener=no` in `/etc/systemd/resolved.conf`, restarts `systemd-resolved`, and ensures `/etc/resolv.conf` symlink is valid before starting dnsmasq.
- **InfluxDB race:** `sleep 5` + up to 40s `influx ping` loop + 3-attempt retry on `influx setup`. Previous version often lost the token on first install because `setup` raced with service init.
- **Python pip `--break-system-packages`:** all `pip install` calls are made via the venv's own pip (`$NEKOPI_DIR/venv/bin/pip`), which is isolated from system packages and does not need the flag. Noted in comment.
- **Data dir ownership:** added explicit `chown nekopi:nekopi $NEKOPI_DIR/data` and `chmod 755` after repo clone (clone can overwrite ownership).

---

## 5. License migration — MIT → GPL-3.0-or-later

- `LICENSE` replaced with the official GPL v3 text from gnu.org (674 lines).
- SPDX + full GPL v3 header added to the top of `api/main.py` and inside the main `<script>` block of `ui/index.html`.
- SPDX header added at the top of `build_installer_v2.py`; generated `install_nekopi.sh` declares `License: GPL-3.0-or-later` in its banner comment.
- `README.md`: MIT badge → GPL v3 badge; new "License" section explaining copyleft intent; footer and Contributing section updated.
- `index.html` (landing page): MIT badge and footer link → GPL v3.
- `ui/index.html` and `ui/demo.html`: About tagline and footer text updated.
- Backend `/api/about` now returns `"license": "GPL-3.0"`, so the dynamic About page reads correctly on older deployments after server update.
- WLAN Pi Profiler credit line corrected: it's actually BSD-3-Clause, not MIT.
- Final grep for `MIT License`, `license.*MIT`, `License-MIT`, `"license": "MIT"`, `SPDX-License-Identifier: MIT`, and bare `\bMIT\b` returns zero matches across all tracked `.py/.html/.md/.json/.sh/.txt/.yml/.yaml/.js/.css` files.

---

## 6. Unresolved / follow-up items

- **WiFi uplink detection for NAT:** `iptables MASQUERADE` is still hardcoded to `wlan0`/`eth0` at `api/main.py:~1801-1804`. Should key off `hw_caps.wifi_uplink` / `test_iface`. Not fixed here because the NAT logic is tightly coupled to a Settings toggle; safe refactor deferred to a dedicated PR.
- **Default `iface=` query params** on toolkit endpoints (ARP scan, DHCP/TFTP server, MAC clone, static IP set, VoIP/QoS, VLAN probe, etc.) still default to `"eth0"` / `"wlan1"`. UI always passes the real iface from `/api/hw-caps`, so this only affects direct API callers / Swagger docs. Leaving as-is to avoid a large diff with no runtime effect.
- **Demo hardcoded device table** at `ui/index.html:3193-3232`: legitimate marketing/demo content. Not migrated.
- **Version & codename** (`v1.3.0`, `Tomás`/`ToManchas`) are still hardcoded in a couple of places. Not in scope for this audit; would require a single source-of-truth file (`VERSION`) and a small reader. Tracked separately.
