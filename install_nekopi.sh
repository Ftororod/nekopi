#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  NekoPi Field Unit — Automated Installer v2
#  Version:   1.3.0  ·  Codename: ToManchas
#  Generated: 2026-04-16 14:24
#  Target:    Ubuntu 24.04 LTS · Raspberry Pi 5 · 8 GB
#  License:   GPL-3.0-or-later
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

NEKOPI_DIR="/opt/nekopi"
NEKOPI_USER="nekopi"
NEKOPI_PORT=8080
REPO_URL="https://github.com/Ftororod/nekopi.git"
REPO_BRANCH="main"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
fail() { echo -e "${RED}❌ $1${NC}"; }
info() { echo -e "${CYAN}▶  $1${NC}"; }

# Must be root
if [[ $EUID -ne 0 ]]; then
    fail "This script must be run as root (sudo)"
    exit 1
fi

STARTED_AT=$(date +%s)


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  0 · HARDWARE DETECTION"
echo "════════════════════════════════════════════════════════════"
info "Detecting available hardware…"

HAS_WLAN0="no"; HAS_WLAN1="no"; HAS_ETH0="no"; HAS_ETH1="no"
HAS_ETH_MGMT="no"; HAS_ETH_TEST="no"
MGMT_IFACE=""; TEST_IFACE=""

detect_iface() {
    local name="$1"
    ip link show "$name" &>/dev/null && echo "yes" || echo "no"
}

# Detect kernel interface names
HAS_WLAN0=$(detect_iface wlan0)
HAS_WLAN1=$(detect_iface wlan1)
HAS_ETH0=$(detect_iface eth0)
HAS_ETH1=$(detect_iface eth1)

# Detect by driver — this is stable across HAT present/absent
for iface in $(ls /sys/class/net/ 2>/dev/null); do
    [ "$iface" = "lo" ] && continue
    [ -L "/sys/class/net/$iface/device/driver" ] || continue
    driver=$(basename "$(readlink -f /sys/class/net/$iface/device/driver)")
    case "$driver" in
        bcmgenet|macb)  HAS_ETH_MGMT="yes"; MGMT_IFACE="$iface" ;;
        r8169|r8125)    HAS_ETH_TEST="yes"; TEST_IFACE="$iface" ;;
    esac
done

# Fallbacks if no driver match (generic server / VM)
[ -z "$MGMT_IFACE" ] && [ "$HAS_ETH1" = "yes" ] && MGMT_IFACE="eth1"
[ -z "$MGMT_IFACE" ] && [ "$HAS_ETH0" = "yes" ] && MGMT_IFACE="eth0"
[ -z "$TEST_IFACE" ] && [ "$HAS_ETH0" = "yes" ] && TEST_IFACE="eth0"

echo "  wlan0 (built-in WiFi):   $HAS_WLAN0"
echo "  wlan1 (USB monitor adp): $HAS_WLAN1"
echo "  eth0  (kernel name):     $HAS_ETH0"
echo "  eth1  (kernel name):     $HAS_ETH1"
echo "  mgmt  (driver-matched):  $HAS_ETH_MGMT ($MGMT_IFACE)"
echo "  test  (driver-matched):  $HAS_ETH_TEST ($TEST_IFACE)"

# Write capabilities file so the backend can gate UI modules
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
ok "Hardware capabilities written to $NEKOPI_DIR/data/hw_caps.json"

# Export for rest of the script
export HAS_WLAN0 HAS_WLAN1 HAS_ETH0 HAS_ETH1 HAS_ETH_MGMT HAS_ETH_TEST
export MGMT_IFACE TEST_IFACE


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  1 · USER"
echo "════════════════════════════════════════════════════════════"
info "Creating user $NEKOPI_USER (if missing)…"
if ! id "$NEKOPI_USER" &>/dev/null; then
    adduser --disabled-password --gecos "NekoPi" "$NEKOPI_USER"
    ok "User $NEKOPI_USER created"
else
    ok "User $NEKOPI_USER already exists"
