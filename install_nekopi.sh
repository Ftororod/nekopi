#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  NekoPi Field Unit — Automated Installer v2
#  Version:   1.3.0  ·  Codename: ToManchas
#  Generated: 2026-04-16 15:17
#  Target:    Ubuntu 24.04 LTS · Raspberry Pi 5 · 8 GB
#  License:   GPL-3.0-or-later
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

NEKOPI_DIR="/opt/nekopi"
NEKOPI_USER="nekopi"
NEKOPI_PORT=8080
REPO_URL="https://github.com/Ftororod/nekopi.git"
REPO_BRANCH="main"

INSTALL_LOG="/var/log/nekopi/install.log"
mkdir -p "$(dirname "$INSTALL_LOG")"
: > "$INSTALL_LOG"

# Must be root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (sudo)"
    exit 1
fi


# ── Progress display helpers ─────────────────────────────────────────
# Colors — only when stdout is a TTY
if [ -t 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
    GRAY='\033[0;90m';  BOLD='\033[1m';      RED='\033[0;31m'
    RESET='\033[0m'
else
    GREEN=''; YELLOW=''; CYAN=''; GRAY=''; BOLD=''; RED=''; RESET=''
fi

NEKOPI_TOTAL_STEPS=24

NEKOPI_CURRENT_STEP=0
NEKOPI_START_TIME=$(date +%s)
NEKOPI_STEP_START=0
NEKOPI_COMPLETED=()   # entries of the form "N:label:seconds"
NEKOPI_SKIPPED=()     # entries of the form "N:label:reason"

_nk_tty() { [ -t 1 ]; }

_nk_banner() {
    local version codename
    # Read VERSION file at runtime so this works regardless of when the
    # installer was generated vs. when the user runs it.
    if [ -f "$NEKOPI_DIR/VERSION" ]; then
        version=$(head -n 1 "$NEKOPI_DIR/VERSION" 2>/dev/null)
        codename=$(sed -n '2p' "$NEKOPI_DIR/VERSION" 2>/dev/null)
    elif [ -f "$(dirname "$0")/VERSION" ]; then
        version=$(head -n 1 "$(dirname "$0")/VERSION" 2>/dev/null)
        codename=$(sed -n '2p' "$(dirname "$0")/VERSION" 2>/dev/null)
    fi
    version="${version:-unknown}"
    codename="${codename:-unknown}"
    echo ""
    echo -e "${CYAN}╔════════════════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}║${RESET}  ${BOLD}NekoPi Field Unit${RESET}"
    echo -e "${CYAN}║${RESET}  ${CYAN}v${version} · Codename: ${codename}${RESET}"
    echo -e "${CYAN}║${RESET}  GPL v3 · ~8 min total"
    echo -e "${CYAN}╚════════════════════════════════════════════════╝${RESET}"
    echo ""
}

_nk_section() {
    local title="$1"
    echo ""
    echo -e "${GRAY}── ${title} ──────────────────────────────────────${RESET}"
    echo ""
}

_nk_step_start() {
    NEKOPI_CURRENT_STEP="$1"
    NEKOPI_STEP_START=$(date +%s)
    if _nk_tty; then
        echo -e "${GRAY}[${1}/${NEKOPI_TOTAL_STEPS}]${RESET} ${YELLOW}⠸  ${2}${RESET}"
    else
        echo "[${1}/${NEKOPI_TOTAL_STEPS}] ..  ${2}"
    fi
}

_nk_step_done() {
    local elapsed=$(( $(date +%s) - NEKOPI_STEP_START ))
    if _nk_tty; then
        # Rewrite the in-progress line as completed
        echo -ne "\033[1A\033[2K"
        echo -e "${GRAY}[${1}/${NEKOPI_TOTAL_STEPS}]${RESET} ${GREEN}✔  ${2}${RESET}   ${GRAY}${elapsed}s${RESET}"
    else
        echo "[${1}/${NEKOPI_TOTAL_STEPS}] ✔  ${2}   ${elapsed}s"
    fi
    NEKOPI_COMPLETED+=("${1}:${2}:${elapsed}")
}

_nk_step_skip() {
    if _nk_tty; then
        echo -ne "\033[1A\033[2K"
        echo -e "${GRAY}[${1}/${NEKOPI_TOTAL_STEPS}]${RESET} ${GRAY}–  ${2}${RESET}"
    else
        echo "[${1}/${NEKOPI_TOTAL_STEPS}] –  ${2}"
    fi
    echo -e "         ${GRAY}(skipped — ${3})${RESET}"
    NEKOPI_SKIPPED+=("${1}:${2}:${3}")
    NEKOPI_CURRENT_STEP="$1"
}

_nk_hw_pills() {
    echo -ne "         "
    local pair iface status
    for pair in "$@"; do
        iface="${pair%%:*}"
        status="${pair##*:}"
        if [ "$status" = "yes" ]; then
            echo -ne "${GREEN}${iface} ✔${RESET}  "
        else
            echo -ne "${GRAY}${iface} —${RESET}  "
        fi
    done
    echo ""
}

_nk_pkg_progress() {
    local pkg="$1" idx="$2" total="$3"
    local bar_fill=$(( idx * 20 / total ))
    local i bar_fill_str="" bar_empty_str=""
    for i in $(seq 1 20); do
        if [ "$i" -le "$bar_fill" ]; then
            bar_fill_str="${bar_fill_str}="
        else
            bar_empty_str="${bar_empty_str}-"
        fi
    done
    if _nk_tty; then
        echo -ne "\033[1A\033[2K"
        printf '%b[%s/%s]%b %b⠸  Installing %-16s%b [%b%s%b%b%s%b]  %d/%d\n' \
            "$GRAY" "$NEKOPI_CURRENT_STEP" "$NEKOPI_TOTAL_STEPS" "$RESET" \
            "$YELLOW" "$pkg" "$RESET" \
            "$CYAN" "$bar_fill_str" "$RESET" \
            "$GRAY" "$bar_empty_str" "$RESET" \
            "$idx" "$total"
    else
        echo "    Installing: ${pkg} (${idx}/${total})"
    fi
}

_nk_overall_progress() {
    local elapsed=$(( $(date +%s) - NEKOPI_START_TIME ))
    local pct=$(( NEKOPI_CURRENT_STEP * 100 / NEKOPI_TOTAL_STEPS ))
    local bar_fill=$(( pct * 30 / 100 ))
    local i bar_fill_str="" bar_empty_str=""
    for i in $(seq 1 30); do
        if [ "$i" -le "$bar_fill" ]; then
            bar_fill_str="${bar_fill_str}="
        else
            bar_empty_str="${bar_empty_str}-"
        fi
    done
    local elapsed_fmt
    if [ "$elapsed" -lt 60 ]; then
        elapsed_fmt="${elapsed}s"
    else
        elapsed_fmt="$((elapsed/60))m $((elapsed%60))s"
    fi
    echo ""
    echo -e "${GRAY}─────────────────────────────────────────────────────────${RESET}"
    echo -e "Overall  [${CYAN}${bar_fill_str}${RESET}${GRAY}${bar_empty_str}${RESET}]  ${BOLD}${pct}%${RESET}"
    echo -e "Elapsed: ${elapsed_fmt}"
    echo ""
}

_nk_on_error() {
    local rc="$1"
    echo ""
    echo -e "${RED}❌ Installation failed at step ${NEKOPI_CURRENT_STEP}${RESET}"
    echo -e "${GRAY}   Last 40 lines of ${INSTALL_LOG}:${RESET}"
    echo -e "${GRAY}   ──────────────────────────────────────────────────────${RESET}"
    tail -40 "$INSTALL_LOG" 2>/dev/null | sed 's/^/   /'
    exit "$rc"
}
trap '_nk_on_error $?' ERR

_nk_banner
_nk_section "starting installation"


_nk_step_start 1 "Hardware detection"
{
HAS_WLAN0="no"; HAS_WLAN1="no"; HAS_ETH0="no"; HAS_ETH1="no"
HAS_ETH_MGMT="no"; HAS_ETH_TEST="no"
MGMT_IFACE=""; TEST_IFACE=""

detect_iface() {
    local name="$1"
    ip link show "$name" &>/dev/null && echo "yes" || echo "no"
}

HAS_WLAN0=$(detect_iface wlan0)
HAS_WLAN1=$(detect_iface wlan1)
HAS_ETH0=$(detect_iface eth0)
HAS_ETH1=$(detect_iface eth1)

# Driver-based detection — stable across HAT present/absent
for iface in $(ls /sys/class/net/ 2>/dev/null); do
    [ "$iface" = "lo" ] && continue
    [ -L "/sys/class/net/$iface/device/driver" ] || continue
    driver=$(basename "$(readlink -f /sys/class/net/$iface/device/driver)")
    case "$driver" in
        bcmgenet|macb)  HAS_ETH_MGMT="yes"; MGMT_IFACE="$iface" ;;
        r8169|r8125)    HAS_ETH_TEST="yes"; TEST_IFACE="$iface" ;;
    esac
