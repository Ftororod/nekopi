#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  NekoPi Field Unit — Automated Installer v2
#  Generated: 2026-04-13 11:09
#  Target:    Ubuntu 24.04 LTS · Raspberry Pi 5 · 8 GB
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
echo "  0 · USER"
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
echo "  1 · DIRECTORIES"
echo "════════════════════════════════════════════════════════════"
info "Creating directory tree…"
mkdir -p "$NEKOPI_DIR"/{api,bin,captures/kismet,captures/ota,data,logs,oled,reports,ssl,tftp,ui/assets}
mkdir -p /srv/tftp
chmod 777 /srv/tftp
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
ok "Directories ready"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  2 · APT REPOSITORIES"
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

# Disable Kismet repo if present (breaks apt on arm64)
if ls /etc/apt/sources.list.d/kismet*.list 2>/dev/null; then
    sed -i 's/^deb /# deb /' /etc/apt/sources.list.d/kismet*.list
    warn "Kismet repo disabled to avoid apt conflicts"
fi

apt-get update -qq
ok "Package lists updated"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  3 · BASE DEPENDENCIES"
echo "════════════════════════════════════════════════════════════"
info "Installing system packages…"

# tshark needs non-interactive debconf
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
echo "  4 · USER GROUPS"
echo "════════════════════════════════════════════════════════════"
info "Adding $NEKOPI_USER to required groups…"
usermod -a -G dialout   "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G wireshark "$NEKOPI_USER" 2>/dev/null || true
usermod -a -G netdev    "$NEKOPI_USER" 2>/dev/null || true
ok "Groups: dialout, wireshark, netdev"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  5 · CLONE / UPDATE REPO"
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


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  6 · PYTHON VIRTUAL ENVIRONMENT"
echo "════════════════════════════════════════════════════════════"
info "Setting up Python venv…"
if [ ! -d "$NEKOPI_DIR/venv" ]; then
    sudo -u "$NEKOPI_USER" python3 -m venv "$NEKOPI_DIR/venv"
    ok "Venv created"
else
    ok "Venv already exists"
fi

info "Installing Python dependencies…"
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
echo "  7 · SSL CERTIFICATE"
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
echo "  8 · SYSTEMD SERVICE"
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
echo "  9 · NETPLAN — ETH1 STATIC IP"
echo "════════════════════════════════════════════════════════════"
info "Configuring eth1 static IP (192.168.99.1/24)…"
cat > /etc/netplan/01-nekopi.yaml << 'NETPLAN'
network:
  version: 2
  ethernets:
    eth1:
      dhcp4: false
      optional: true
      addresses: [192.168.99.1/24]
NETPLAN

sed -i 's/^    //' /etc/netplan/01-nekopi.yaml
chmod 600 /etc/netplan/01-nekopi.yaml
netplan apply 2>/dev/null || warn "netplan apply failed (eth1 may not be present yet)"
ok "Netplan configured"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  10 · DNSMASQ — DHCP FOR ETH1"
echo "════════════════════════════════════════════════════════════"
info "Configuring dnsmasq for management network…"
cat > /etc/dnsmasq.conf << 'DNSMASQ'
interface=eth1
bind-interfaces
except-interface=eth0
except-interface=wlan0
except-interface=wlan1
dhcp-range=192.168.99.100,192.168.99.199,255.255.255.0,12h
dhcp-option=3,192.168.99.1
dhcp-option=6,192.168.99.1
server=8.8.8.8
server=8.8.4.4
DNSMASQ

# Override: wait for eth1 before starting
mkdir -p /etc/systemd/system/dnsmasq.service.d/
cat > /etc/systemd/system/dnsmasq.service.d/wait-eth1.conf << 'OVERRIDE'
[Unit]
After=network-online.target sys-subsystem-net-devices-eth1.device
Wants=sys-subsystem-net-devices-eth1.device
OVERRIDE

mkdir -p /etc/dnsmasq.d

systemctl daemon-reload
systemctl enable dnsmasq
systemctl restart dnsmasq 2>/dev/null || warn "dnsmasq restart failed (eth1 may not be present)"
ok "dnsmasq configured"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  11 · INFLUXDB — INITIAL SETUP"
echo "════════════════════════════════════════════════════════════"
info "Setting up InfluxDB…"
if [ -f "$NEKOPI_DIR/data/influx-token.txt" ]; then
    ok "InfluxDB already configured (token exists)"