fi


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  2 · DIRECTORIES"
echo "════════════════════════════════════════════════════════════"
info "Creating directory tree…"
mkdir -p "$NEKOPI_DIR"/{api,bin,captures/kismet,captures/ota,data,logs,oled,reports,ssl,tftp,ui/assets}
mkdir -p /srv/tftp
chmod 777 /srv/tftp
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
# Ensure data dir is writable by nekopi for hw_caps.json, tokens, etc.
chmod 755 "$NEKOPI_DIR/data"
ok "Directories ready"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  3 · APT REPOSITORIES"
echo "════════════════════════════════════════════════════════════"
info "Configuring third-party repositories…"

# InfluxDB
if [ ! -f /usr/share/keyrings/influxdata-archive-keyring.gpg ]; then
    curl -fsSL https://repos.influxdata.com/influxdata-archive.key \
        | gpg --dearmor \
        | tee /usr/share/keyrings/influxdata-archive-keyring.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/influxdata-archive-keyring.gpg] https://repos.influxdata.com/debian stable main" \
        | tee /etc/apt/sources.list.d/influxdata.list > /dev/null
    ok "InfluxDB repo added"
else
    ok "InfluxDB repo already present"
fi

# Grafana
if [ ! -f /etc/apt/sources.list.d/grafana.list ]; then
    apt-get install -y -qq apt-transport-https software-properties-common > /dev/null
    curl -fsSL https://packages.grafana.com/gpg.key | gpg --dearmor \
        | tee /usr/share/keyrings/grafana-archive-keyring.gpg > /dev/null
    echo "deb [signed-by=/usr/share/keyrings/grafana-archive-keyring.gpg] https://packages.grafana.com/oss/deb stable main" \
        | tee /etc/apt/sources.list.d/grafana.list > /dev/null
    ok "Grafana repo added"
else
    ok "Grafana repo already present"
fi

# Disable Kismet repo if present (breaks apt on arm64 / unsupported releases)
if ls /etc/apt/sources.list.d/kismet*.list 2>/dev/null; then
    sed -i 's/^deb /# deb /' /etc/apt/sources.list.d/kismet*.list
    warn "Kismet repo disabled to avoid apt conflicts"
fi

apt-get update -qq
ok "Package lists updated"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  4 · BASE DEPENDENCIES"
echo "════════════════════════════════════════════════════════════"
info "Installing system packages…"

# tshark needs non-interactive debconf so it doesn't prompt
echo "wireshark-common wireshark-common/install-setuid boolean true" \
    | debconf-set-selections

DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    git curl wget unzip jq \
    dnsmasq \
    cockpit \
    influxdb2 \
    grafana \
    tshark \
    picocom minicom \
    i2c-tools \
    network-manager \
    avahi-daemon \
    ttyd \
    openssl \
    libcap2-bin \
    > /dev/null 2>&1 || {
        # Retry without -qq on failure so we see the error
        warn "Silent install failed — retrying with verbose output…"
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            python3 python3-venv python3-pip python3-dev \
            git curl wget unzip jq \
            dnsmasq \
            cockpit \
            influxdb2 \
            grafana \
            tshark \
            picocom minicom \
            i2c-tools \
            network-manager \
            avahi-daemon \
            ttyd \
            openssl \
            libcap2-bin
    }
ok "System packages installed"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  5 · USER GROUPS"
echo "════════════════════════════════════════════════════════════"
info "Adding $NEKOPI_USER to required groups…"
usermod -a -G dialout   "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G wireshark "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G netdev    "$NEKOPI_USER" 2>/dev/null || true
ok "Groups: dialout, wireshark, netdev"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  6 · CLONE / UPDATE REPO"
echo "════════════════════════════════════════════════════════════"
info "Setting up NekoPi source code…"
if [ -d "$NEKOPI_DIR/.git" ]; then
    cd "$NEKOPI_DIR"
    sudo -u "$NEKOPI_USER" git fetch origin
    sudo -u "$NEKOPI_USER" git reset --hard "origin/$REPO_BRANCH"
    ok "Repo updated to latest $REPO_BRANCH"
else
    # Clone into temp then move contents (dir already has data/)
    TMP_CLONE=$(mktemp -d)
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$TMP_CLONE"
    cp -a "$TMP_CLONE/." "$NEKOPI_DIR/"
    rm -rf "$TMP_CLONE"
    chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
    ok "Repo cloned into $NEKOPI_DIR"