done

[ -z "$MGMT_IFACE" ] && [ "$HAS_ETH1" = "yes" ] && MGMT_IFACE="eth1"
[ -z "$MGMT_IFACE" ] && [ "$HAS_ETH0" = "yes" ] && MGMT_IFACE="eth0"
[ -z "$TEST_IFACE" ] && [ "$HAS_ETH0" = "yes" ] && TEST_IFACE="eth0"

echo "  wlan0 (built-in WiFi):   $HAS_WLAN0"
echo "  wlan1 (USB monitor adp): $HAS_WLAN1"
echo "  eth0  (kernel name):     $HAS_ETH0"
echo "  eth1  (kernel name):     $HAS_ETH1"
echo "  mgmt  (driver-matched):  $HAS_ETH_MGMT ($MGMT_IFACE)"
echo "  test  (driver-matched):  $HAS_ETH_TEST ($TEST_IFACE)"

mkdir -p "$NEKOPI_DIR/data"
cat > "$NEKOPI_DIR/data/hw_caps.json" <<HWCAPS
{
  "wlan0": $( [ "$HAS_WLAN0" = "yes" ] && echo true || echo false ),
  "wlan1": $( [ "$HAS_WLAN1" = "yes" ] && echo true || echo false ),
  "eth0":  $( [ "$HAS_ETH0"  = "yes" ] && echo true || echo false ),
  "eth1":  $( [ "$HAS_ETH1"  = "yes" ] && echo true || echo false ),
  "eth_mgmt":     $( [ "$HAS_ETH_MGMT" = "yes" ] && echo true || echo false ),
  "eth_test":     $( [ "$HAS_ETH_TEST" = "yes" ] && echo true || echo false ),
  "wifi_monitor": $( [ "$HAS_WLAN1" = "yes" ] && echo true || echo false ),
  "wifi_uplink":  $( [ "$HAS_WLAN0" = "yes" ] && echo true || echo false ),
  "mgmt_iface": "$MGMT_IFACE",
  "test_iface": "$TEST_IFACE",
  "generated_at": "$(date -Iseconds)"
}
HWCAPS
sed -i 's/^    //' "$NEKOPI_DIR/data/hw_caps.json"