else
    systemctl start influxdb
    info "Waiting for InfluxDB to start…"
    for i in $(seq 1 30); do
        if influx ping &>/dev/null; then break; fi
        sleep 1
    done

    influx setup \
        --username nekopi \
        --password nekopi2024 \
        --org nekopi \
        --bucket nekopi \
        --retention 30d \
        --force 2>/dev/null && ok "InfluxDB initial setup done" \
        || warn "InfluxDB setup may already exist"

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
echo "  12 · GRAFANA"
echo "════════════════════════════════════════════════════════════"
info "Configuring Grafana (on-demand)…"
systemctl disable grafana-server 2>/dev/null || true
systemctl stop grafana-server 2>/dev/null || true
ok "Grafana disabled (on-demand, datasource auto-configured by NekoPi)"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  13 · COCKPIT — IFRAME EMBED"
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
echo "  14 · KISMET — LOG DIRECTORY"
echo "════════════════════════════════════════════════════════════"
info "Configuring Kismet log directory…"
mkdir -p /etc/kismet
cat > /etc/kismet/kismet_site.conf << 'KISMET'
log_prefix=/opt/nekopi/captures/kismet/Kismet
KISMET
ok "Kismet logs → $NEKOPI_DIR/captures/kismet/"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  15 · SUDOERS — SERVICE CONTROL"
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
echo "  16 · PKTVISOR"
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
echo "  17 · OLLAMA — LOCAL AI"
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
echo "  18 · DATA FILES"
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
echo "  19 · GITIGNORE"
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
echo "  20 · FINAL OWNERSHIP"
echo "════════════════════════════════════════════════════════════"
info "Fixing ownership on $NEKOPI_DIR…"
chown -R "$NEKOPI_USER":"$NEKOPI_USER" "$NEKOPI_DIR"
ok "Ownership set to $NEKOPI_USER"


echo ""
echo "════════════════════════════════════════════════════════════"
echo "  21 · ASSETS CHECK"
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
echo "  22 · START SERVICES"
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
echo "  23 · VERIFICATION"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       NekoPi Install Verification            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

PASS=0; TOTAL=0

check() {
    TOTAL=$((TOTAL+1))
    if eval "$1" &>/dev/null; then
        ok "$2"
        PASS=$((PASS+1))
    else
        fail "$2"
    fi
}

check "systemctl is-active --quiet nekopi"          "NekoPi service running"
check "systemctl is-active --quiet dnsmasq"         "dnsmasq running"
check "systemctl is-active --quiet cockpit.socket"  "Cockpit running"
check "systemctl is-active --quiet ollama"          "Ollama running"
check "ip addr show eth1 2>/dev/null | grep -q 192.168.99.1" "eth1 IP 192.168.99.1"
check "[ -f $NEKOPI_DIR/ssl/cert.pem ]"             "SSL certificate"
check "[ -f $NEKOPI_DIR/data/influx-token.txt ]"    "InfluxDB token"
check "[ -f $NEKOPI_DIR/data/dhcp-options.json ]"   "DHCP options file"
check "command -v ttyd"                              "ttyd installed"
check "command -v tshark"                            "tshark installed"
check "command -v ollama"                            "ollama installed"
check "groups $NEKOPI_USER | grep -q dialout"       "dialout group"
check "groups $NEKOPI_USER | grep -q wireshark"     "wireshark group"
check "[ -f $NEKOPI_DIR/ui/index.html ]"            "UI index.html"

ELAPSED=$(( $(date +%s) - STARTED_AT ))
MINS=$(( ELAPSED / 60 ))
SECS=$(( ELAPSED % 60 ))

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Result: ${GREEN}$PASS${NC} / $TOTAL passed"
echo "  Time:   ${MINS}m ${SECS}s"
echo "  Access: https://$(hostname -I | awk '{print $1}'):$NEKOPI_PORT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$PASS" -eq "$TOTAL" ]; then
    echo -e "${GREEN}🎉 NekoPi installed successfully!${NC}"
else
    echo -e "${YELLOW}⚠️  Some checks failed — review output above${NC}"
fi
echo ""