fi

# Make sure data dir (with hw_caps.json written in step 0) is preserved
# and owned correctly after the clone/reset.
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  7 · PYTHON VIRTUAL ENVIRONMENT"
echo "════════════════════════════════════════════════════════════"
info "Setting up Python venv…"
if [ ! -d "$NEKOPI_DIR/venv" ]; then
    sudo -u "$NEKOPI_USER" python3 -m venv "$NEKOPI_DIR/venv"
    ok "Venv created"
else
    ok "Venv already exists"
fi

info "Installing Python dependencies (venv pip — no --break-system-packages needed)…"
sudo -u "$NEKOPI_USER" "$NEKOPI_DIR/venv/bin/pip" install --upgrade pip -q
if [ -f "$NEKOPI_DIR/requirements.txt" ]; then
    sudo -u "$NEKOPI_USER" "$NEKOPI_DIR/venv/bin/pip" install -r "$NEKOPI_DIR/requirements.txt" -q
else
    # Fallback: install known dependencies
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
ok "Python dependencies installed"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  8 · SSL CERTIFICATE"
echo "════════════════════════════════════════════════════════════"
info "Generating self-signed SSL certificate…"
if [ ! -f "$NEKOPI_DIR/ssl/cert.pem" ]; then
    openssl req -x509 -newkey rsa:4096 \
        -keyout "$NEKOPI_DIR/ssl/key.pem" \
        -out "$NEKOPI_DIR/ssl/cert.pem" \
        -days 3650 -nodes \
        -subj "/CN=nekopi.local" 2>/dev/null
    chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/ssl"
    chmod 600 "$NEKOPI_DIR/ssl/key.pem"
    ok "SSL certificate generated (10 years)"
else
    ok "SSL certificate already exists"
fi


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  9 · SYSTEMD SERVICE"
echo "════════════════════════════════════════════════════════════"
info "Installing nekopi.service…"
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

# Remove leading whitespace from heredoc
sed -i 's/^    //' /etc/systemd/system/nekopi.service

systemctl daemon-reload
systemctl enable nekopi
ok "nekopi.service installed and enabled"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  10 · NETPLAN — DRIVER-MATCHED INTERFACES"
echo "════════════════════════════════════════════════════════════"
info "Configuring netplan (driver-based match, name-agnostic)…"

# On RPi5 the kernel names interfaces by PCIe enumeration order:
#   - With HAT attached:    eth0=HAT(r8169)         eth1=native(bcmgenet)
#   - Without HAT:          eth0=native(bcmgenet)   (no eth1)
# Matching by driver instead of name means dnsmasq/backend never point
# at a missing interface when the HAT is removed.

# Remove legacy name-based netplan if present (from older installs)
if [ -f /etc/netplan/01-nekopi.yaml ]; then
    rm -f /etc/netplan/01-nekopi.yaml
    info "Removed legacy /etc/netplan/01-nekopi.yaml (replaced by driver-matched config)"
fi

cat > /etc/netplan/01-nekopi-mgmt.yaml << 'NETPLAN'
network:
  version: 2
  renderer: networkd
  ethernets:
    mgmt:
      match:
        driver: bcmgenet         # RPi5 native NIC (always present)
      set-name: eth-mgmt
      dhcp4: false
      optional: true
      addresses: [192.168.99.1/24]
    test:
      match:
        driver: r8169            # RTL8125B 2.5GbE HAT (only when present)
      set-name: eth-test
      dhcp4: true
      optional: true             # Don't block boot when HAT is absent
NETPLAN

sed -i 's/^    //' /etc/netplan/01-nekopi-mgmt.yaml
chmod 600 /etc/netplan/01-nekopi-mgmt.yaml

# Apply — if eth-mgmt already exists with expected IP we still want to re-apply
netplan apply 2>/dev/null \
    || warn "netplan apply failed (interfaces may not be present yet — normal on generic Linux)"
ok "Netplan configured (eth-mgmt=bcmgenet, eth-test=r8169)"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  11 · DNSMASQ — DHCP FOR MGMT"
echo "════════════════════════════════════════════════════════════"
info "Configuring dnsmasq for management network…"