export HAS_WLAN0 HAS_WLAN1 HAS_ETH0 HAS_ETH1 HAS_ETH_MGMT HAS_ETH_TEST
export MGMT_IFACE TEST_IFACE
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 1 "Hardware detection"
_nk_hw_pills "eth-mgmt:$HAS_ETH_MGMT" "eth-test:$HAS_ETH_TEST" "wlan0:$HAS_WLAN0" "wlan1:$HAS_WLAN1"


_nk_step_start 2 "User nekopi"
{
if ! id "$NEKOPI_USER" &>/dev/null; then
    adduser --disabled-password --gecos "NekoPi" "$NEKOPI_USER"
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 2 "User nekopi"


_nk_step_start 3 "Directories"
{
mkdir -p "$NEKOPI_DIR"/{api,bin,captures/kismet,captures/ota,data,logs,oled,reports,ssl,tftp,ui/assets}
mkdir -p /srv/tftp
chmod 777 /srv/tftp
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
chmod 755 "$NEKOPI_DIR/data"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 3 "Directories"


_nk_step_start 4 "APT repositories"
{
# InfluxDB
if [ ! -f /usr/share/keyrings/influxdata-archive-keyring.gpg ]; then
    curl -fsSL https://repos.influxdata.com/influxdata-archive.key \
        | gpg --dearmor \
        | tee /usr/share/keyrings/influxdata-archive-keyring.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/influxdata-archive-keyring.gpg] https://repos.influxdata.com/debian stable main" \
        | tee /etc/apt/sources.list.d/influxdata.list > /dev/null
fi

# Grafana
if [ ! -f /etc/apt/sources.list.d/grafana.list ]; then
    apt-get install -y -qq apt-transport-https software-properties-common > /dev/null
    curl -fsSL https://packages.grafana.com/gpg.key | gpg --dearmor \
        | tee /usr/share/keyrings/grafana-archive-keyring.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/grafana-archive-keyring.gpg] https://packages.grafana.com/oss/deb stable main" \
        | tee /etc/apt/sources.list.d/grafana.list > /dev/null
fi

# Kismet repo — disable if present (breaks apt on arm64 / unsupported releases)
if ls /etc/apt/sources.list.d/kismet*.list 2>/dev/null; then
    sed -i 's/^deb /# deb /' /etc/apt/sources.list.d/kismet*.list
fi

apt-get update -qq
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 4 "APT repositories"


_nk_step_start 5 "Base dependencies"
{
    # Preseed wireshark so tshark install doesn't prompt
    echo "wireshark-common wireshark-common/install-setuid boolean true" \
        | debconf-set-selections

    # Always install Kismet — the wlan1-specific configuration in step 16
    # is conditional, but the kismet package must be present regardless
    # so that modules activate automatically when an MT7921AU is plugged
    # in later (hw_caps.json is re-read at service start).
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq kismet || true
} >> "$INSTALL_LOG" 2>&1

PKGS=(
    python3 python3-venv python3-pip python3-dev
    git curl wget unzip jq
    dnsmasq
    cockpit
    influxdb2
    grafana
    tshark
    picocom minicom
    i2c-tools
    network-manager
    avahi-daemon
    ttyd
    openssl
    libcap2-bin
)
PKG_COUNT=${#PKGS[@]}
PKG_IDX=0

for pkg in "${PKGS[@]}"; do
    PKG_IDX=$((PKG_IDX + 1))
    _nk_pkg_progress "$pkg" "$PKG_IDX" "$PKG_COUNT"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$pkg" >> "$INSTALL_LOG" 2>&1 \
        || echo "WARN: failed to install $pkg" >> "$INSTALL_LOG"
done

_nk_step_done 5 "Base dependencies"


_nk_step_start 6 "User groups"
{
usermod -a -G dialout   "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G wireshark "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G netdev    "$NEKOPI_USER" 2>/dev/null || true
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 6 "User groups"


_nk_step_start 7 "Clone / update repo"
{
if [ -d "$NEKOPI_DIR/.git" ]; then
    cd "$NEKOPI_DIR"
    sudo -u "$NEKOPI_USER" git fetch origin
    sudo -u "$NEKOPI_USER" git reset --hard "origin/$REPO_BRANCH"
else
    TMP_CLONE=$(mktemp -d)
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$TMP_CLONE"
    cp -a "$TMP_CLONE/." "$NEKOPI_DIR/"
    rm -rf "$TMP_CLONE"
    chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
fi
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 7 "Clone / update repo"


_nk_step_start 8 "Python venv + pip deps"
{
if [ ! -d "$NEKOPI_DIR/venv" ]; then
    sudo -u "$NEKOPI_USER" python3 -m venv "$NEKOPI_DIR/venv"
fi
sudo -u "$NEKOPI_USER" "$NEKOPI_DIR/venv/bin/pip" install --upgrade pip -q
if [ -f "$NEKOPI_DIR/requirements.txt" ]; then
    sudo -u "$NEKOPI_USER" "$NEKOPI_DIR/venv/bin/pip" install -r "$NEKOPI_DIR/requirements.txt" -q
else
    sudo -u "$NEKOPI_USER" "$NEKOPI_DIR/venv/bin/pip" install -q \
        fastapi==0.111.0 \
        uvicorn==0.29.0 \
        uvloop==0.22.1 \
        httpx==0.27.0 \
        psutil==5.9.8 \
        paramiko==4.0.0 \
        pyserial==3.5 \
        influxdb-client==1.50.0 \
        websockets==16.0 \
        webssh==1.6.3 \
        weasyprint==68.1 \
        pyyaml==6.0.3 \
        dnspython==2.8.0 \
        bcrypt==5.0.0 \
        orjson==3.11.8 \
        aiofiles==23.2.1 \
        pillow==12.2.0 \
        python-dotenv==1.2.2 \
        python-multipart==0.0.24
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 8 "Python venv + pip deps"


_nk_step_start 9 "SSL certificate"
{
if [ ! -f "$NEKOPI_DIR/ssl/cert.pem" ]; then
    openssl req -x509 -newkey rsa:4096 \
        -keyout "$NEKOPI_DIR/ssl/key.pem" \
        -out "$NEKOPI_DIR/ssl/cert.pem" \
        -days 3650 -nodes \
        -subj "/CN=nekopi.local" 2>/dev/null
    chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/ssl"
    chmod 600 "$NEKOPI_DIR/ssl/key.pem"
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 9 "SSL certificate"


_nk_step_start 10 "systemd service"
{
cat > /etc/systemd/system/nekopi.service << 'UNIT'
[Unit]
Description=NekoPi Field Unit — API & Frontend (HTTPS)
After=network.target
Wants=network-online.target avahi-daemon.service

[Service]
Type=simple
User=nekopi
WorkingDirectory=/opt/nekopi
ExecStart=/opt/nekopi/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8080 --workers 1 --ssl-keyfile /opt/nekopi/ssl/key.pem --ssl-certfile /opt/nekopi/ssl/cert.pem
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nekopi
Environment=PYTHONPATH=/opt/nekopi
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN

[Install]
WantedBy=multi-user.target
UNIT

sed -i 's/^    //' /etc/systemd/system/nekopi.service

systemctl daemon-reload
systemctl enable nekopi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 10 "systemd service"


_nk_step_start 11 "Netplan (eth-mgmt / eth-test)"
{
# Remove legacy name-based netplan if present
if [ -f /etc/netplan/01-nekopi.yaml ]; then
    rm -f /etc/netplan/01-nekopi.yaml
fi

cat > /etc/netplan/01-nekopi-mgmt.yaml << 'NETPLAN'
network:
  version: 2
  renderer: networkd
  ethernets:
    mgmt:
      match:
        driver: bcmgenet
      set-name: eth-mgmt
      dhcp4: false
      optional: true
      addresses: [192.168.99.1/24]
    test:
      match:
        driver: r8169
      set-name: eth-test
      dhcp4: true
      optional: true
NETPLAN

sed -i 's/^    //' /etc/netplan/01-nekopi-mgmt.yaml
chmod 600 /etc/netplan/01-nekopi-mgmt.yaml
netplan apply 2>/dev/null || true
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 11 "Netplan (eth-mgmt / eth-test)"


_nk_step_start 12 "dnsmasq + systemd-resolved fix"
{
# Free port 53 from systemd-resolved stub listener
if [ -f /etc/systemd/resolved.conf ]; then
    if ! grep -q "^DNSStubListener=no" /etc/systemd/resolved.conf; then
        sed -i 's/^#\?DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf
        systemctl restart systemd-resolved 2>/dev/null || true
        [ -L /etc/resolv.conf ] || ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
    fi
fi

DNSMASQ_IFACE="eth-mgmt"
if ! ip link show eth-mgmt &>/dev/null; then
    if [ -n "${MGMT_IFACE:-}" ]; then
        DNSMASQ_IFACE="$MGMT_IFACE"
    else
        DNSMASQ_IFACE="eth1"
    fi
fi

cat > /etc/dnsmasq.conf << DNSMASQ
interface=$DNSMASQ_IFACE
bind-interfaces
except-interface=lo
dhcp-range=192.168.99.100,192.168.99.199,255.255.255.0,12h
dhcp-option=3,192.168.99.1
dhcp-option=6,192.168.99.1
server=8.8.8.8
server=8.8.4.4
DNSMASQ

mkdir -p /etc/systemd/system/dnsmasq.service.d/
cat > /etc/systemd/system/dnsmasq.service.d/wait-mgmt.conf << OVERRIDE
[Unit]
After=network-online.target sys-subsystem-net-devices-$DNSMASQ_IFACE.device
Wants=sys-subsystem-net-devices-$DNSMASQ_IFACE.device
OVERRIDE

mkdir -p /etc/dnsmasq.d
systemctl daemon-reload
systemctl enable dnsmasq
systemctl restart dnsmasq 2>/dev/null || true
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 12 "dnsmasq + systemd-resolved fix"


_nk_step_start 13 "InfluxDB setup"
{
if [ -f "$NEKOPI_DIR/data/influx-token.txt" ]; then
    :  # already configured
else
    systemctl start influxdb
    sleep 5
    READY=0
    for i in $(seq 1 40); do
        if influx ping &>/dev/null; then READY=1; break; fi
        sleep 1
    done

    SETUP_OK=0
    for attempt in 1 2 3; do
        if influx setup \
            --username nekopi \
            --password nekopi2024 \
            --org nekopi \
            --bucket nekopi \
            --retention 30d \
            --force 2>/dev/null; then
            SETUP_OK=1; break
        fi
        sleep 3
    done

    TOKEN=$(influx auth list --json 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['token'])" 2>/dev/null || echo "")
    if [ -n "$TOKEN" ]; then
        echo "$TOKEN" > "$NEKOPI_DIR/data/influx-token.txt"
        chmod 600 "$NEKOPI_DIR/data/influx-token.txt"
        chown "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data/influx-token.txt"
    fi
fi

# On-demand only — no auto-start
systemctl disable influxdb 2>/dev/null || true
systemctl stop influxdb 2>/dev/null || true
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 13 "InfluxDB setup"


_nk_step_start 14 "Grafana (on-demand)"
{
systemctl disable grafana-server 2>/dev/null || true
systemctl stop grafana-server 2>/dev/null || true
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 14 "Grafana (on-demand)"


_nk_step_start 15 "Cockpit"
{
mkdir -p /etc/cockpit
cat > /etc/cockpit/cockpit.conf << 'COCKPIT'
[WebService]
AllowUnencrypted=true
Origins=*
COCKPIT
systemctl enable --now cockpit.socket
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 15 "Cockpit"


_nk_step_start 16 "Kismet config"
{
# Always: log output path and capture dir. These work with or without
# wlan1 — if wlan1 shows up later (hot-plug), Kismet will find it
# via sources configured below OR via its own auto-detect.
mkdir -p /etc/kismet /opt/nekopi/captures/kismet
cat > /etc/kismet/kismet_site.conf << 'KISMET_CFG'
log_prefix=/opt/nekopi/captures/kismet/Kismet
KISMET_CFG
sed -i 's/^    //' /etc/kismet/kismet_site.conf

# Conditional: monitor-mode source line (requires wlan1 adapter present
# at install time). If wlan1 is absent now, we leave the source list
# empty — the backend will regenerate kismet_site.conf when wlan1 is
# detected at runtime.
if [ "$HAS_WLAN1" = "yes" ]; then
    echo "source=wlan1" >> /etc/kismet/kismet_site.conf
else
    echo "NOTE: wlan1 not detected — skipping wlan1-specific source config"
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 16 "Kismet config"


_nk_step_start 17 "Sudoers"
{
cat > /etc/sudoers.d/nekopi-services << 'SUDOERS'
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl start influxdb
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop influxdb
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl start grafana-server
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop grafana-server
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl start cockpit
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop cockpit
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl start kismet
nekopi ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop kismet
nekopi ALL=(ALL) NOPASSWD: /usr/bin/iw
nekopi ALL=(ALL) NOPASSWD: /usr/bin/ip
nekopi ALL=(ALL) NOPASSWD: /usr/sbin/tcpdump
nekopi ALL=(ALL) NOPASSWD: /usr/bin/tshark
nekopi ALL=(ALL) NOPASSWD: /usr/bin/airodump-ng
nekopi ALL=(ALL) NOPASSWD: /usr/bin/airmon-ng
SUDOERS

chmod 440 /etc/sudoers.d/nekopi-services
visudo -c -f /etc/sudoers.d/nekopi-services || { rm -f /etc/sudoers.d/nekopi-services; false; }
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 17 "Sudoers"


_nk_step_start 18 "pktvisor"
{
if [ ! -f "$NEKOPI_DIR/bin/pktvisord" ]; then
    PKTVISOR_URL="https://github.com/ns1labs/pktvisor/releases/latest/download/pktvisor-linux-arm64.zip"
    if wget -q --spider "$PKTVISOR_URL" 2>/dev/null; then
        wget -q -O /tmp/pktvisor.zip "$PKTVISOR_URL"
        unzip -qo /tmp/pktvisor.zip -d /tmp/pktvisor
        mkdir -p "$NEKOPI_DIR/bin"
        cp /tmp/pktvisor/bin/* "$NEKOPI_DIR/bin/" 2>/dev/null || cp /tmp/pktvisor/* "$NEKOPI_DIR/bin/" 2>/dev/null
        chmod +x "$NEKOPI_DIR/bin/pktvisord"
        rm -rf /tmp/pktvisor /tmp/pktvisor.zip
    fi
fi

if [ -f "$NEKOPI_DIR/bin/pktvisord" ]; then
    setcap cap_net_raw,cap_net_admin=eip "$NEKOPI_DIR/bin/pktvisord" 2>/dev/null || true
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 18 "pktvisor"


_nk_step_start 19 "Data files"
{
if [ ! -f "$NEKOPI_DIR/data/dhcp-options.json" ]; then
    echo '{"options": []}' > "$NEKOPI_DIR/data/dhcp-options.json"
    chown "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data/dhcp-options.json"
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 19 "Data files"


_nk_step_start 20 ".gitignore"
{
cat > "$NEKOPI_DIR/.gitignore" << 'GITIGNORE'
*.kismet
*.kismet-journal
captures/
logs/
ssl/
data/
reports/
*.tmp
*.bak
__pycache__/
*.pyc
venv/
ui/assets/ota/
GITIGNORE
chown "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/.gitignore"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 20 ".gitignore"


_nk_step_start 21 "Final ownership"
{
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 21 "Final ownership"


_nk_step_start 22 "Assets check"
{
[ -f "$NEKOPI_DIR/ui/assets/nekopi-logo-about.png" ] \
    || echo "WARN: missing ui/assets/nekopi-logo-about.png"
[ -f "$NEKOPI_DIR/ui/assets/nekopi-logo-dark.png" ] \
    || echo "WARN: missing ui/assets/nekopi-logo-dark.png"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 22 "Assets check"


_nk_step_start 23 "Start services"
{
systemctl restart nekopi
sleep 3
READY=0
for i in $(seq 1 15); do
    if curl -ks "https://127.0.0.1:$NEKOPI_PORT/api/health" &>/dev/null; then
        READY=1; break
    fi
    sleep 1
done
if [ "$READY" != "1" ]; then
    echo "WARN: NekoPi did not respond yet — check journalctl -u nekopi -f"
fi
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 23 "Start services"


_nk_step_start 24 "Post-install verification"
{
INSTALL_ERRORS=0

check() {
    local label="$1"; local cmd="$2"
    if eval "$cmd" &>/dev/null; then
        echo "  ✔  $label"
    else
        echo "  ✗  $label"
        INSTALL_ERRORS=$((INSTALL_ERRORS + 1))
    fi
}

check "systemd service nekopi"        "systemctl is-active --quiet nekopi"
check "dnsmasq active"                "systemctl is-active --quiet dnsmasq"
check "cockpit socket active"         "systemctl is-active --quiet cockpit.socket"
check "Port $NEKOPI_PORT listening"   "ss -tlnp | grep -q ':$NEKOPI_PORT'"
check "API /api/health responds"      "curl -sk https://127.0.0.1:$NEKOPI_PORT/api/health"
check "API /api/hw-caps responds"     "curl -sk https://127.0.0.1:$NEKOPI_PORT/api/hw-caps"
check "hw_caps.json exists"           "test -f $NEKOPI_DIR/data/hw_caps.json"
check "Data directory"                "test -d $NEKOPI_DIR/data"
check "SSL certificate"               "test -f $NEKOPI_DIR/ssl/cert.pem"
check "InfluxDB token"                "test -f $NEKOPI_DIR/data/influx-token.txt"
check "DHCP options file"             "test -f $NEKOPI_DIR/data/dhcp-options.json"
check "UI index.html"                 "test -f $NEKOPI_DIR/ui/index.html"
check "Python fastapi/uvicorn"        "$NEKOPI_DIR/venv/bin/python3 -c 'import fastapi, uvicorn'"
check "ttyd binary"                   "command -v ttyd"
check "tshark binary"                 "command -v tshark"
check "kismet binary"                 "command -v kismet"
check "Group: dialout"                "groups $NEKOPI_USER | grep -q dialout"
check "Group: wireshark"              "groups $NEKOPI_USER | grep -q wireshark"

if [ "$HAS_ETH_MGMT" = "yes" ]; then
    check "MGMT iface has 192.168.99.1" "ip addr show | grep -q 192.168.99.1"
fi

if [ "$HAS_WLAN1" = "yes" ]; then
    check "wlan1 monitor mode capable" "iw phy | grep -q 'monitor\|managed'"
fi

echo "INSTALL_ERRORS=$INSTALL_ERRORS"
} >> "$INSTALL_LOG" 2>&1
_nk_step_done 24 "Post-install verification"


# Overall progress bar — printed once at the end, not between steps
_nk_overall_progress

_nk_section "completed"

echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  Installation complete${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

# Completed steps
for entry in "${NEKOPI_COMPLETED[@]}"; do
    IFS=':' read -r num label secs <<< "$entry"
    printf '  %b✔%b  [%2s]  %-40s %ds\n' \
        "$GREEN" "$RESET" "$num" "$label" "$secs"
done

# Skipped steps, if any
if [ ${#NEKOPI_SKIPPED[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${YELLOW}Skipped (hardware not available):${RESET}"
    for entry in "${NEKOPI_SKIPPED[@]}"; do
        IFS=':' read -r num label reason <<< "$entry"
        printf '  %b–%b  [%2s]  %-40s (%s)\n' \
            "$YELLOW" "$RESET" "$num" "$label" "$reason"
    done
fi

TOTAL_TIME=$(( $(date +%s) - NEKOPI_START_TIME ))
echo ""
printf '  Total time: %dm %ds\n' "$((TOTAL_TIME/60))" "$((TOTAL_TIME%60))"
printf '  Access:     %bhttps://%s:%s%b\n' \
    "$CYAN" "$(hostname -I | awk '{print $1}')" "$NEKOPI_PORT" "$RESET"
printf '  Install log: %s\n' "$INSTALL_LOG"
echo ""