# Free port 53 before dnsmasq starts: Ubuntu ships systemd-resolved
# listening on 127.0.0.53:53 by default, which collides with dnsmasq.
if [ -f /etc/systemd/resolved.conf ]; then
    if ! grep -q "^DNSStubListener=no" /etc/systemd/resolved.conf; then
        sed -i 's/^#\?DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf
        systemctl restart systemd-resolved 2>/dev/null || true
        # Make sure /etc/resolv.conf points to a valid resolver
        [ -L /etc/resolv.conf ] || ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
        ok "systemd-resolved stub listener disabled (port 53 freed for dnsmasq)"
    fi
fi

# dnsmasq binds to eth-mgmt (set by netplan via driver match).
# Fallback: if eth-mgmt doesn't exist at install time, fall back to $MGMT_IFACE
# detected in step 0, or eth1 as last resort.
DNSMASQ_IFACE="eth-mgmt"
if ! ip link show eth-mgmt &>/dev/null; then
    if [ -n "${MGMT_IFACE:-}" ]; then
        DNSMASQ_IFACE="$MGMT_IFACE"
        warn "eth-mgmt not present — dnsmasq will bind $MGMT_IFACE (fallback)"
    else
        DNSMASQ_IFACE="eth1"
        warn "No mgmt interface detected — dnsmasq will bind eth1 (may fail)"
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

# Wait for the mgmt interface before starting dnsmasq
mkdir -p /etc/systemd/system/dnsmasq.service.d/
cat > /etc/systemd/system/dnsmasq.service.d/wait-mgmt.conf << OVERRIDE
[Unit]
After=network-online.target sys-subsystem-net-devices-$DNSMASQ_IFACE.device
Wants=sys-subsystem-net-devices-$DNSMASQ_IFACE.device
OVERRIDE

mkdir -p /etc/dnsmasq.d

systemctl daemon-reload
systemctl enable dnsmasq
systemctl restart dnsmasq 2>/dev/null || warn "dnsmasq restart failed ($DNSMASQ_IFACE may not be up)"
ok "dnsmasq configured on $DNSMASQ_IFACE"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  12 · INFLUXDB — INITIAL SETUP"
echo "════════════════════════════════════════════════════════════"
info "Setting up InfluxDB…"
if [ -f "$NEKOPI_DIR/data/influx-token.txt" ]; then
    ok "InfluxDB already configured (token exists)"
else
    systemctl start influxdb
    info "Waiting for InfluxDB to start (up to 45s)…"
    # Give service time to open its socket
    sleep 5
    READY=0
    for i in $(seq 1 40); do
        if influx ping &>/dev/null; then READY=1; break; fi
        sleep 1
    done

    if [ "$READY" != "1" ]; then
        warn "InfluxDB did not become ready — retrying setup anyway"
    fi

    # Retry setup a few times — first attempt can race with service init
    SETUP_OK=0
    for attempt in 1 2 3; do
        if influx setup \
            --username nekopi \
            --password nekopi2024 \
            --org nekopi \
            --bucket nekopi \
            --retention 30d \
            --force 2>/dev/null; then
            SETUP_OK=1
            break
        fi
        sleep 3
    done
    [ "$SETUP_OK" = "1" ] \
        && ok "InfluxDB initial setup done" \
        || warn "InfluxDB setup may already exist or service not ready"

    # Save token
    TOKEN=$(influx auth list --json 2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['token'])" 2>/dev/null || echo "")
    if [ -n "$TOKEN" ]; then
        echo "$TOKEN" > "$NEKOPI_DIR/data/influx-token.txt"
        chmod 600 "$NEKOPI_DIR/data/influx-token.txt"
        chown "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data/influx-token.txt"
        ok "InfluxDB token saved"
    else
        warn "Could not retrieve InfluxDB token — configure manually"
    fi
fi

# Disable auto-start (on-demand via NekoPi API)
systemctl disable influxdb 2>/dev/null || true
systemctl stop influxdb 2>/dev/null || true
ok "InfluxDB disabled (on-demand)"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  13 · GRAFANA"
echo "════════════════════════════════════════════════════════════"
info "Configuring Grafana (on-demand)…"
systemctl disable grafana-server 2>/dev/null || true
systemctl stop grafana-server 2>/dev/null || true
ok "Grafana disabled (on-demand, datasource auto-configured by NekoPi)"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  14 · COCKPIT — IFRAME EMBED"
echo "════════════════════════════════════════════════════════════"
info "Configuring Cockpit for iframe embedding…"
mkdir -p /etc/cockpit
cat > /etc/cockpit/cockpit.conf << 'COCKPIT'
[WebService]
AllowUnencrypted=true
Origins=*
COCKPIT

systemctl enable --now cockpit.socket
ok "Cockpit configured and enabled"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  15 · KISMET — LOG DIRECTORY"
echo "════════════════════════════════════════════════════════════"
info "Configuring Kismet log directory…"
mkdir -p /etc/kismet
cat > /etc/kismet/kismet_site.conf << 'KISMET'
log_prefix=/opt/nekopi/captures/kismet/Kismet
KISMET
ok "Kismet logs → $NEKOPI_DIR/captures/kismet/"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  16 · SUDOERS — SERVICE CONTROL"
echo "════════════════════════════════════════════════════════════"
info "Configuring passwordless sudo for NekoPi services…"
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
visudo -c -f /etc/sudoers.d/nekopi-services && ok "Sudoers validated" \
    || { fail "Sudoers syntax error!"; rm -f /etc/sudoers.d/nekopi-services; }


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  17 · PKTVISOR"
echo "════════════════════════════════════════════════════════════"
info "Checking pktvisor…"
if [ -f "$NEKOPI_DIR/bin/pktvisord" ]; then
    ok "pktvisord already present"
else
    PKTVISOR_URL="https://github.com/ns1labs/pktvisor/releases/latest/download/pktvisor-linux-arm64.zip"
    if wget -q --spider "$PKTVISOR_URL" 2>/dev/null; then
        wget -q -O /tmp/pktvisor.zip "$PKTVISOR_URL"
        unzip -qo /tmp/pktvisor.zip -d /tmp/pktvisor
        mkdir -p "$NEKOPI_DIR/bin"
        cp /tmp/pktvisor/bin/* "$NEKOPI_DIR/bin/" 2>/dev/null || cp /tmp/pktvisor/* "$NEKOPI_DIR/bin/" 2>/dev/null
        chmod +x "$NEKOPI_DIR/bin/pktvisord"
        rm -rf /tmp/pktvisor /tmp/pktvisor.zip
        ok "pktvisord downloaded"
    else
        warn "pktvisor download URL not reachable — skip (install manually)"
    fi
fi

# CAP_NET_RAW for capture without sudo
if [ -f "$NEKOPI_DIR/bin/pktvisord" ]; then
    setcap cap_net_raw,cap_net_admin=eip "$NEKOPI_DIR/bin/pktvisord" 2>/dev/null || true
    ok "pktvisord capabilities set"
fi


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  18 · OLLAMA — LOCAL AI"
echo "════════════════════════════════════════════════════════════"
info "Installing Ollama…"
if command -v ollama &>/dev/null; then
    ok "Ollama already installed"
else
    curl -fsSL https://ollama.ai/install.sh | sh
    ok "Ollama installed"
fi

systemctl enable ollama 2>/dev/null || true
systemctl start ollama 2>/dev/null || true

# Pull base model in background (won't block installer)
info "Pulling mistral model in background…"
nohup ollama pull mistral > /dev/null 2>&1 &
ok "Ollama running — model download in background"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  19 · DATA FILES"
echo "════════════════════════════════════════════════════════════"
info "Creating initial data files…"
if [ ! -f "$NEKOPI_DIR/data/dhcp-options.json" ]; then
    echo '{"options": []}' > "$NEKOPI_DIR/data/dhcp-options.json"
    chown "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR/data/dhcp-options.json"
    ok "dhcp-options.json created"
else
    ok "dhcp-options.json already exists"
fi


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  20 · GITIGNORE"
echo "════════════════════════════════════════════════════════════"
info "Writing .gitignore…"
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
ok ".gitignore written"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  21 · FINAL OWNERSHIP"
echo "════════════════════════════════════════════════════════════"
info "Fixing ownership on $NEKOPI_DIR…"
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
ok "Ownership set to $NEKOPI_USER"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  22 · ASSETS CHECK"
echo "════════════════════════════════════════════════════════════"
info "Checking UI assets…"
[ -f "$NEKOPI_DIR/ui/assets/nekopi-logo-about.png" ] \
    && ok "Logo about OK" \
    || warn "Logo about MISSING — copy to $NEKOPI_DIR/ui/assets/nekopi-logo-about.png"
[ -f "$NEKOPI_DIR/ui/assets/nekopi-logo-dark.png" ] \
    && ok "Logo dark OK" \
    || warn "Logo dark MISSING — copy to $NEKOPI_DIR/ui/assets/nekopi-logo-dark.png"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  23 · START SERVICES"
echo "════════════════════════════════════════════════════════════"
info "Starting NekoPi…"
systemctl restart nekopi
sleep 3

# Wait up to 15s for NekoPi to respond
READY=0
for i in $(seq 1 15); do
    if curl -ks "https://127.0.0.1:$NEKOPI_PORT/api/health" &>/dev/null; then
        READY=1; break
    fi
    sleep 1
done

if [ "$READY" = "1" ]; then
    ok "NekoPi is running on https://0.0.0.0:$NEKOPI_PORT"
else
    warn "NekoPi did not respond yet — check: journalctl -u nekopi -f"
fi


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  24 · POST-INSTALL VERIFICATION"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       NekoPi — Post-Install Verification     ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

verify_install() {
    INSTALL_ERRORS=0

    check() {
        local label="$1"; local cmd="$2"
        if eval "$cmd" &>/dev/null; then
            ok "$label"
        else
            fail "$label"
            INSTALL_ERRORS=$((INSTALL_ERRORS + 1))
        fi
    }

    check "systemd service nekopi"        "systemctl is-active --quiet nekopi"
    check "dnsmasq active"                "systemctl is-active --quiet dnsmasq"
    check "cockpit socket active"         "systemctl is-active --quiet cockpit.socket"
    check "ollama service"                "systemctl is-active --quiet ollama"
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
    check "ollama binary"                 "command -v ollama"
    check "Group: dialout"                "groups $NEKOPI_USER | grep -q dialout"
    check "Group: wireshark"              "groups $NEKOPI_USER | grep -q wireshark"

    # Hardware-conditional checks
    if [ "$HAS_ETH_MGMT" = "yes" ]; then
        check "MGMT iface has 192.168.99.1" "ip addr show | grep -q 192.168.99.1"
    else
        warn "No MGMT iface detected — skipping IP check (expected on generic Linux)"
    fi

    if [ "$HAS_WLAN1" = "yes" ]; then
        check "wlan1 monitor mode capable" "iw phy | grep -q 'monitor\|managed'"
    else
        warn "No wlan1 (USB WiFi) — Kismet/Roaming/Profiler modules will show 'no hardware' in UI"
    fi

    if [ "$HAS_ETH_TEST" = "yes" ]; then
        ok "TEST iface detected ($TEST_IFACE) — Wired/Security modules enabled"
    else
        warn "No TEST iface (r8169/r8125) — Wired/Security auto-subnet detection will be limited"
    fi

    ELAPSED=$(( $(date +%s) - STARTED_AT ))
    MINS=$(( ELAPSED / 60 ))
    SECS=$(( ELAPSED % 60 ))

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ "$INSTALL_ERRORS" -eq 0 ]; then
        echo -e "  ${GREEN}✅ Installation verified — no errors${NC}"
    else
        echo -e "  ${YELLOW}⚠️  $INSTALL_ERRORS checks failed — review output above${NC}"
    fi
    echo "  Time:   ${MINS}m ${SECS}s"
    echo "  Access: https://$(hostname -I | awk '{print $1}'):$NEKOPI_PORT"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ "$INSTALL_ERRORS" -eq 0 ]; then
        echo -e "${GREEN}🎉 NekoPi installed successfully!${NC}"
    fi
    echo ""
}

verify_install
