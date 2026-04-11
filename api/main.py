#!/usr/bin/env python3
"""
NekoPi Field Unit — FastAPI Backend v1.3
Codename: Tomás
"""
from fastapi import FastAPI, Query, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import asyncio, json, subprocess, re, socket, time, os, shutil

app = FastAPI(title="NekoPi Field Unit API", version="1.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BASE_DIR  = Path(__file__).parent.parent
HTML_FILE = BASE_DIR / "ui" / "index.html"

@app.get("/", include_in_schema=False)
async def root():
    if HTML_FILE.exists():
        return FileResponse(str(HTML_FILE))
    return HTMLResponse("""<h2>NekoPi API running</h2><a href=/docs>API Docs</a>""")

@app.get("/demo", include_in_schema=False)
async def demo_mode():
    if HTML_FILE.exists():
        content = HTML_FILE.read_text()
        content = content.replace("</head>", "<script>window.NEKOPI_DEMO_MODE=true;</script></head>")
        return HTMLResponse(content)
    return HTMLResponse("Frontend not found")

@app.get("/live", include_in_schema=False)
async def live_mode():
    if HTML_FILE.exists():
        return FileResponse(str(HTML_FILE))
    return HTMLResponse("Frontend not found")

# ── HELPERS ──────────────────────────────────────────────────
def run_cmd(cmd: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def get_default_gateway() -> str:
    out = run_cmd(["ip", "route", "show", "default"])
    m = re.search(r"via\s+(\S+)", out)
    return m.group(1) if m else ""

def get_dns_servers() -> list:
    """Get DNS servers — prefer those from the GW interface, not isolated segments"""
    gw = get_default_gateway()

    # Try resolvectl per-interface first
    if gw:
        out = run_cmd(["resolvectl", "status"])
        # Find the interface that has the default gateway
        ifaces = get_interfaces()
        gw_iface = next((i for i in ifaces if i["ip"] and
                        gw.startswith(".".join(i["ip"].split(".")[:3]))), None)
        if gw_iface:
            # Look for DNS servers listed under that specific interface
            pattern = re.compile(
                r"Link \d+\s+\(" + re.escape(gw_iface["name"]) + r"\).*?DNS Servers:\s+(.+?)(?:\n\S|\Z)",
                re.DOTALL
            )
            m = pattern.search(out)
            if m:
                servers = m.group(1).split()
                if servers: return servers

    # Fallback: resolvectl global
    out = run_cmd(["resolvectl", "status"])
    servers = re.findall(r"DNS Servers:\s+(.+)", out)
    if servers:
        found = servers[0].split()
        real = [s for s in found if not s.startswith("127.")]
        if real: return real

    # Fallback: resolv.conf filtering 127.x
    try:
        content = Path("/etc/resolv.conf").read_text()
        found = re.findall(r"nameserver\s+(\S+)", content)
        return [s for s in found if not s.startswith("127.")] or found
    except Exception:
        return []

def get_interfaces() -> list:
    ifaces = []
    out = run_cmd(["ip", "-j", "addr"])
    try:
        data = json.loads(out)
        for iface in data:
            name  = iface.get("ifname", "")
            flags = iface.get("flags", [])
            if name == "lo":
                continue
            addrs = [a["local"] for a in iface.get("addr_info", []) if a.get("family") == "inet"]

            # Detect type by name
            if name.startswith(("wlan", "wlp")):
                itype = "wifi"
            elif name.startswith(("eth", "ens", "enp", "eno", "end")):
                itype = "eth"
            else:
                itype = "other"

            # Detect role by driver — universal for any RPi5
            driver = ""
            try:
                driver = Path(f"/sys/class/net/{name}/device/driver/module").resolve().name
            except Exception:
                try:
                    driver_link = Path(f"/sys/class/net/{name}/device/driver")
                    driver = driver_link.resolve().name if driver_link.exists() else ""
                except Exception:
                    pass

            # Role assignment:
            # eth0 = HAT (r8169/r8125 PCIe)  → test
            # eth1 = native RPi5 (macb)       → mgmt
            # wlan0 = native RPi5 (brcmfmac)  → scan
            # wlan1 = HAT WiFi (future WiFi7) → test_wifi
            role = "unknown"
            if driver in ("r8169", "r8125"):   role = "test"
            elif driver in ("macb", "bcmgenet"): role = "mgmt"
            elif driver == "brcmfmac":          role = "scan"
            elif itype == "wifi":               role = "test_wifi"
            elif itype == "eth" and name == "eth0": role = "test"
            elif itype == "eth" and name == "eth1": role = "mgmt"

            ifaces.append({
                "name":   name,
                "label":  _label(name),
                "status": "up" if "UP" in flags else "down",
                "ip":     addrs[0] if addrs else "",
                "type":   itype,
                "driver": driver,
                "role":   role,
            })
    except Exception:
        pass
    return ifaces

def _label(name: str) -> str:
    if re.match(r"^(eth|ens|enp|eno)\d", name):
        idx = re.sub(r"[^0-9]", "", name) or "0"
        return "ETH " + str(int(idx))
    if name.startswith("wlan"):
        return "WLAN " + name.replace("wlan","")
    if name.startswith("wlp"):
        idx = re.sub(r"[^0-9]", "", name) or "0"
        return "WLAN " + idx
    return name.upper()

def get_cpu_temp() -> float | None:
    for zone in range(4):
        p = Path(f"/sys/class/thermal/thermal_zone{zone}/temp")
        if p.exists():
            try:
                return round(int(p.read_text().strip()) / 1000, 1)
            except Exception:
                pass
    out = run_cmd(["vcgencmd", "measure_temp"])
    m = re.search(r"temp=([\d.]+)", out)
    return float(m.group(1)) if m else None

def get_iface_stats(name: str) -> dict:
    base = Path(f"/sys/class/net/{name}/statistics")
    def read(f):
        try: return int((base / f).read_text().strip())
        except: return 0
    return {"rx_bytes": read("rx_bytes"), "tx_bytes": read("tx_bytes"),
            "rx_errors": read("rx_errors"), "tx_errors": read("tx_errors")}

def _get_uptime() -> int:
    try: return int(float(Path("/proc/uptime").read_text().split()[0]))
    except: return 0

def _svc_active(name: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() == "active"
    except: return False

def _port_open(port: int) -> bool:
    import socket as _s
    try:
        s = _s.create_connection(("127.0.0.1", port), timeout=1); s.close(); return True
    except: return False

# ── HEALTH ───────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.3.0", "codename": "Tomas",
            "hostname": socket.gethostname(), "uptime_s": _get_uptime()}

# ── SERVICES STATUS ──────────────────────────────────────────
@app.get("/api/services/status")
async def services_status():
    ifaces = get_interfaces()
    has_wifi   = any(i["type"] == "wifi" for i in ifaces)
    has_wired  = any(i["type"] == "eth"  for i in ifaces)
    has_influx  = _svc_active("influxdb")       or _port_open(8086)
    has_grafana = _svc_active("grafana-server") or _port_open(3000)
    has_ttyd    = _svc_active("ttyd")           or _port_open(7681)
    has_webssh  = _svc_active("webssh")         or _port_open(8888)
    has_lldpd   = _svc_active("lldpd")
    has_iperf3  = bool(run_cmd(["which", "iperf3"]))
    has_nmap    = bool(run_cmd(["which", "nmap"]))
    has_orb     = bool(run_cmd(["which", "orb"]))

    # AI backend availability — RPi is NEVER an Ollama host. Ollama is always
    # remote. Returns whichever side is configured + online so the UI can show
    # both states (some modules need Ollama specifically for privacy).
    try:
        s = json.loads((BASE_DIR / "data" / "settings.json").read_text())
    except Exception:
        s = {}
    gemini_online = bool(s.get("gemini_key"))
    ollama_url    = s.get("ollama_url") or ""
    ollama_online = False
    ollama_model  = ""
    if ollama_url:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{ollama_url.rstrip('/')}/api/tags", timeout=2) as r:
                tags = json.loads(r.read())
                models = tags.get("models", [])
                if models:
                    ollama_online = True
                    ollama_model  = models[0].get("name", "")
        except Exception:
            ollama_online = False

    return {
        "wifi": has_wifi, "wired": has_wired,
        "influx": has_influx, "grafana": has_grafana,
        "ai_gemini_online": gemini_online,
        "ai_ollama_online": ollama_online,
        "ai_ollama_model":  ollama_model,
        "ttyd": has_ttyd, "webssh": has_webssh,
        "lldpd": has_lldpd, "iperf3": has_iperf3, "nmap": has_nmap, "orb": has_orb,
    }

# ── SYSTEM METRICS ───────────────────────────────────────────
@app.get("/api/system/metrics")
async def system_metrics():
    cpu_temp = get_cpu_temp()
    cpu_pct  = None
    try:
        out1 = Path("/proc/stat").read_text().splitlines()[0].split()
        await asyncio.sleep(0.5)
        out2 = Path("/proc/stat").read_text().splitlines()[0].split()
        idle1 = int(out1[4]); total1 = sum(int(x) for x in out1[1:])
        idle2 = int(out2[4]); total2 = sum(int(x) for x in out2[1:])
        dtotal = total2 - total1; didle = idle2 - idle1
        cpu_pct = round((1 - didle / dtotal) * 100, 1) if dtotal else 0
    except: pass
    ram = {}
    try:
        mi = Path("/proc/meminfo").read_text()
        def mkb(k): m = re.search(k + r":\s+(\d+)", mi); return int(m.group(1)) if m else 0
        total = mkb("MemTotal"); avail = mkb("MemAvailable"); used = total - avail
        ram = {"total_mb": total//1024, "used_mb": used//1024, "pct": round(used/total*100, 1)}
    except: pass
    disk = {}
    try:
        st = os.statvfs("/")
        tb = st.f_blocks * st.f_frsize; fb = st.f_bfree * st.f_frsize; ub = tb - fb
        disk = {"total_gb": round(tb/1e9,1), "used_gb": round(ub/1e9,1), "pct": round(ub/tb*100,1)}
    except: pass
    wifi_throughput = None
    try:
        ifaces = get_interfaces()
        wi = next((i for i in ifaces if i["type"] == "wifi"), None)
        if wi:
            s1 = get_iface_stats(wi["name"]); await asyncio.sleep(0.5); s2 = get_iface_stats(wi["name"])
            mbps = ((s2["rx_bytes"]-s1["rx_bytes"]) + (s2["tx_bytes"]-s1["tx_bytes"])) * 8/1e6/0.5
            wifi_throughput = round(mbps/1000, 3)
    except: pass
    return {"cpu_temp": cpu_temp, "cpu_pct": cpu_pct, "ram": ram, "disk": disk,
            "wifi_throughput": wifi_throughput, "latency_ms": None, "uptime_s": _get_uptime()}

# ── NETWORK INFO ─────────────────────────────────────────────
@app.get("/api/network/info")
async def network_info():
    gw     = get_default_gateway()
    ifaces = get_interfaces()

    # Mark roles based on driver + GW
    for i in ifaces:
        # is_gw: has default gateway route
        i["is_gw"] = bool(i["ip"] and gw and
                          gw.startswith(".".join(i["ip"].split(".")[:3])))
        # is_test: HAT interface (r8169/r8125 driver or eth0)
        i["is_test"] = i.get("role") in ("test", "test_wifi")
        # is_mgmt: native RPi5 or GW interface
        i["is_mgmt"] = i.get("role") in ("mgmt",) or i["is_gw"]

    dns = get_dns_servers()

    subnets = {}
    try:
        routes = json.loads(run_cmd(["ip", "-j", "route"]))
        for i in ifaces:
            for r in routes:
                if r.get("dev") == i["name"] and "dst" in r and r["dst"] != "default":
                    subnets[i["name"]] = r["dst"]; break
    except: pass

    speeds = {}
    for i in ifaces:
        try:
            s = int(Path(f"/sys/class/net/{i['name']}/speed").read_text().strip())
            speeds[i["name"]] = (f"{s} Mb/s" if s < 1000 else f"{s//1000} Gb/s") if s > 0 else "down"
        except: speeds[i["name"]] = "unknown"

    # Identify test and mgmt interfaces for frontend convenience
    test_iface = next((i for i in ifaces if i.get("is_test") and i["type"] == "eth"), None)
    mgmt_iface = next((i for i in ifaces if i.get("is_gw")), None)
    test_speed = speeds.get(test_iface["name"]) if test_iface else None

    return {"gateway": gw, "dns": dns[0] if dns else "", "dns_list": dns,
            "hostname": socket.gethostname(), "domain": "CO",
            "interfaces": ifaces, "subnets": subnets, "speeds": speeds,
            "test_iface": test_iface["name"] if test_iface else None,
            "test_speed": test_speed,
            "mgmt_iface": mgmt_iface["name"] if mgmt_iface else None}

@app.get("/api/network/public-ip")
async def public_ip():
    import urllib.request
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as r:
            data = json.loads(r.read())
            ip = data.get("ip", "")
        # Geo lookup
        with urllib.request.urlopen(f"https://ipapi.co/{ip}/json/", timeout=5) as r:
            geo = json.loads(r.read())
        return {"ip": ip, "isp": geo.get("org","—"), "city": geo.get("city","—"),
                "country": geo.get("country_name","—"), "ok": True}
    except Exception as e:
        return {"ip": "—", "isp": "—", "city": "—", "country": "—", "ok": False, "error": str(e)}

# ── NETWORK TRAFFIC ──────────────────────────────────────────
_traffic_snap: dict = {}

_traffic_last_result = []

@app.get("/api/network/traffic")
async def network_traffic():
    global _traffic_snap, _traffic_last_result
    ifaces = get_interfaces(); result = []; now = time.time()
    dt = now - _traffic_snap.get("_ts", now - 2)
    for i in ifaces:
        s2 = get_iface_stats(i["name"]); s1 = _traffic_snap.get(i["name"], {})
        if s1 and dt >= 0.5:  # Need at least 0.5s between samples
            rx = round((s2["rx_bytes"]-s1.get("rx_bytes",0))*8/1e6/dt, 2)
            tx = round((s2["tx_bytes"]-s1.get("tx_bytes",0))*8/1e6/dt, 2)
        else:
            rx = tx = 0.0
        _traffic_snap[i["name"]] = s2
        result.append({"name": i["name"], "label": i["label"],
                        "rx_mbps": max(0.0, rx), "tx_mbps": max(0.0, tx),
                        "rx_errors": s2["rx_errors"], "tx_errors": s2["tx_errors"]})
    _traffic_snap["_ts"] = now
    # If all zeros but we have a recent result, return cached (warmup case)
    if all(r["rx_mbps"] == 0 and r["tx_mbps"] == 0 for r in result) and _traffic_last_result:
        return {"interfaces": _traffic_last_result, "ts": now, "cached": True}
    _traffic_last_result = result
    return {"interfaces": result, "ts": now}

# ── NETWORK PROBES ───────────────────────────────────────────
@app.get("/api/network/probes")
async def network_probes():
    gw  = get_default_gateway()
    dns = (get_dns_servers() or ["8.8.8.8"])[0]
    targets = [
        {"name": "Gateway",    "host": gw or "192.168.1.1"},
        {"name": "DNS",        "host": dns},
        {"name": "1.1.1.1",   "host": "1.1.1.1"},
        {"name": "8.8.8.8",   "host": "8.8.8.8"},
        {"name": "Google",     "host": "google.com"},
        {"name": "Cloudflare", "host": "cloudflare.com"},
        {"name": "AWS",        "host": "aws.amazon.com"},
    ]

    async def ping_one(t):
        if not t["host"]: return {**t, "rtt_ms": None, "loss": True}
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", "2", "-W", "2", "-q", t["host"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            out = stdout.decode()
        except Exception:
            return {"name": t["name"], "host": t["host"], "rtt_ms": None, "loss": True}
        rtt_m  = re.search(r"rtt min/avg/max.*=\s*[\d.]+/([\d.]+)/", out)
        loss_m = re.search(r"(\d+)%\s+packet loss", out)
        loss   = int(loss_m.group(1)) == 100 if loss_m else True
        return {"name": t["name"], "host": t["host"],
                "rtt_ms": float(rtt_m.group(1)) if rtt_m and not loss else None,
                "loss": loss}

    results = await asyncio.gather(*[ping_one(t) for t in targets])
    return {"probes": list(results)}

# ── QUICK CHECK ──────────────────────────────────────────────
@app.get("/api/qc/run")
async def qc_run(gateway: str = "", dns: str = "", target: str = "1.1.1.1", groups: str = "network,security,wifi"):
    gw         = gateway or get_default_gateway()
    dns_server = dns or (get_dns_servers() or ["8.8.8.8"])[0]
    ifaces     = get_interfaces()
    test_iface = next((i for i in ifaces if i.get("is_test")), None)
    # Prefer WiFi interface that is actually associated
    def is_associated(iface_name):
        out = run_cmd(["iw", "dev", iface_name, "link"])
        return "Connected to" in out or "SSID" in out

    wifi_ifaces = [i for i in ifaces if i["type"] == "wifi"]
    wifi_iface  = next((i for i in wifi_ifaces if is_associated(i["name"])), None)
    if not wifi_iface and wifi_ifaces:
        wifi_iface = wifi_ifaces[0]  # fallback to first

    # ── Helper: async ping ────────────────────────────────────
    async def apingt(name: str, host: str, count: int = 10, detail: str = ""):
        if not host:
            return {"name": name, "ok": False, "val": "no host", "detail": detail, "group": "network"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "ping", "-c", str(count), "-W", "2", "-q", host,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=count*3+5)
            out = out.decode()
        except Exception:
            return {"name": name, "ok": False, "val": "timeout", "detail": detail, "group": "network"}
        rtt_m  = re.search(r"rtt min/avg/max.*=\s*([\d.]+)/([\d.]+)/([\d.]+)", out)
        loss_m = re.search(r"(\d+)%\s+packet loss", out)
        recv_m = re.search(r"(\d+) received", out)
        loss   = int(loss_m.group(1)) if loss_m else 100
        ok     = loss < 100
        rtt    = float(rtt_m.group(2)) if rtt_m and ok else None
        recv   = int(recv_m.group(1)) if recv_m else 0
        return {"name": name, "ok": ok,
                "val": f"{rtt:.1f}ms" if rtt else "timeout",
                "detail": f"{recv}/{count} recv · {loss}% loss · {detail}",
                "group": "network"}

    # ── 1. Gateway reachability ───────────────────────────────
    async def test_gateway():
        r = await apingt("Gateway", gw, count=5, detail=f"gw:{gw}")
        r["icon"] = "🏠"
        return r

    # ── 2. Gateway packet loss ────────────────────────────────
    async def test_packet_loss():
        r = await apingt("Packet Loss", gw, count=20, detail="20 pings al GW")
        loss_m = re.search(r"(\d+)% loss", r["detail"])
        loss = int(loss_m.group(1)) if loss_m else 0
        r["name"] = "Packet Loss"
        r["ok"] = loss == 0
        r["val"] = f"{loss}%"
        r["icon"] = "📉"
        return r

    # ── 3. DNS server reachability ────────────────────────────
    async def test_dns_reach():
        r = await apingt("DNS Server", dns_server, count=3, detail=f"dns:{dns_server}")
        r["name"] = "DNS Reach"
        r["icon"] = "🔍"
        return r

    # ── 4. DNS resolution ─────────────────────────────────────
    async def test_dns_resolve():
        cmd = ["dig", "+short", "+time=3", f"@{dns_server}", "google.com"]
        t0  = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            out = out.decode().strip()
            ms  = round((time.time()-t0)*1000, 1)
        except Exception:
            return {"name":"DNS Resolve","ok":False,"val":"failed","detail":"dig timeout","icon":"🌐","group":"network"}
        ok = bool(out) and "error" not in out.lower()
        return {"name":"DNS Resolve","ok":ok,
                "val":f"{ms}ms" if ok else "failed",
                "detail":f"@{dns_server} → {out[:25] if ok else 'no response'}",
                "icon":"🌐","group":"network"}

    # ── 5. Internet reachability ──────────────────────────────
    async def test_internet():
        # HTTP check primario — funciona incluso cuando ICMP está bloqueado (hotspots móviles)
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "8", "-o", "/dev/null", "-w", "%{http_code}",
                "http://connectivitycheck.gstatic.com/generate_204",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            code = out.decode().strip()
            ok = code == "204"
            if ok:
                return {"name":"Internet","ok":True,"val":"OK","detail":"HTTP 204 — full connectivity","icon":"🌍","group":"network"}
        except Exception:
            code = "err"
        # Fallback: ping a 1.1.1.1
        ping_r = await apingt("Internet", "1.1.1.1", count=3)
        if ping_r["ok"]:
            return {"name":"Internet","ok":True,"val":"OK","detail":"ping 1.1.1.1 ok (ICMP only)","icon":"🌍","group":"network"}
        return {"name":"Internet","ok":False,"val":f"HTTP {code}",
                "detail":"No HTTP ni ICMP — sin conectividad","icon":"🌍","group":"network"}

    # ── 6. MTU path discovery ─────────────────────────────────
    async def test_mtu():
        # Ping con tamaños crecientes para encontrar MTU del path
        mtu_ok = 1500
        for mtu in [1500, 1472, 1400, 1280]:
            payload = mtu - 28  # IP+ICMP headers
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ping", "-c", "2", "-W", "2", "-M", "do", "-s", str(payload), gw,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(), timeout=8)
                combined = (out + err).decode()
                if "0% packet loss" in combined or "0 received" not in combined:
                    mtu_ok = mtu
                    break
            except Exception:
                continue
        ok = mtu_ok >= 1500
        return {"name":"MTU Path","ok":ok,
                "val":f"{mtu_ok}B",
                "detail":"full MTU ok" if ok else f"MTU limited to {mtu_ok}B — possible fragmentation",
                "icon":"📦","group":"network"}

    # ── 7. Default route validation ───────────────────────────
    async def test_routes():
        out = run_cmd(["ip", "route", "show", "default"])
        routes = [l for l in out.splitlines() if "default" in l]
        count  = len(routes)
        # NekoPi normalmente tiene 2-3 rutas (eth0 test + eth1 mgmt + wlan)
        ok   = count >= 1
        warn = count > 3
        detail = f"{count} default route{'s' if count != 1 else ''}"
        if count == 0:
            detail = "⚠ No default route — sin conectividad"
            ok = False
        elif count <= 3:
            detail += " — OK para arquitectura multi-iface"
        else:
            detail += " — posible conflicto de rutas"
            ok = False
        return {"name":"Default Route","ok":ok,
                "val":f"{count} route{'s' if count!=1 else ''}",
                "detail":detail,"icon":"🗺","group":"network"}

    # ── 8. Interface errors (duplex/speed mismatch) ───────────
    async def test_iface_errors():
        iface_name = test_iface["name"] if test_iface else (ifaces[0]["name"] if ifaces else "eth0")
        stats_path = Path(f"/sys/class/net/{iface_name}/statistics")
        try:
            rx_err = int((stats_path/"rx_errors").read_text().strip())
            tx_err = int((stats_path/"tx_errors").read_text().strip())
            rx_drop= int((stats_path/"rx_dropped").read_text().strip())
            total_err = rx_err + tx_err + rx_drop
            ok = total_err == 0
            return {"name":"Interface Errors","ok":ok,
                    "val":f"{total_err} errors",
                    "detail":f"rx_err:{rx_err} tx_err:{tx_err} drop:{rx_drop} on {iface_name}",
                    "icon":"🔌","group":"network"}
        except Exception:
            return {"name":"Interface Errors","ok":True,"val":"ok","detail":f"no errors on {iface_name}","icon":"🔌","group":"network"}

    # ── 9. Captive portal detection ───────────────────────────
    async def test_captive():
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "5", "-L", "-o", "/dev/null",
                "-w", "%{http_code}|%{url_effective}",
                "http://connectivitycheck.gstatic.com/generate_204",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            result = out.decode().strip()
            parts  = result.split("|")
            code   = parts[0] if parts else "0"
            url    = parts[1] if len(parts) > 1 else ""
            if code == "000":
                # Timeout o sin conectividad — no es captive portal
                return {"name":"Captive Portal","ok":True,"val":"N/A",
                        "detail":"Sin conectividad HTTP — no aplica","icon":"🔓","group":"security"}
            captive = code != "204" or "gstatic" not in url
            return {"name":"Captive Portal","ok":not captive,
                    "val":"None detected" if not captive else "DETECTED",
                    "detail":f"HTTP {code}" + (f" → {url[:30]}" if captive else ""),
                    "icon":"🔓","group":"security"}
        except Exception:
            return {"name":"Captive Portal","ok":True,"val":"ok","detail":"no redirect","icon":"🔓","group":"security"}

    # ── 10. Rogue DHCP detection ──────────────────────────────
    async def test_rogue_dhcp():
        # Buscar múltiples servidores DHCP en el segmento
        # Usar nmap si disponible, si no dhcping
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "nmap", "--script", "broadcast-dhcp-discover", "-e",
                (test_iface["name"] if test_iface else "eth0"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            out = out.decode()
            servers = re.findall(r"Server Identifier:\s*([\d.]+)", out)
            ok = len(servers) <= 1
            return {"name":"Rogue DHCP","ok":ok,
                    "val":f"{len(servers)} server{'s' if len(servers)!=1 else ''}",
                    "detail":"no rogue DHCP" if ok else f"⚠ Multiple DHCP: {', '.join(servers)}",
                    "icon":"⚠","group":"security"}
        except Exception:
            return {"name":"Rogue DHCP","ok":True,"val":"1 server","detail":"single DHCP server","icon":"⚠","group":"security"}

    # ── 11. DHCP lease health ─────────────────────────────────
    async def test_dhcp_lease():
        dhcp = await network_dhcp()
        ok   = dhcp.get("active", False)
        expires = dhcp.get("expires", "?")
        server  = dhcp.get("server", "?")
        return {"name":"DHCP Lease","ok":ok,
                "val":"Active" if ok else "No lease",
                "detail":f"server:{server} expires:{expires}" if ok else "no active lease",
                "icon":"📋","group":"security"}

    # ── 12-17. WiFi tests ─────────────────────────────────────
    async def test_wifi_association():
        if not wifi_iface:
            return {"name":"WiFi Assoc","ok":False,"val":"no iface","detail":"no WiFi interface","icon":"📡","group":"wifi"}
        out = run_cmd(["iw", "dev", wifi_iface["name"], "link"])
        connected = "Connected to" in out or "SSID" in out
        ssid_m = re.search(r"SSID:\s*(.+)", out)
        bssid_m= re.search(r"Connected to\s*([\w:]+)", out)
        ssid   = ssid_m.group(1).strip() if ssid_m else "?"
        bssid  = bssid_m.group(1) if bssid_m else "?"
        return {"name":"WiFi Assoc","ok":connected,
                "val":ssid if connected else "Not connected",
                "detail":f"BSSID:{bssid}" if connected else "not associated",
                "icon":"📡","group":"wifi"}

    async def test_wifi_signal():
        if not wifi_iface:
            return {"name":"WiFi Signal","ok":False,"val":"no iface","detail":"","icon":"📶","group":"wifi"}
        out = run_cmd(["iw", "dev", wifi_iface["name"], "link"])
        sig_m   = re.search(r"signal:\s*([-\d.]+)\s*dBm", out)
        noise_m = re.search(r"noise floor:\s*([-\d.]+)\s*dBm", out)
        if not sig_m:
            return {"name":"WiFi Signal","ok":False,"val":"not assoc","detail":"not associated","icon":"📶","group":"wifi"}
        rssi  = float(sig_m.group(1))
        noise = float(noise_m.group(1)) if noise_m else -95.0
        snr   = rssi - noise
        ok    = rssi >= -70 and snr >= 20
        qual  = "Excellent" if rssi>=-55 else "Good" if rssi>=-65 else "Fair" if rssi>=-75 else "Poor"
        return {"name":"WiFi Signal","ok":ok,
                "val":f"{rssi:.0f}dBm",
                "detail":f"SNR:{snr:.0f}dB · {qual}",
                "icon":"📶","group":"wifi"}

    async def test_wifi_standard():
        if not wifi_iface:
            return {"name":"WiFi Standard","ok":False,"val":"no iface","detail":"","icon":"📻","group":"wifi"}
        out = run_cmd(["iw", "dev", wifi_iface["name"], "link"])
        rate_m = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", out)
        he_m   = re.search(r"HE-MCS\s*(\d+)", out)
        vht_m  = re.search(r"VHT-MCS\s*(\d+)", out)
        mcs_m  = re.search(r"MCS\s*(\d+)", out)
        width_m= re.search(r"(\d+)MHz", out)
        rate   = float(rate_m.group(1)) if rate_m else 0
        std    = "802.11ax(WiFi6)" if he_m else "802.11ac(WiFi5)" if vht_m else "802.11n(WiFi4)" if mcs_m else "legacy"
        width  = width_m.group(1) + "MHz" if width_m else "?"
        ok     = he_m is not None or vht_m is not None
        return {"name":"WiFi Standard","ok":ok,
                "val":std,
                "detail":f"{rate:.0f}Mbps · {width}",
                "icon":"📻","group":"wifi"}

    async def test_wifi_channel_load():
        if not wifi_iface:
            return {"name":"Channel Load","ok":True,"val":"n/a","detail":"no WiFi","icon":"📊","group":"wifi"}
        # Contar APs en el mismo canal del AP asociado
        out_link = run_cmd(["iw", "dev", wifi_iface["name"], "link"])
        freq_m   = re.search(r"freq:\s*(\d+)", out_link)
        if not freq_m:
            return {"name":"Channel Load","ok":True,"val":"n/a","detail":"not associated","icon":"📊","group":"wifi"}
        freq = freq_m.group(1)
        # Buscar en el último scan cuántos APs están en ese frecuencia
        out_scan = run_cmd(["iw", "dev", wifi_iface["name"], "scan", "dump"])
        same_ch  = len(re.findall(rf"freq: {freq}", out_scan))
        ok = same_ch <= 3
        return {"name":"Channel Load","ok":ok,
                "val":f"{same_ch} APs",
                "detail":f"on freq {freq}MHz — {'congested' if same_ch>3 else 'acceptable'}",
                "icon":"📊","group":"wifi"}

    async def test_wifi_roaming():
        if not wifi_iface:
            return {"name":"Roaming Ready","ok":True,"val":"n/a","detail":"no WiFi","icon":"🔄","group":"wifi"}
        out_link = run_cmd(["iw", "dev", wifi_iface["name"], "link"])
        ssid_m   = re.search(r"SSID:\s*(.+)", out_link)
        sig_m    = re.search(r"signal:\s*([-\d.]+)", out_link)
        if not ssid_m or not sig_m:
            return {"name":"Roaming Ready","ok":True,"val":"n/a","detail":"not associated","icon":"🔄","group":"wifi"}
        ssid       = ssid_m.group(1).strip()
        cur_rssi   = float(sig_m.group(1))
        out_scan   = run_cmd(["iw", "dev", wifi_iface["name"], "scan", "dump"])
        # Buscar APs con mismo SSID
        neighbors  = []
        blocks     = re.split(r"(?=BSS )", out_scan)
        for block in blocks:
            if f"SSID: {ssid}" in block:
                rssi_m = re.search(r"signal:\s*([-\d.]+)", block)
                bssid_m= re.search(r"BSS ([\w:]+)", block)
                if rssi_m and bssid_m:
                    neighbors.append((bssid_m.group(1), float(rssi_m.group(1))))
        neighbors.sort(key=lambda x: -x[1])
        best = neighbors[0][1] if neighbors else cur_rssi
        delta = best - cur_rssi
        ok = delta < 10  # Si hay otro AP >10dBm mejor, posible sticky client
        detail = f"{len(neighbors)} neighbor APs"
        if delta >= 10:
            detail += f" — mejor AP a +{delta:.0f}dB (sticky client?)"
        return {"name":"Roaming Ready","ok":ok,
                "val":f"{len(neighbors)} neighbors",
                "detail":detail,"icon":"🔄","group":"wifi"}

    # ── Run all tests in parallel ─────────────────────────────
    network_tasks = [
        test_gateway(), test_packet_loss(), test_dns_reach(),
        test_dns_resolve(), test_internet(), test_mtu(),
        test_routes(), test_iface_errors()
    ]
    security_tasks = [
        test_captive(), test_rogue_dhcp(), test_dhcp_lease()
    ]
    wifi_tasks = [
        test_wifi_association(), test_wifi_signal(), test_wifi_standard(),
        test_wifi_channel_load(), test_wifi_roaming()
    ]

    active_groups = [g.strip().lower() for g in groups.split(",") if g.strip()]
    tasks_to_run = []
    if "network"  in active_groups: tasks_to_run += network_tasks
    if "security" in active_groups: tasks_to_run += security_tasks
    if "wifi"     in active_groups: tasks_to_run += wifi_tasks
    if not tasks_to_run: tasks_to_run = network_tasks + security_tasks + wifi_tasks

    all_results = await asyncio.gather(
        *tasks_to_run,
        return_exceptions=True
    )

    tests = []
    for r in all_results:
        if isinstance(r, Exception):
            tests.append({"name":"Error","ok":False,"val":"exception","detail":str(r),"group":"network"})
        else:
            tests.append(r)

    passed = sum(1 for t in tests if t.get("ok"))
    return {
        "tests": tests,
        "passed": passed,
        "total": len(tests),
        "gateway": gw,
        "dns": dns_server,
        "groups": {
            "network":  [t for t in tests if t.get("group") == "network"],
            "security": [t for t in tests if t.get("group") == "security"],
            "wifi":     [t for t in tests if t.get("group") == "wifi"],
        }
    }

@app.get("/api/network/dhcp")
async def network_dhcp():
    """DHCP lease info using systemd-networkd format + response time"""
    ifaces = get_interfaces()
    gw     = get_default_gateway()
    result = {"lease_time": None, "expires": None, "response_ms": None,
              "server": None, "active": False, "lifetime_str": None}

    def parse_time_str(s: str) -> int:
        """Convert '2h', '30min', '1h 45min' to seconds"""
        if not s: return 0
        total = 0
        for m in re.finditer(r"(\d+)\s*(h|min|s)", s):
            v, unit = int(m.group(1)), m.group(2)
            if unit == "h":   total += v * 3600
            elif unit == "min": total += v * 60
            else:               total += v
        return total

    for iface in ifaces:
        if not iface.get("ip"): continue
        # Get ifindex for this interface
        try:
            ifindex = int(Path(f"/sys/class/net/{iface['name']}/ifindex").read_text().strip())
        except Exception:
            continue
        lease_path = Path(f"/run/systemd/netif/leases/{ifindex}")
        if not lease_path.exists():
            continue
        try:
            txt = lease_path.read_text()
            kv  = {}
            for line in txt.splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    kv[k.strip()] = v.strip()
            if kv.get("ADDRESS") == iface["ip"]:
                lt_str = kv.get("LIFETIME", "")
                lt_sec = parse_time_str(lt_str)
                result["active"]       = True
                result["lease_time"]   = lt_sec
                result["lifetime_str"] = lt_str
                result["server"]       = kv.get("SERVER_ADDRESS")
                # Calculate expiry from file mtime + lifetime
                try:
                    import os
                    mtime  = os.path.getmtime(str(lease_path))
                    expiry = mtime + lt_sec
                    import datetime
                    result["expires"] = datetime.datetime.fromtimestamp(expiry).strftime("%H:%M:%S")
                except Exception:
                    result["expires"] = lt_str
                break
        except Exception:
            pass

    # DHCP response time — use ping RTT to GW as proxy
    gw_iface = next((i for i in ifaces if i.get("ip") and
                     gw and gw.startswith(".".join(i["ip"].split(".")[:3]))), None)
    if gw:
        target = gw_iface["ip"] if gw_iface else gw
        out = run_cmd(["ping", "-c", "2", "-W", "1", "-q", gw], timeout=5)
        rtt_m = re.search(r"rtt min/avg/max.*=\s*[\d.]+/([\d.]+)/", out)
        if rtt_m:
            result["response_ms"] = float(rtt_m.group(1))

    return result
@app.get("/api/qc/ping")
async def qc_ping(target: str = "8.8.8.8", count: int = 4):
    out = run_cmd(["ping", "-c", str(count), "-W", "2", target], timeout=20)
    rtt_m  = re.search(r"rtt min/avg/max.*=\s*([\d.]+)/([\d.]+)/([\d.]+)", out)
    loss_m = re.search(r"(\d+)%\s+packet loss", out)
    return {"target": target, "output": out,
            "loss_pct": int(loss_m.group(1)) if loss_m else 100,
            "rtt_avg": float(rtt_m.group(2)) if rtt_m else None,
            "ok": loss_m is not None and int(loss_m.group(1)) < 100}

@app.get("/api/qc/dns")
async def qc_dns(domain: str = "google.com", server: str = ""):
    cmd = ["dig", "+short", "+time=3"]
    if server: cmd.append(f"@{server}")
    cmd.append(domain)
    t0 = time.time(); out = run_cmd(cmd, timeout=8); ms = round((time.time()-t0)*1000, 1)
    return {"domain": domain, "server": server or "default", "result": out, "ms": ms, "ok": bool(out)}

@app.get("/api/qc/gateway")
async def qc_gateway():
    gw = get_default_gateway()
    if not gw: return {"ok": False, "error": "No default gateway"}
    out    = run_cmd(["ping", "-c", "3", "-W", "2", "-q", gw], timeout=10)
    rtt_m  = re.search(r"rtt min/avg/max.*=\s*[\d.]+/([\d.]+)/", out)
    loss_m = re.search(r"(\d+)%\s+packet loss", out)
    return {"gateway": gw, "rtt_avg": float(rtt_m.group(1)) if rtt_m else None,
            "loss_pct": int(loss_m.group(1)) if loss_m else 100,
            "ok": loss_m is not None and int(loss_m.group(1)) < 100}

@app.get("/api/qc/captive")
async def qc_captive():
    import urllib.request
    probes = [("Google","http://connectivitycheck.gstatic.com/generate_204",204),
              ("Microsoft","http://msftconnecttest.com/connecttest.txt",200)]
    results = []
    for name, url, expected in probes:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NekoPi/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                results.append({"name": name, "status": r.status, "ok": r.status == expected})
        except Exception: results.append({"name": name, "status": 0, "ok": False})
    return {"captive_detected": not all(r["ok"] for r in results), "probes": results}

# ── WIFI ─────────────────────────────────────────────────────
def get_best_wifi_iface() -> str:
    """
    Selecciona la mejor interfaz WiFi disponible para scan.
    Prefiere dongles USB (wlan1+) sobre el WiFi integrado (wlan0/brcmfmac)
    ya que suelen tener mayor sensibilidad y alcance.
    """
    ifaces = get_interfaces()
    wifi_ifaces = [i for i in ifaces if i["type"] == "wifi"]
    if not wifi_ifaces:
        return ""
    # Preferir interfaz no-brcmfmac (dongle externo) si está disponible
    external = [i for i in wifi_ifaces if i.get("driver") != "brcmfmac"]
    if external:
        return external[0]["name"]
    return wifi_ifaces[0]["name"]


# ── WIFI ASSOCIATION ──────────────────────────────────────────
@app.get("/api/wifi/status")
async def wifi_status():
    """Estado de asociación de todas las interfaces WiFi — paralelo"""
    ifaces = get_interfaces()
    wifi_ifaces = [i for i in ifaces if i["type"] == "wifi"]

    async def get_one(iface):
        try:
            proc = await asyncio.create_subprocess_exec(
                "iw", "dev", iface["name"], "link",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            out = out.decode()
        except Exception:
            return {"iface": iface["name"], "connected": False}
        connected = "Connected to" in out or "SSID:" in out
        info = {"iface": iface["name"], "connected": connected}
        if connected:
            ssid_m  = re.search(r"SSID:\s*(.+)", out)
            bssid_m = re.search(r"Connected to\s*([\w:]+)", out)
            sig_m   = re.search(r"signal:\s*([-\d.]+)\s*dBm", out)
            rate_m  = re.search(r"tx bitrate:\s*([\d.]+)\s*MBit/s", out)
            freq_m  = re.search(r"freq:\s*(\d+)", out)
            info["ssid"]   = ssid_m.group(1).strip() if ssid_m else ""
            info["bssid"]  = bssid_m.group(1) if bssid_m else ""
            info["signal"] = float(sig_m.group(1)) if sig_m else None
            info["rate"]   = float(rate_m.group(1)) if rate_m else None
            info["freq"]   = int(freq_m.group(1)) if freq_m else None
            ip_out = run_cmd(["ip", "addr", "show", iface["name"]])
            ip_m   = re.search(r"inet\s+([\d.]+)/", ip_out)
            info["ip"] = ip_m.group(1) if ip_m else None
        return info

    results = await asyncio.gather(*[get_one(i) for i in wifi_ifaces])
    return {"interfaces": list(results)}

@app.post("/api/wifi/connect")
async def wifi_connect(iface: str = "wlan1", ssid: str = "", password: str = "", bssid: str = ""):
    """Conectar interfaz WiFi a un SSID via wpa_cli.
    Si la interfaz quedó en modo monitor (roaming/sensor) o tiene un *mon
    virtual, la regresamos a managed antes de hablar con wpa_supplicant."""
    if not ssid:
        return {"ok": False, "error": "SSID requerido"}

    # Refuse *mon virtual ifaces — they only support monitor mode.
    if iface.endswith("mon"):
        return {"ok": False, "error": f"{iface} es una interfaz monitor — usa wlan0"}

    # Step 0: Force the interface back to managed mode if it's in monitor
    # (a previous Roaming/Sensor session may have left it in monitor mode).
    info = run_cmd(["iw", "dev", iface, "info"])
    if "type monitor" in info:
        run_cmd(["sudo", "ip", "link", "set", iface, "down"])
        run_cmd(["sudo", "iw", "dev", iface, "set", "type", "managed"])
        run_cmd(["sudo", "ip", "link", "set", iface, "up"])
        await asyncio.sleep(0.5)

    # Step 0b: Make sure a wpa_supplicant ctrl_interface socket exists for this
    # iface — without it wpa_cli silently fails (which is exactly what the
    # user reported as "no me deja conectar a las redes que ya probé").
    sock = Path(f"/var/run/wpa_supplicant/{iface}")
    if not sock.exists():
        # Best effort: start the per-iface systemd unit if it exists.
        # wpa_supplicant-wlan0.service is the one shipped on this device.
        unit = f"wpa_supplicant-{iface}.service"
        chk = run_cmd(["systemctl", "list-unit-files", unit])
        if unit in chk:
            run_cmd(["sudo", "systemctl", "restart", unit])
            await asyncio.sleep(1.2)
        else:
            # Fall back to the generic template (needs /etc/wpa_supplicant/wpa_supplicant-<iface>.conf)
            tmpl = f"wpa_supplicant@{iface}.service"
            run_cmd(["sudo", "systemctl", "restart", tmpl])
            await asyncio.sleep(1.2)
        if not sock.exists():
            return {"ok": False,
                    "error": f"wpa_supplicant ctrl_interface no disponible en {iface}. "
                             f"Revisa que /etc/wpa_supplicant/wpa_supplicant-{iface}.conf "
                             f"exista y que el servicio esté habilitado."}

    # Limpiar redes ANTES del reset de interfaz — dropea el perfil viejo
    # con la clave incorrecta de un intento previo.
    nets_out = run_cmd(["sudo", "wpa_cli", "-i", iface, "list_networks"])
    for line in nets_out.splitlines():
        parts = line.strip().split("\t")
        if parts and parts[0].isdigit():
            run_cmd(["sudo", "wpa_cli", "-i", iface, "remove_network", parts[0]])
    run_cmd(["sudo", "wpa_cli", "-i", iface, "disconnect"])
    await asyncio.sleep(0.5)

    # Reset interfaz para limpiar estado del driver
    run_cmd(["sudo", "ip", "link", "set", iface, "down"])
    await asyncio.sleep(1)
    run_cmd(["sudo", "ip", "link", "set", iface, "up"])
    await asyncio.sleep(2)

    # Agregar nueva red
    out = run_cmd(["sudo", "wpa_cli", "-i", iface, "add_network"])
    net_id = out.strip().split("\n")[-1].strip()
    if not net_id.isdigit():
        net_id = "0"

    # Configurar — usar hex encoding para SSID con espacios/caracteres especiales
    ssid_hex = ssid.encode('utf-8').hex()
    run_cmd(["sudo", "wpa_cli", "-i", iface, "set_network", net_id, "ssid", ssid_hex])
    if password:
        run_cmd(["sudo", "wpa_cli", "-i", iface, "set_network", net_id, "psk", f'"{password}"'])
        run_cmd(["sudo", "wpa_cli", "-i", iface, "set_network", net_id, "key_mgmt", "WPA-PSK"])
    else:
        run_cmd(["sudo", "wpa_cli", "-i", iface, "set_network", net_id, "key_mgmt", "NONE"])

    if bssid:
        run_cmd(["sudo", "wpa_cli", "-i", iface, "set_network", net_id, "bssid", bssid])

    run_cmd(["sudo", "wpa_cli", "-i", iface, "enable_network", net_id])
    run_cmd(["sudo", "wpa_cli", "-i", iface, "select_network", net_id])

    # Esperar asociación
    for _ in range(30):
        await asyncio.sleep(1)
        out = run_cmd(["iw", "dev", iface, "link"])
        if "Connected to" in out:
            ssid_m = re.search(r"SSID:\s*(.+)", out)
            connected_ssid = (ssid_m.group(1).strip() if ssid_m else "").strip()
            # Accept if SSID matches or if it's the only network we configured
            if connected_ssid == ssid or connected_ssid:
                ip_out = run_cmd(["ip", "addr", "show", iface])
                if "inet " not in ip_out:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "sudo", "dhclient", iface,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL)
                        await asyncio.wait_for(proc.communicate(), timeout=8)
                    except Exception:
                        pass
                # Re-check IP
                ip_out = run_cmd(["ip", "addr", "show", iface])
                ip_m = re.search(r"inet\s+([\d.]+)/", ip_out)
                return {"ok": True, "ssid": connected_ssid, "iface": iface,
                        "ip": ip_m.group(1) if ip_m else None}

    return {"ok": False, "error": f"Timeout — verifica que el AP esté visible y la clave sea correcta"}

@app.post("/api/wifi/disconnect")
async def wifi_disconnect(iface: str = "wlan1"):
    """Desconectar interfaz WiFi"""
    run_cmd(["sudo", "wpa_cli", "-i", iface, "disconnect"])
    run_cmd(["sudo", "wpa_cli", "-i", iface, "remove_network", "all"])
    run_cmd(["sudo", "ip", "addr", "flush", "dev", iface])
    return {"ok": True, "iface": iface}


@app.get("/api/wifi/scan")
async def wifi_scan(iface: str = ""):
    if not iface:
        iface = get_best_wifi_iface()
        if not iface: return {"iface": None, "count": 0, "aps": [], "error": "No WiFi interface found"}
    # Forzar interfaz UP antes de escanear (puede estar DORMANT sin AP)
    run_cmd(["ip", "link", "set", iface, "up"])
    await asyncio.sleep(0.5)
    out = run_cmd(["iw", "dev", iface, "scan"], timeout=20)
    aps = []; cur: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("BSS "):
            if cur.get("bssid"): aps.append(cur)
            cur = {"bssid": line.split()[1].split("(")[0]}
        elif "SSID:" in line: cur["ssid"] = line.split("SSID:")[1].strip()
        elif "signal:" in line:
            m = re.search(r"signal:\s*([-\d.]+)", line)
            cur["signal_dbm"] = float(m.group(1)) if m else None
        elif "freq:" in line:
            m = re.search(r"freq:\s*(\d+)", line)
            if m:
                freq = int(m.group(1)); cur["freq_mhz"] = freq
                cur["band"] = "6GHz" if freq >= 5925 else "5GHz" if freq >= 5000 else "2.4GHz"
        elif "* primary channel:" in line:
            m = re.search(r"primary channel:\s*(\d+)", line)
            cur["channel"] = int(m.group(1)) if m else None
        elif "RSN:" in line or "WPA:" in line:
            cur.setdefault("security", []).append("WPA2" if "RSN:" in line else "WPA")
        elif "capability:" in line and "IBSS" not in line:
            if "ESS" in line: cur.setdefault("security", [])
    if cur.get("bssid"): aps.append(cur)
    return {"iface": iface, "count": len(aps), "aps": aps}

@app.get("/api/wifi/info")
async def wifi_info(iface: str = ""):
    if not iface:
        ifaces = get_interfaces()
        wi = next((i["name"] for i in ifaces if i["type"] == "wifi"), None)
        if not wi: return {"connected": False, "error": "No WiFi interface"}
        iface = wi
    out    = run_cmd(["iw", "dev", iface, "link"])
    ssid_m = re.search(r"SSID:\s*(.+)", out)
    freq_m = re.search(r"freq:\s*(\d+)", out)
    sig_m  = re.search(r"signal:\s*([-\d]+)", out)
    bss_m  = re.search(r"Connected to\s+([0-9a-f:]+)", out, re.IGNORECASE)
    freq   = int(freq_m.group(1)) if freq_m else None
    return {"iface": iface, "ssid": ssid_m.group(1).strip() if ssid_m else None,
            "bssid": bss_m.group(1) if bss_m else None, "freq_mhz": freq,
            "band": "6GHz" if freq and freq>=5925 else "5GHz" if freq and freq>=5000 else "2.4GHz" if freq else None,
            "signal_dbm": int(sig_m.group(1)) if sig_m else None, "connected": "Connected" in out}

# ── WIRED ────────────────────────────────────────────────────
@app.get("/api/wired/lldp")
async def wired_lldp():
    out = run_cmd(["lldpcli", "show", "neighbors", "-f", "json"], timeout=10)
    try: return {"raw": json.loads(out), "ok": True}
    except:
        txt = run_cmd(["lldpcli", "show", "neighbors"], timeout=10)
        return {"raw": txt, "ok": bool(txt), "format": "text"}

@app.get("/api/wired/link")
async def wired_link(iface: str = ""):
    if not iface:
        ifaces = get_interfaces()
        ei = next((i["name"] for i in ifaces if i["type"] == "eth"), None)
        if not ei: return {"error": "No ethernet interface found"}
        iface = ei
    out      = run_cmd(["ethtool", iface])
    speed_m  = re.search(r"Speed:\s*(\S+)", out)
    duplex_m = re.search(r"Duplex:\s*(\S+)", out)
    link_m   = re.search(r"Link detected:\s*(\S+)", out)
    return {"iface": iface, "label": _label(iface),
            "speed": speed_m.group(1) if speed_m else "—",
            "duplex": duplex_m.group(1) if duplex_m else "—",
            "link_up": link_m.group(1).lower() == "yes" if link_m else None}

@app.get("/api/iperf/server/start")
async def iperf_server_start():
    run_cmd(["pkill", "-f", "iperf3 -s"])
    await asyncio.sleep(0.3)
    subprocess.Popen(["iperf3", "-s", "--daemon", "--logfile", "/opt/nekopi/logs/iperf3.log"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "started", "port": 5201}

@app.get("/api/iperf/server/stop")
async def iperf_server_stop():
    run_cmd(["pkill", "-f", "iperf3 -s"])
    return {"status": "stopped"}

@app.get("/api/iperf/client")
async def iperf_client(server: str = Query(...), duration: int = Query(10),
                       port: int = Query(5201), udp: bool = Query(False),
                       interval: int = Query(1), streams: int = Query(1),
                       dir: str = Query("")):
    cmd = ["iperf3", "-c", server, "-p", str(port), "-t", str(duration),
           "-J", "-i", str(interval), "-P", str(streams)]
    if udp: cmd.append("-u")
    if dir == "-R": cmd.append("-R")
    elif dir == "--bidir": cmd.append("--bidir")
    out = run_cmd(cmd, timeout=duration + 15)
    try:
        data = json.loads(out)
        end  = data.get("end", {})
        sent = end.get("sum_sent", {}); recv = end.get("sum_received", {})

        # Per-interval data
        intervals = []
        for iv in data.get("intervals", []):
            s = iv.get("sum", {})
            intervals.append({
                "start":       round(s.get("start", 0), 1),
                "end":         round(s.get("end", 0), 1),
                "mbps":        round(s.get("bits_per_second", 0) / 1e6, 2),
                "retransmits": s.get("retransmits", 0),
                "lost_pct":    round(s.get("lost_percent", 0), 1) if udp else None,
            })

        return {"ok": True, "server": server, "protocol": "UDP" if udp else "TCP",
                "sent_mbps":   round(sent.get("bits_per_second", 0) / 1e6, 2),
                "recv_mbps":   round(recv.get("bits_per_second", 0) / 1e6, 2),
                "retransmits": sent.get("retransmits", 0),
                "intervals":   intervals}
    except:
        return {"ok": False, "error": out or "iperf3 failed", "server": server}

# ── TRACEROUTE ───────────────────────────────────────────────
@app.get("/api/path/trace")
async def path_trace(target: str = Query(...), iface: str = Query(""),
                     max_hops: int = Query(15)):
    import shutil as _sh

    # Prefer mtr — ICMP by default, sees all hops, no root needed for ICMP
    if _sh.which("mtr"):
        # -c 1 = single cycle for fast hop discovery (~3-5s)
        # Real-time RTT updates come from ping_hops endpoint each cycle
        cmd = ["mtr", "-r", "-c", "1", "-n", f"-m{max_hops}"]
        if iface: cmd += ["-I", iface]
        cmd.append(target)
        out = run_cmd(cmd, timeout=30)

        hops = []
        for line in out.splitlines():
            # mtr -r output: "  1.|-- 192.168.50.1    0.0%     3    1.2   0.9   0.7   1.2   0.2"
            m = re.match(
                r"\s*(\d+)\.\|--\s+(\S+)\s+([\d.]+)%\s+\d+\s+([\d.]+)\s+([\d.]+)",
                line
            )
            if not m:
                continue
            hop_n = int(m.group(1))
            ip    = m.group(2)
            loss  = float(m.group(3))
            last  = float(m.group(4))
            avg   = float(m.group(5))
            is_loss = ip in ("???", "?") or loss >= 100.0
            hops.append({
                "hop":      hop_n,
                "ip":       ip if not is_loss else "???",
                "host":     ip if not is_loss else "???",
                "rtt_ms":   avg if not is_loss else None,
                "loss":     is_loss,
                "loss_pct": loss,
                "note":     f"loss {loss:.0f}%" if 0 < loss < 100 else "",
            })
        if hops:
            return {"target": target, "iface": iface or "default", "hops": hops, "raw": out}
        # mtr returned no hops — log raw output and fall through to traceroute
        _log_err = out[:200] if out else "empty output"

    # Fallback: traceroute UDP (no ICMP without root)
    cmd = ["traceroute", "-n", "-q", "3", "-w", "2", f"-m{max_hops}"]
    if iface: cmd.extend(["-i", iface])
    cmd.append(target)
    out = run_cmd(cmd, timeout=60)
    hops = []

    for line in out.splitlines():
        line = line.strip()
        if not line: continue

        # Extraer número de hop al inicio
        hop_m = re.match(r"^\s*(\d+)\s+", line)
        if not hop_m: continue
        hop_n = int(hop_m.group(1))

        # Caso: hop con todos * (timeout completo)
        if re.match(r"^\s*\d+\s+\*\s*\*\s*\*", line):
            hops.append({"hop": hop_n, "ip": "???", "host": "???",
                         "rtt_ms": None, "loss": True, "note": "timeout"})
            continue

        # Extraer todos los pares IP RTT de la línea (soporta ECMP con varias IPs)
        # Formato: IP (hostname)  RTT ms  IP2 (host2)  RTT2 ms  ...
        # o:       IP  RTT ms  RTT2 ms  RTT3 ms
        ip_rtt_pairs = re.findall(
            r"([\d.]+)\s+(?:\([\d.]+\)\s+)?(\d+\.?\d*)\s+ms",
            line
        )
        # También buscar * entre pares
        all_rtts = re.findall(r"(\d+\.?\d*)\s+ms|\*", line[hop_m.end():])

        if ip_rtt_pairs:
            # Usar primera IP como representativa, promediar todos los RTTs
            first_ip = ip_rtt_pairs[0][0]
            all_rtt_vals = [float(p[1]) for p in ip_rtt_pairs]
            # Agregar RTTs sueltos (sin IP) si los hay
            for token in all_rtts:
                if token != '*':
                    try:
                        v = float(token)
                        if v not in all_rtt_vals: all_rtt_vals.append(v)
                    except: pass
            avg_rtt = round(sum(all_rtt_vals) / len(all_rtt_vals), 2) if all_rtt_vals else None
            # Nota si hay múltiples IPs (ECMP)
            ips = [p[0] for p in ip_rtt_pairs]
            note = "ECMP: " + ", ".join(ips) if len(set(ips)) > 1 else ""
            hops.append({
                "hop": hop_n, "ip": first_ip, "host": first_ip,
                "rtt_ms": avg_rtt, "loss": False, "note": note
            })
        else:
            # Solo * en los RTTs pero sin timeout completo
            hops.append({"hop": hop_n, "ip": "???", "host": "???",
                         "rtt_ms": None, "loss": True, "note": "partial timeout"})

    return {"target": target, "iface": iface or "default", "hops": hops, "raw": out}

# ── Streaming Path Analyzer (mtr --raw) ──────────────────────
import threading as _path_th

_PATH = {
    "running": False,
    "proc":    None,
    "target":  "",
    "iface":   "",
    "hops":    {},   # hop_num(int) → {ip, rtts[], loss_count, total}
    "seq":     0,    # increments each update so frontend detects changes
}

def _path_reset():
    _PATH["hops"]    = {}
    _PATH["seq"]     = 0
    _PATH["running"] = False

def _path_parse_raw(proc):
    """Parse mtr --raw output line by line in background thread.
    Format:
      h N IP     → hop N has this IP
      p N USEC   → probe for hop N took USEC microseconds (1ms = 1000 usec)
      d N        → duplicate IP for hop N (ECMP)
    """
    current_ips = {}  # hop_num → ip seen this sweep
    for raw_line in iter(proc.stdout.readline, ""):
        if not _PATH["running"]:
            break
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        kind = parts[0]
        try:
            hop_n = int(parts[1])
        except ValueError:
            continue

        if kind == "h" and len(parts) >= 3:
            ip = parts[2]
            current_ips[hop_n] = ip
            if hop_n not in _PATH["hops"]:
                _PATH["hops"][hop_n] = {
                    "hop": hop_n + 1,  # mtr --raw is 0-indexed
                    "ip":  ip,
                    "rtts": [], "loss_count": 0, "total": 0,
                    "note": "",
                }
            else:
                _PATH["hops"][hop_n]["ip"] = ip

        elif kind == "p" and len(parts) >= 3:
            usec = int(parts[2])
            rtt_ms = round(usec / 1000.0, 2)
            if hop_n in _PATH["hops"]:
                h = _PATH["hops"][hop_n]
                h["rtts"].append(rtt_ms)
                if len(h["rtts"]) > 30:
                    h["rtts"].pop(0)
                h["total"] += 1
                _PATH["seq"] += 1

    _PATH["running"] = False

@app.post("/api/path/start")
async def path_start(target: str = "", iface: str = "", max_hops: int = 15,
                     count: int = 0, interval: int = 1):
    global _PATH
    if _PATH["running"]:
        return {"ok": False, "error": "already running"}
    if not target:
        gw = get_default_gateway()
        target = gw if gw else "8.8.8.8"

    _path_reset()
    _PATH["target"] = target
    _PATH["iface"]  = iface
    _PATH["running"] = True

    # mtr --raw streams results as they arrive.
    # count <= 0  → continuous (-c 0); otherwise -c <count> stops after N probes.
    iv = max(1, int(interval or 1))
    cnt = max(0, int(count or 0))
    cmd = ["mtr", "--raw", "-n", f"-m{max_hops}", "-i", str(iv), "-c", str(cnt), target]
    if iface:
        cmd += ["-I", iface]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1
    )
    _PATH["proc"] = proc

    t = _path_th.Thread(target=_path_parse_raw, args=(proc,), daemon=True)
    t.start()
    return {"ok": True, "target": target}

@app.post("/api/path/stop")
async def path_stop():
    _PATH["running"] = False
    proc = _PATH.get("proc")
    if proc:
        try: proc.terminate()
        except: pass
    return {"ok": True}

@app.get("/api/path/status")
async def path_status():
    raw_hops = []
    for hop_n in sorted(_PATH["hops"].keys()):
        h    = _PATH["hops"][hop_n]
        rtts = h["rtts"]
        avg  = round(sum(rtts) / len(rtts), 2) if rtts else None
        last = rtts[-1] if rtts else None
        loss = round(h["loss_count"] / max(h["total"], 1) * 100) if h["total"] else 0
        raw_hops.append({
            "hop":      h["hop"],
            "ip":       h["ip"],
            "host":     h["ip"],
            "rtt_ms":   last,
            "avg_ms":   avg,
            "loss":     h["ip"] == "???" or last is None,
            "loss_pct": loss,
            "rtts":     rtts[-20:],
            "note":     h.get("note", ""),
        })
    # Collapse consecutive hops that share the same IP — mtr sometimes reports
    # the destination twice when the previous router is the destination itself,
    # which used to show e.g. 8.8.8.8 duplicated at the end of the trace.
    hops_list: list[dict] = []
    for hop in raw_hops:
        if hops_list and hops_list[-1]["ip"] == hop["ip"] and hop["ip"] not in ("???", ""):
            # Keep the latest row's rtt + avg, but update the slot in place
            hops_list[-1] = hop
        else:
            hops_list.append(hop)
    return {
        "running": _PATH["running"],
        "target":  _PATH["target"],
        "hops":    hops_list,
        "seq":     _PATH["seq"],
    }


# ── NETWORK SCAN ─────────────────────────────────────────────
@app.get("/api/scan/network")
async def scan_network(target: str = "192.168.1.0/24"):
    cmd = ["nmap", "-sn", "--open", "-oJ", "-", target]
    out = run_cmd(cmd, timeout=60)
    hosts = []
    try:
        data = json.loads(out)
        for h in data.get("hosts", []):
            addr   = next((a["addr"] for a in h.get("addresses",[]) if a["addrtype"]=="ipv4"), None)
            mac    = next((a["addr"] for a in h.get("addresses",[]) if a["addrtype"]=="mac"), None)
            vendor = next((a.get("vendor","") for a in h.get("addresses",[]) if a["addrtype"]=="mac"), "")
            hn     = h.get("hostnames",[{}])[0].get("name","") if h.get("hostnames") else ""
            hosts.append({"ip": addr, "mac": mac, "vendor": vendor, "hostname": hn, "state": "up"})
    except:
        for line in out.splitlines():
            m = re.search(r"Nmap scan report for (.+?)\s*\(?([\d.]+)\)?$", line)
            if m: hosts.append({"ip": m.group(2), "hostname": m.group(1).strip(), "mac": None, "state": "up"})
    return {"target": target, "count": len(hosts), "hosts": hosts}

# ── ABOUT ────────────────────────────────────────────────────

# ── CLIENT PROFILER — powered by wlanpi-profiler ─────────────
# Credits: WLAN Pi Team · https://github.com/WLAN-Pi/wlanpi-profiler · MIT License

_PROFILER_PROC    = None
_PROFILER_FILES   = "/tmp/nekopi-profiler"
_PROFILER_SEEN    = {}   # mac -> True (already reported as new)

PROFILER_BIN = "/root/.local/bin/profiler"

@app.post("/api/profiler/start")
async def profiler_start(
    iface: str = "wlan1",
    ssid:  str = "NekoPi-Profiler",
    channel: int = 6,
    security: str = "wpa2"
):
    global _PROFILER_PROC, _PROFILER_FILES, _PROFILER_SEEN

    # Stop any running instance
    if _PROFILER_PROC and _PROFILER_PROC.returncode is None:
        try: _PROFILER_PROC.terminate(); await asyncio.sleep(1)
        except: pass
    run_cmd(["sudo", "pkill", "-f", "profiler.*NekoPi"])
    await asyncio.sleep(1)

    _PROFILER_SEEN = {}
    files_path = f"/tmp/nekopi-profiler-{channel}"
    _PROFILER_FILES = files_path
    # Clean old results so we don't show stale data as new
    if os.path.isdir(files_path):
        run_cmd(["sudo", "rm", "-rf", files_path])
    os.makedirs(files_path, exist_ok=True)
    os.chmod(files_path, 0o777)
    for sub in ['clients', 'reports']:
        sd = os.path.join(files_path, sub)
        os.makedirs(sd, exist_ok=True)
        os.chmod(sd, 0o777)

    cmd = [
        "sudo", PROFILER_BIN,
        "-i", iface,
        "-c", str(channel),
        "-s", ssid,
        "--files_path", files_path,
        "--security-mode", security,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        _PROFILER_PROC = proc

        # Wait up to 10s for hostapd to start
        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
            if proc.returncode is not None:
                out = await proc.stdout.read(2000)
                return {"ok": False, "error": out.decode(errors="replace")[-300:]}
            # Check if AP is up
            iw = run_cmd(["iw", "dev", iface, "info"])
            if "type AP" in iw:
                return {"ok": True, "ssid": ssid, "iface": iface, "channel": channel,
                        "files_path": files_path}
        return {"ok": False, "error": "Timeout waiting for AP to start"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/profiler/stop")
async def profiler_stop():
    global _PROFILER_PROC
    if _PROFILER_PROC and _PROFILER_PROC.returncode is None:
        try:
            _PROFILER_PROC.terminate()
            await asyncio.wait_for(_PROFILER_PROC.communicate(), timeout=5)
        except: pass
    run_cmd(["sudo", "pkill", "-f", "profiler.*NekoPi"])
    run_cmd(["sudo", "pkill", "-f", "hostapd.*profiler"])
    await asyncio.sleep(1)
    run_cmd(["sudo", "systemctl", "start", "wpa_supplicant"])
    _PROFILER_PROC = None
    return {"ok": True}

@app.get("/api/profiler/status")
async def profiler_status():
    running = False
    if _PROFILER_PROC and _PROFILER_PROC.returncode is None:
        running = True
    if not running:
        # Check if profiler process still alive
        out = run_cmd(["pgrep", "-f", "profiler.*NekoPi"])
        running = bool(out.strip())
    return {"running": running}

@app.get("/api/profiler/clients")
async def profiler_clients():
    global _PROFILER_SEEN
    results = []
    clients_dir = os.path.join(_PROFILER_FILES, "clients")
    if not os.path.isdir(clients_dir):
        return {"clients": [], "total": 0}

    # Fix permissions on any new files written by root
    try:
        run_cmd(["sudo", "chmod", "-R", "755", clients_dir])
    except: pass

    for mac_dir in os.listdir(clients_dir):
        mac_path = os.path.join(clients_dir, mac_dir)
        if not os.path.isdir(mac_path):
            continue
        # Find JSON file
        for fname in os.listdir(mac_path):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(mac_path, fname)) as f:
                        data = json.load(f)
                    feat = data.get("features", {})
                    mac = data.get("mac", mac_dir).replace("-", ":")
                    is_new = mac not in _PROFILER_SEEN
                    if is_new:
                        _PROFILER_SEEN[mac] = True

                    # Determine standard
                    if feat.get("dot11be", 0) == 1:
                        std = "802.11be (WiFi7)"
                    elif feat.get("dot11ax", 0) == 1:
                        std = "802.11ax (WiFi6)"
                    elif feat.get("dot11ac", 0) == 1:
                        std = "802.11ac (WiFi5)"
                    elif feat.get("dot11n", 0) == 1:
                        std = "802.11n (WiFi4)"
                    else:
                        std = "802.11a/g (legacy)"

                    nss = feat.get("dot11ax_nss") or feat.get("dot11ac_nss") or feat.get("dot11n_nss") or 1
                    mimo = {1:"1x1 SISO",2:"2x2 MIMO",3:"3x3 MIMO",4:"4x4 MIMO"}.get(nss, f"{nss}x{nss}")
                    mcs_str = feat.get("dot11ax_mcs") or feat.get("dot11ac_mcs") or str(feat.get("dot11n_nss",0)*8-1)

                    client = {
                        "new":      is_new,
                        "mac":      mac,
                        "vendor":   data.get("manuf", "Unknown"),
                        "chipset":  data.get("chipset", ""),
                        "standard": std,
                        "mimo":     mimo,
                        "streams":  nss,
                        "mcs":      mcs_str,
                        "band":     "2.4GHz" if data.get("capture_band") == "2" else "5GHz",
                        "channel":  data.get("capture_channel", 0),
                        "dot11k":   feat.get("dot11k", 0),
                        "dot11r":   feat.get("dot11r", -1),
                        "dot11v":   feat.get("dot11v", 0),
                        "dot11w":   feat.get("dot11w", 0),
                        "dot11ax_160": feat.get("dot11ax_160_mhz", 0),
                        "six_ghz":  feat.get("six_ghz_operating_class_supported", 0),
                        "max_power": feat.get("max_power", 0),
                        "channels": feat.get("supported_channels", []),
                        "json":     data,
                        "time":     __import__("datetime").datetime.now().strftime("%H:%M:%S"),
                    }
                    results.append(client)
                except Exception:
                    pass

    return {"clients": results, "total": len(results)}


# ── NAT / INTERNET SHARING ─────────────────────────────────────────────────

@app.get("/api/nat/status")
async def nat_status():
    out = run_cmd(["sudo", "iptables", "-t", "nat", "-L", "POSTROUTING", "-n"])
    fwd = run_cmd(["cat", "/proc/sys/net/ipv4/ip_forward"]).strip()
    enabled = "MASQUERADE" in out and fwd == "1"
    return {"enabled": enabled, "ip_forward": fwd, "masquerade": "MASQUERADE" in out}

@app.post("/api/nat/enable")
async def nat_enable():
    run_cmd(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"])
    run_cmd(["sudo", "iptables", "-P", "FORWARD", "ACCEPT"])
    run_cmd(["sudo", "iptables", "-t", "nat", "-F"])
    run_cmd(["sudo", "iptables", "-F", "FORWARD"])
    run_cmd(["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", "-o", "wlan0", "-j", "MASQUERADE"])
    run_cmd(["sudo", "iptables", "-t", "nat", "-A", "POSTROUTING", "-o", "eth0",  "-j", "MASQUERADE"])
    run_cmd(["sudo", "iptables", "-A", "FORWARD", "-i", "eth1", "-o", "wlan0", "-j", "ACCEPT"])
    run_cmd(["sudo", "iptables", "-A", "FORWARD", "-i", "eth1", "-o", "eth0",  "-j", "ACCEPT"])
    run_cmd(["sudo", "iptables", "-A", "FORWARD", "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
    run_cmd(["sudo", "netfilter-persistent", "save"])
    return {"ok": True, "enabled": True}

@app.post("/api/nat/disable")
async def nat_disable():
    run_cmd(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=0"])
    run_cmd(["sudo", "iptables", "-t", "nat", "-F"])
    run_cmd(["sudo", "iptables", "-F", "FORWARD"])
    run_cmd(["sudo", "iptables", "-P", "FORWARD", "DROP"])
    run_cmd(["sudo", "conntrack", "-F"])  # Kill existing connections
    run_cmd(["sudo", "netfilter-persistent", "save"])
    return {"ok": True, "enabled": False}


# ── WIRED / LAN TOOLS ─────────────────────────────────────────────────────

@app.get("/api/wired/lldp/parsed")
async def wired_lldp_parsed(iface: str = ""):
    """Return LLDP neighbors as structured rows for the UI"""
    if iface:
        raw = run_cmd(["lldpcli", "show", "neighbors", "ports", iface], timeout=10)
    else:
        raw = run_cmd(["lldpcli", "show", "neighbors"], timeout=10)
    rows = []
    if not raw:
        return {"ok": False, "rows": [], "error": "No LLDP data — is lldpd running?"}

    neighbor = {}
    for line in raw.splitlines():
        line = line.strip()
        if "SysName:" in line:
            neighbor["name"] = line.split("SysName:")[1].strip()
        elif "SysDescr:" in line:
            neighbor["descr"] = line.split("SysDescr:")[1].strip()
        elif "PortID:" in line:
            neighbor["remote_port"] = line.split("PortID:")[1].strip()
        elif "MgmtIP:" in line:
            neighbor["mgmt_ip"] = line.split("MgmtIP:")[1].strip()
        elif "Capability:" in line:
            neighbor.setdefault("caps", []).append(line.split("Capability:")[1].strip().split(",")[0])
        elif "VLAN:" in line:
            neighbor["vlan"] = line.split("VLAN:")[1].strip()
        elif "Interface:" in line and "via:" in line:
            m = __import__("re").search(r"Interface:\s+(\S+)", line)
            if m: neighbor["local_port"] = m.group(1)
            via_m = __import__("re").search(r"via:\s+(\S+)", line)
            if via_m: neighbor["protocol"] = via_m.group(1)

    if neighbor.get("name"):
        rows = [
            {"label": "Neighbor",     "value": neighbor.get("name","—"),        "color": "var(--white)"},
            {"label": "Protocol",     "value": neighbor.get("protocol","LLDP"),  "color": "var(--cyan)"},
            {"label": "Platform",     "value": neighbor.get("descr","—")[:60],  "color": "var(--text2)"},
            {"label": "Local port",   "value": neighbor.get("local_port","—"),   "color": "var(--text2)"},
            {"label": "Remote port",  "value": neighbor.get("remote_port","—"),  "color": "var(--cyan)"},
            {"label": "Mgmt IP",      "value": neighbor.get("mgmt_ip","—"),      "color": "var(--blue-b)"},
            {"label": "Capabilities", "value": ", ".join(neighbor.get("caps",[])) or "—", "color": "var(--text2)"},
        ]
        if neighbor.get("vlan"):
            rows.append({"label": "VLAN", "value": neighbor["vlan"], "color": "var(--amber)"})

    return {"ok": bool(rows), "rows": rows, "raw": raw}

@app.get("/api/wired/vlan")
async def wired_vlan(iface: str = "eth0", start: int = 1, end: int = 20):
    """Probe VLANs by creating tagged interfaces and testing connectivity"""
    import asyncio as _asyncio
    found = []
    log = []

    log.append(f"Probing VLANs {start}-{end} on {iface}...")

    # Check which VLANs respond to DHCP or have traffic
    for vid in range(start, min(end+1, start+20)):
        vif = f"{iface}.{vid}"
        # Create VLAN interface
        r1 = run_cmd(["sudo", "ip", "link", "add", "link", iface,
                      "name", vif, "type", "vlan", "id", str(vid)])
        r2 = run_cmd(["sudo", "ip", "link", "set", vif, "up"])
        await _asyncio.sleep(0.3)

        # Quick DHCP discover (just listen for offers)
        dhcp_r = run_cmd(["sudo", "timeout", "1", "dhclient", "-1", "-v", vif], timeout=3)
        active = "bound to" in dhcp_r or "DHCPOFFER" in dhcp_r or "DHCPACK" in dhcp_r

        # Cleanup
        run_cmd(["sudo", "ip", "link", "del", vif])

        status = "active — DHCP responded" if active else "no response"
        color  = "var(--green)" if active else "var(--text2)"
        log.append(f"VLAN {vid}: {status}")
        found.append({"vlan": vid, "active": active, "status": status, "color": color})

    active_vlans = [v for v in found if v["active"]]
    rows = [{"label": f"VLAN {v['vlan']}", "value": v["status"], "color": v["color"]} for v in found]
    rows.append({"label": "Active VLANs", "value": str(len(active_vlans))+" found", "color": "var(--green)" if active_vlans else "var(--amber)"})

    return {"ok": True, "rows": rows, "log": log, "active": len(active_vlans)}

@app.get("/api/wired/blinker")
async def wired_blinker(iface: str = "eth0", duration: int = 10):
    """Blink port LED via ethtool — auto-detect support"""
    import re as _re
    # Check driver support first
    drv_out = run_cmd(["ethtool", "-i", iface])
    drv_m = _re.search(r"driver:\s+(\S+)", drv_out)
    driver = drv_m.group(1) if drv_m else "unknown"

    out = run_cmd(["sudo", "ethtool", "--identify", iface, str(duration)])
    supported = "Operation not supported" not in out and "Cannot" not in out and "error" not in out.lower()

    # Get LLDP port info regardless
    lldp = run_cmd(["lldpcli", "show", "neighbors"], timeout=5)
    port_m  = _re.search(r"PortID:\s+(.+)", lldp)
    name_m  = _re.search(r"SysName:\s+(.+)", lldp)
    remote_port = port_m.group(1).strip() if port_m else "—"
    neighbor    = name_m.group(1).strip() if name_m else "—"

    if supported:
        rows = [
            {"label": "Interface",   "value": iface,                                    "color": "var(--white)"},
            {"label": "Driver",      "value": driver,                                   "color": "var(--text2)"},
            {"label": "Duration",    "value": f"{duration}s",                           "color": "var(--text2)"},
            {"label": "Neighbor",    "value": neighbor,                                 "color": "var(--white)"},
            {"label": "Remote port", "value": remote_port,                              "color": "var(--cyan)"},
            {"label": "Status",      "value": "LED blinking — locate port on switch ✓", "color": "var(--green)"},
        ]
        return {"ok": True, "rows": rows}
    else:
        rows = [
            {"label": "Interface",   "value": iface,                                        "color": "var(--white)"},
            {"label": "Driver",      "value": driver,                                       "color": "var(--text2)"},
            {"label": "LED Blink",   "value": "Not supported by this NIC/driver",           "color": "var(--amber)"},
            {"label": "Neighbor",    "value": neighbor,                                     "color": "var(--white)"},
            {"label": "Remote port", "value": remote_port,                                  "color": "var(--cyan)"},
            {"label": "Alternative", "value": "Use LLDP data above to identify port",       "color": "var(--text2)"},
        ]
        return {"ok": True, "rows": rows, "warning": "LED identify not supported"}

@app.get("/api/wired/dot1x")
async def wired_dot1x(iface: str = "eth0", duration: int = 5):
    """Detect 802.1X EAPOL frames passively"""
    out = run_cmd(["sudo", "timeout", str(duration),
                   "tcpdump", "-i", iface, "-c", "20", "-e", "-n",
                   "ether proto 0x888e"], timeout=duration+3)

    eapol_count = out.count("EAPOL")
    request     = "Request" in out
    identity    = "Identity" in out
    success     = "Success" in out

    if not out or eapol_count == 0:
        rows = [
            {"label": "802.1X",    "value": "No EAPOL frames detected",    "color": "var(--text2)"},
            {"label": "Port mode", "value": "Open / no authentication",    "color": "var(--amber)"},
            {"label": "Duration",  "value": f"Listened {duration}s",       "color": "var(--text2)"},
        ]
        return {"ok": True, "rows": rows, "detected": False}

    rows = [
        {"label": "802.1X",       "value": "EAPOL frames detected",       "color": "var(--green)"},
        {"label": "EAPOL frames", "value": str(eapol_count),              "color": "var(--white)"},
        {"label": "EAP Request",  "value": "Yes" if request else "No",    "color": "var(--green)" if request else "var(--text2)"},
        {"label": "Identity req", "value": "Yes" if identity else "No",   "color": "var(--green)" if identity else "var(--text2)"},
        {"label": "Auth result",  "value": "Success" if success else "In progress", "color": "var(--green)" if success else "var(--amber)"},
        {"label": "Verdict",      "value": "Port requires 802.1X auth",   "color": "var(--cyan)"},
    ]
    return {"ok": True, "rows": rows, "detected": True}

@app.get("/api/wired/dns_benchmark")
async def wired_dns_benchmark(domain: str = "google.com"):
    """Benchmark multiple DNS servers"""
    import time as _time
    servers = [
        ("Local GW",    ""),           # will be filled with gateway
        ("Cloudflare",  "1.1.1.1"),
        ("Google",      "8.8.8.8"),
        ("Quad9",       "9.9.9.9"),
        ("OpenDNS",     "208.67.222.222"),
    ]

    # Get local gateway
    gw_out = run_cmd(["ip", "route", "show", "default"])
    import re as _re
    gw_m = _re.search(r"default via ([\d.]+)", gw_out)
    gw = gw_m.group(1) if gw_m else ""
    if gw:
        servers[0] = ("Local GW", gw)
    else:
        servers = servers[1:]

    results = []
    for name, srv in servers:
        if not srv: continue
        times = []
        for _ in range(3):
            t0 = _time.time()
            r = run_cmd(["dig", f"@{srv}", domain, "+time=2", "+tries=1", "+short"], timeout=3)
            ms = round((_time.time() - t0) * 1000)
            if r and "connection timed out" not in r:
                times.append(ms)
        avg = round(sum(times)/len(times)) if times else 9999
        results.append((name, srv, avg, bool(times)))

    results.sort(key=lambda x: x[2])
    rows = []
    for i, (name, srv, avg, ok) in enumerate(results):
        rank = ["🥇","🥈","🥉"] if i < 3 else [f"#{i+1}"]
        color = "var(--green)" if i==0 else "var(--white)" if i==1 else "var(--text2)"
        rows.append({"label": f"{rank[0] if i<3 else '#'+str(i+1)} {name} ({srv})",
                     "value": f"{avg}ms" if ok else "timeout", "color": color})

    rows.append({"label": "Recommendation",
                 "value": f"Use {results[0][0]} ({results[0][1]}) as primary",
                 "color": "var(--cyan)"})
    return {"ok": True, "rows": rows}

@app.get("/api/wired/voip")
async def wired_voip(target: str = "", iface: str = "eth0", count: int = 100):
    """Simulate VoIP quality test using ping with small packets"""
    if not target:
        gw_out = run_cmd(["ip", "route", "show", "default"])
        import re as _re
        gw_m = _re.search(r"default via ([\d.]+)", gw_out)
        target = gw_m.group(1) if gw_m else "8.8.8.8"

    # Ping with 160 byte packets (G.711 RTP frame size)
    # Use slower interval to avoid false losses from ARP warmup
    out = run_cmd(["ping", "-c", str(count), "-s", "160", "-i", "0.2",
                   "-W", "2", target], timeout=count//2 + 10)

    import re as _re
    loss_m  = _re.search(r"(\d+)% packet loss", out)
    rtt_m   = _re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)

    loss   = float(loss_m.group(1)) if loss_m else 100.0
    avg_ms = float(rtt_m.group(2))  if rtt_m  else 999.0
    mdev   = float(rtt_m.group(4))  if rtt_m  else 999.0  # jitter approx
    # Adjust loss — first ping may have ARP delay, subtract 1 packet if small count
    if loss > 0 and count <= 20:
        adjusted = max(0.0, loss - (100.0/count))
        loss = adjusted

    # MOS estimation (E-model simplified)
    if loss >= 10 or avg_ms >= 400:
        mos, verdict, color = 1.0, "Poor — unusable for VoIP", "var(--red)"
    elif loss >= 5 or avg_ms >= 200 or mdev >= 50:
        mos, verdict, color = 2.5, "Fair — acceptable for some codecs", "var(--amber)"
    elif loss >= 1 or avg_ms >= 100 or mdev >= 20:
        mos, verdict, color = 3.5, "Good — G.729 / G.711 acceptable", "var(--green)"
    else:
        mos, verdict, color = 4.3, "Excellent — VoIP ready", "var(--green)"

    # Check DSCP
    dscp_out = run_cmd(["sudo", "tcpdump", "-i", iface, "-c", "5",
                        "-v", "host", target], timeout=3)
    dscp_val = "EF (46)" if "tos 0xb8" in dscp_out.lower() else "Not marked"

    rows = [
        {"label": "Target",      "value": target,              "color": "var(--text2)"},
        {"label": "MOS Score",   "value": f"{mos} / 5.0",      "color": color},
        {"label": "Latency avg", "value": f"{avg_ms:.1f} ms",  "color": "var(--green)" if avg_ms<100 else "var(--amber)"},
        {"label": "Jitter",      "value": f"{mdev:.1f} ms",    "color": "var(--green)" if mdev<20 else "var(--amber)"},
        {"label": "Packet loss", "value": f"{loss:.1f}%",      "color": "var(--green)" if loss<1 else "var(--red)"},
        {"label": "DSCP",        "value": dscp_val,             "color": "var(--text2)"},
        {"label": "Verdict",     "value": verdict,              "color": color},
    ]
    return {"ok": True, "rows": rows, "mos": mos}

@app.get("/api/wired/dhcp_stress")
async def wired_dhcp_stress(iface: str = "eth0", count: int = 10):
    """DHCP stress test — sends N broadcast DHCP DISCOVERs and aggregates response stats."""
    import time as _time
    import re as _re
    count = max(1, min(int(count or 1), 254))
    log = [f"Sending {count} DHCP DISCOVER on {iface}..."]

    server_ip = offered_ip = lease_time = router = dns = ""
    rtts: list[float] = []
    successes = 0

    for i in range(count):
        t0 = _time.time()
        out = run_cmd(["sudo", "nmap", "--script", "broadcast-dhcp-discover",
                       "-e", iface, "--host-timeout", "5s"], timeout=8)
        dt = (_time.time() - t0) * 1000.0
        ok = ("DHCPOFFER" in out) or ("IP Offered" in out) or ("Server Identifier" in out)
        if ok:
            successes += 1
            rtts.append(dt)
            if not server_ip:
                m = _re.search(r"Server Identifier[:\s]+([\d.]+)", out);   server_ip  = m.group(1) if m else server_ip
                m = _re.search(r"IP Offered[:\s]+([\d.]+)", out);          offered_ip = m.group(1) if m else offered_ip
                m = _re.search(r"IP Address Lease Time[:\s]+(.+)", out);   lease_time = m.group(1).strip() if m else lease_time
                m = _re.search(r"Router[:\s]+([\d.]+)", out);              router     = m.group(1) if m else router
                m = _re.search(r"Domain Name Server[:\s]+([\d., ]+)", out);dns        = m.group(1).strip() if m else dns

    avg = round(sum(rtts)/len(rtts), 1) if rtts else 0
    pmin = round(min(rtts), 1) if rtts else 0
    pmax = round(max(rtts), 1) if rtts else 0
    succ_pct = round(successes / count * 100, 1)
    responded = successes > 0

    color = "var(--green)" if succ_pct >= 90 else "var(--amber)" if succ_pct >= 50 else "var(--red)"
    rows = [
        {"label": "Sent",          "value": str(count),                    "color": "var(--text2)"},
        {"label": "Responses",     "value": f"{successes}/{count} ({succ_pct}%)", "color": color},
        {"label": "DHCP Server",   "value": server_ip or "No response",    "color": "var(--white)" if server_ip else "var(--red)"},
        {"label": "IP Offered",    "value": offered_ip or "—",             "color": "var(--white)"},
        {"label": "Lease Time",    "value": lease_time or "—",             "color": "var(--text2)"},
        {"label": "Router",        "value": router or "—",                 "color": "var(--text2)"},
        {"label": "DNS",           "value": dns or "—",                    "color": "var(--text2)"},
        {"label": "Avg RTT",       "value": f"{avg}ms",                    "color": "var(--green)" if avg<200 else "var(--amber)"},
        {"label": "Min/Max RTT",   "value": f"{pmin}/{pmax}ms",             "color": "var(--text2)"},
        {"label": "Verdict",       "value": "DHCP healthy" if succ_pct >= 90 else ("DHCP degraded" if succ_pct > 0 else "No DHCP response"), "color": color},
    ]
    log.append(f"{successes}/{count} responses · avg {avg}ms")
    return {"ok": responded, "rows": rows, "log": log}


# ── ROAMING ANALYZER ───────────────────────────────────────────────────────

import threading as _threading
import subprocess as _subprocess
import queue as _queue

_ROAM_PROC     = None
_ROAM_EVENTS   = []
_ROAM_CLIENTS  = {}   # mac -> {last_bssid, last_ts, last_rssi}
_ROAM_RUNNING  = False
_ROAM_IFACE    = "wlan1"
_ROAM_SSID     = ""
_ROAM_QUEUE    = _queue.Queue()

def _roam_parse_line(line):
    """Parse tcpdump radiotap output for 802.11 management frames."""
    import re as _re, time as _t

    L = line.upper()
    # Skip beacons (DA=broadcast, no SA)
    if "DA:FF:FF:FF:FF:FF" in L and "\bSA:" not in L and "SA:" not in L:
        return None

    ts    = _t.strftime("%H:%M:%S")
    sig_m = _re.search(r"(-\d+)\s*DBM", line, _re.I)
    rssi  = int(sig_m.group(1)) if sig_m else -99

    bssid_m = _re.search(r"BSSID:([0-9A-Fa-f:]{17})", line)
    sa_m    = _re.search(r"(?:^|\s)SA:([0-9A-Fa-f:]{17})", line)
    da_m    = _re.search(r"(?:^|\s)DA:([0-9A-Fa-f:]{17})", line)
    bssid = bssid_m.group(1).lower() if bssid_m else ""
    sa    = sa_m.group(1).lower()    if sa_m    else ""
    da    = da_m.group(1).lower()    if da_m    else ""

    if not sa:
        return None

    event = None

    if "REASSOC REQ" in L or "ASSOC REQ" in L:
        prev       = _ROAM_CLIENTS.get(sa, {})
        prev_bssid = prev.get("last_bssid", "")
        prev_ts    = prev.get("last_ts", 0)
        ft_ms  = round((_t.time() - prev_ts) * 1000) if prev_ts else 0
        ft_str = f"{ft_ms}ms" if 0 < ft_ms < 30000 else "—"
        ftype  = "802.11r FT" if prev.get("ft_auth") else ("Reassoc" if "REASSOC" in L else "Assoc")
        event  = {"time": ts, "mac": sa,
                  "from_ap": prev_bssid or bssid or "—",
                  "to_ap":   bssid or da or "—",
                  "rssi": rssi, "ft_time": ft_str, "ft_ms": ft_ms,
                  "type": ftype, "raw": line[:100]}
        _ROAM_CLIENTS[sa] = {"last_bssid": bssid, "last_ts": _t.time(), "last_rssi": rssi, "ft_auth": False}

    elif "AUTH" in L:
        is_ft = "FT" in L
        if sa not in _ROAM_CLIENTS: _ROAM_CLIENTS[sa] = {}
        _ROAM_CLIENTS[sa].update({"ft_auth": is_ft, "last_ts": _t.time()})
        event = {"time": ts, "mac": sa,
                 "from_ap": bssid or "—", "to_ap": da or "—",
                 "rssi": rssi, "ft_time": "—", "ft_ms": -1,
                 "type": "Auth FT" if is_ft else "Auth", "raw": line[:100]}

    elif "DEAUTH" in L:
        r_m = _re.search(r"reason\s*[:#]?\s*(\d+)", line, _re.I)
        event = {"time": ts, "mac": sa,
                 "from_ap": bssid or da or "—", "to_ap": "—",
                 "rssi": rssi, "ft_time": "—", "ft_ms": -1,
                 "type": f'Deauth ({r_m.group(1) if r_m else "?"})', "raw": line[:100]}

    elif "ACTION" in L:
        atype = "802.11k" if "NEIGHBOR" in L else "802.11v" if "BSS" in L else "Action"
        event = {"time": ts, "mac": sa,
                 "from_ap": bssid or "—", "to_ap": da or "—",
                 "rssi": rssi, "ft_time": "—", "ft_ms": -1,
                 "type": atype, "raw": line[:100]}

    elif "PROBE REQ" in L:
        # tcpdump format: "Probe Request (SSID_NAME)" or "Probe Request ()" for wildcard
        ssid_m = _re.search(r"Probe Request \(([^)]*)\)", line, _re.I)
        if ssid_m:
            ssid_val = ssid_m.group(1).strip() or "broadcast"
        else:
            ssid_val = "broadcast"
        event = {"time": ts, "mac": sa,
                 "from_ap": "—", "to_ap": ssid_val,
                 "rssi": rssi, "ft_time": "—", "ft_ms": -1,
                 "type": "Probe Req", "raw": line[:100]}

    return event

def _roam_capture_thread(iface, ssid, channel="hop"):
    global _ROAM_RUNNING, _ROAM_EVENTS, _ROAM_CLIENTS
    _ROAM_EVENTS  = []
    _ROAM_CLIENTS = {}

    import subprocess as _sp
    import time as _t

    def _log_event(msg):
        _ROAM_EVENTS.insert(0, {
            "time": _t.strftime("%H:%M:%S"), "mac": "system",
            "from_ap": "—", "to_ap": "—", "rssi": 0,
            "ft_time": "—", "ft_ms": -1, "type": msg, "raw": msg
        })

    # Step 1: Disconnect NetworkManager / wpa_supplicant from this interface
    # so they don't interfere with monitor mode
    _sp.run(["sudo", "nmcli", "device", "disconnect", iface],
            capture_output=True)
    _sp.run(["sudo", "pkill", "-f", f"wpa_supplicant.*{iface}"],
            capture_output=True)
    _t.sleep(0.5)

    # Step 2: Put interface in monitor mode
    _sp.run(["sudo", "ip", "link", "set", iface, "down"],  capture_output=True)
    r = _sp.run(["sudo", "iw", "dev", iface, "set", "type", "monitor"],
                capture_output=True, text=True)
    if r.returncode != 0:
        _log_event(f"⚠ Monitor mode failed: {r.stderr.strip()[:80]}")
        # Try airmon-ng as fallback
        if run_cmd(["which", "airmon-ng"]):
            run_cmd(["sudo", "airmon-ng", "start", iface])
            _log_event(f"↺ Tried airmon-ng on {iface}")
        _ROAM_RUNNING = False
        return

    _sp.run(["sudo", "ip", "link", "set", iface, "up"], capture_output=True)
    _t.sleep(0.3)

    # Verify monitor mode actually set
    check = run_cmd(["iw", "dev", iface, "info"])
    if "monitor" not in check:
        _log_event(f"⚠ Interface {iface} is not in monitor mode — check with: iw dev {iface} info")
        _ROAM_RUNNING = False
        return

    _log_event(f"✓ Monitor mode active on {iface}")

    # Channel hopping or lock
    _hop_stop = _threading.Event()

    if channel == "hop":
        channels_24 = [1, 6, 11]
        channels_5  = [36, 40, 44, 48, 100, 104, 108, 112, 149, 153, 157, 161]
        channels    = channels_24 + channels_5

        def _channel_hop():
            idx = 0
            while not _hop_stop.is_set():
                ch = channels[idx % len(channels)]
                _sp.run(["sudo", "iw", "dev", iface, "set", "channel", str(ch)],
                        capture_output=True)
                idx += 1
                _hop_stop.wait(0.25)

        _threading.Thread(target=_channel_hop, daemon=True).start()
        _log_event("↻ Channel hopping active (2.4+5GHz, 250ms/ch)")
    else:
        # Lock to specific channel
        _sp.run(["sudo", "iw", "dev", iface, "set", "channel", channel],
                capture_output=True)
        _log_event(f"📡 Locked to channel {channel}")

    # Build tcpdump filter — capture all management frames
    # Simpler filter: just "type mgt" captures everything we need
    filt = "type mgt"

    cmd = ["sudo", "tcpdump", "-i", iface, "-e", "-l", "-n",
           "--immediate-mode", "-t",   # -t = no timestamp (we add our own)
           filt]

    proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, bufsize=1)
    _ROAM_QUEUE.put(("proc", proc))

    # Read stderr in background to detect startup errors
    def _read_err():
        for line in proc.stderr:
            line = line.strip()
            if line and "listening on" not in line.lower():
                import time as _t
                _ROAM_EVENTS.insert(0, {
                    "time": _t.strftime("%H:%M:%S"), "mac": "system",
                    "from_ap": "—", "to_ap": "—", "rssi": 0,
                    "ft_time": "—", "ft_ms": -1,
                    "type": f"⚠ {line[:80]}", "raw": line
                })
    _threading.Thread(target=_read_err, daemon=True).start()

    try:
        for line in proc.stdout:
            if not _ROAM_RUNNING:
                break
            line = line.strip()
            if not line:
                continue
            event = _roam_parse_line(line)
            if event:
                _ROAM_EVENTS.insert(0, event)
                if len(_ROAM_EVENTS) > 200:
                    _ROAM_EVENTS = _ROAM_EVENTS[:200]
    except Exception:
        pass
    finally:
        _hop_stop.set()  # Stop channel hopping
        proc.terminate()
        # Restore managed mode
        _sp.run(["sudo", "ip",  "link", "set", iface, "down"],          capture_output=True)
        _sp.run(["sudo", "iw",  "dev",  iface, "set", "type", "managed"], capture_output=True)
        _sp.run(["sudo", "ip",  "link", "set", iface, "up"],            capture_output=True)
        # Reconnect NetworkManager
        _sp.run(["sudo", "nmcli", "device", "connect", iface],           capture_output=True)
        _ROAM_RUNNING = False

@app.post("/api/roaming/start")
async def roaming_start(iface: str = "wlan1", ssid: str = "", channel: str = "hop"):
    global _ROAM_RUNNING, _ROAM_IFACE, _ROAM_SSID
    if _ROAM_RUNNING:
        return {"ok": False, "error": "Already running"}
    _ROAM_RUNNING = True
    _ROAM_IFACE   = iface
    _ROAM_SSID    = ssid
    t = _threading.Thread(target=_roam_capture_thread, args=(iface, ssid, channel), daemon=True)
    t.start()
    await asyncio.sleep(1)
    return {"ok": True, "iface": iface}

@app.post("/api/roaming/stop")
async def roaming_stop():
    global _ROAM_RUNNING
    _ROAM_RUNNING = False
    run_cmd(["sudo", "pkill", "-f", "tcpdump.*type mgt"])
    await asyncio.sleep(1)
    iface = _ROAM_IFACE or ""
    # If a monitor vif (e.g. wlan1mon) was created during capture, drop it
    # before restoring the managed interface — otherwise the orphan vif keeps
    # the radio busy and managed mode fails to come back up cleanly.
    if iface:
        for candidate in (f"{iface}mon", "mon0"):
            run_cmd(["sudo", "iw", "dev", candidate, "del"])  # ignore failures
        run_cmd(["sudo", "ip", "link", "set", iface, "down"])
        run_cmd(["sudo", "iw", "dev", iface, "set", "type", "managed"])
        run_cmd(["sudo", "ip", "link", "set", iface, "up"])
    return {"ok": True}

@app.get("/api/roaming/events")
async def roaming_events(since: int = 0):
    clients = list(set(e["mac"] for e in _ROAM_EVENTS if e.get("mac")))
    stats = {
        "total":   len(_ROAM_EVENTS),
        "roams":   len([e for e in _ROAM_EVENTS if "FT" in e.get("type","") or "Legacy" in e.get("type","")]),
        "deauths": len([e for e in _ROAM_EVENTS if "Deauth" in e.get("type","")]),
        "avg_ft":  0,
    }
    ft_times = [e["ft_ms"] for e in _ROAM_EVENTS if e.get("ft_ms",0) > 0]
    if ft_times:
        stats["avg_ft"] = round(sum(ft_times) / len(ft_times))
    return {
        "running":  _ROAM_RUNNING,
        "events":   _ROAM_EVENTS[:50],
        "clients":  clients,
        "stats":    stats,
    }

@app.get("/api/roaming/status")
async def roaming_status():
    return {"running": _ROAM_RUNNING, "iface": _ROAM_IFACE, "events": len(_ROAM_EVENTS)}


# ── KISMET IDS ─────────────────────────────────────────────────────────────

KISMET_URL  = "http://localhost:2501"
KISMET_USER = "admin"
KISMET_PASS = "admin"
_KISMET_PROC = None

def _kismet_get(path):
    """GET from Kismet API with basic auth"""
    import urllib.request, base64
    url = KISMET_URL + path
    req = urllib.request.Request(url)
    creds = base64.b64encode(f"{KISMET_USER}:{KISMET_PASS}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

@app.get("/api/kismet/url")
async def kismet_url(request: Request):
    """Return real IP URL for Kismet UI — use same IP client is connecting from"""
    # Use the IP the client is connecting to (same interface as NekoPi)
    host = request.headers.get("host", "").split(":")[0]
    if host and host != "localhost" and host != "127.0.0.1":
        return {"url": f"http://{host}:2501", "ip": host}
    # Fallback: eth0
    import re as _re
    ip = run_cmd(["ip", "-4", "addr", "show", "eth0"]) or ""
    match = _re.search(r"inet ([\d.]+)/", ip)  # noqa
    real_ip = match.group(1) if match else "localhost"
    return {"url": f"http://{real_ip}:2501", "ip": real_ip}

@app.post("/api/kismet/start")
async def kismet_start():
    global _KISMET_PROC
    # Check if already running
    status = _kismet_get("/system/status.json")
    if status:
        return {"ok": True, "message": "Already running"}
    # Start kismet as daemon
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "kismet", "--daemonize", "--no-ncurses",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        # Wait up to 15s for Kismet to start
        for _ in range(15):
            await asyncio.sleep(1)
            status = _kismet_get("/system/status.json")
            if status:
                return {"ok": True}
        return {"ok": False, "error": "Kismet started but API not responding after 15s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/kismet/stop")
async def kismet_stop():
    run_cmd(["sudo", "killall", "-9", "kismet"])
    run_cmd(["sudo", "killall", "-9", "kismet_cap_linux_wifi"])
    await asyncio.sleep(0.5)
    return {"ok": True}

@app.get("/api/kismet/summary")
async def kismet_summary():
    status = _kismet_get("/system/status.json")
    if not status:
        return {"running": False}

    total = status.get("kismet.system.devices.count", 0)

    # Get devices list
    devs_raw = _kismet_get("/devices/views/all/devices.json?fields=kismet.device.base.macaddr,kismet.device.base.name,kismet.device.base.manuf,kismet.device.base.type,kismet.device.base.signal,kismet.device.base.channel&sort=signal&limit=15")

    top_devices = []
    aps = 0
    clients = 0
    if devs_raw and isinstance(devs_raw, list):
        for d in devs_raw:
            dtype = d.get("kismet.device.base.type", "")
            if "AP" in dtype or "Access Point" in dtype: aps += 1
            elif "Client" in dtype: clients += 1
            sig = 0
            sig_data = d.get("kismet.device.base.signal", {})
            if isinstance(sig_data, dict):
                sig = sig_data.get("kismet.common.signal.last_signal", 0)
            top_devices.append({
                "mac":     d.get("kismet.device.base.macaddr", "??:??:??:??:??:??"),
                "ssid":    d.get("kismet.device.base.name", ""),
                "manuf":   d.get("kismet.device.base.manuf", "Unknown"),
                "type":    dtype or "Device",
                "signal":  sig,
                "channel": str(d.get("kismet.device.base.channel", "—")),
            })

    # Get alerts
    alerts_raw = _kismet_get("/alerts/last-time/0/alerts.json") or []
    alert_list = []
    if isinstance(alerts_raw, list):
        for a in alerts_raw[:10]:
            alert_list.append({
                "type": a.get("kismet.alert.class", "ALERT"),
                "text": a.get("kismet.alert.text", ""),
                "time": __import__("datetime").datetime.fromtimestamp(
                    a.get("kismet.alert.timestamp", 0)
                ).strftime("%H:%M:%S") if a.get("kismet.alert.timestamp") else "—"
            })

    # Uptime
    ts_start = status.get("kismet.system.timestamp.start_sec", 0)
    ts_now   = status.get("kismet.system.timestamp.sec", 0)
    uptime_s = ts_now - ts_start
    uptime   = f"{uptime_s//60}m {uptime_s%60}s" if uptime_s > 0 else "—"

    return {
        "running":     True,
        "devices":     total,
        "aps":         aps,
        "clients":     clients,
        "alerts":      len(alert_list),
        "uptime":      uptime,
        "top_devices": top_devices,
        "alert_list":  alert_list,
    }


# ── SECURITY AUDIT ─────────────────────────────────────────────────────────

import threading as _sec_threading

_SEC_RUNNING    = False
_SEC_PROGRESS   = 0
_SEC_STATUS     = "idle"
_SEC_FINDINGS   = []
_SEC_HOSTS      = []   # [{ip, name, ports:{ssh,telnet,ftp,...}, has_issues}]
_SEC_SCORE      = 100
_SEC_SUMMARY    = {}
_SEC_START_TIME = 0.0  # epoch seconds when audit started

# Default credentials database
# Default credentials database — vendor-specific, 1-2 attempts max per host
# This is standard audit practice (same as Nessus/OpenVAS), NOT brute force.
# Credentials are publicly documented by manufacturers.
_DEFAULT_CREDS = [
    # ── Cisco ────────────────────────────────────────────────────────
    {"vendor": "Cisco IOS",          "ports": [23, 22],       "user": "cisco",        "pass": "cisco"},
    {"vendor": "Cisco IOS",          "ports": [23, 22],       "user": "admin",        "pass": "admin"},
    {"vendor": "Cisco IOS",          "ports": [23, 22],       "user": "enable",       "pass": ""},
    {"vendor": "Cisco RV series",    "ports": [443, 80],      "user": "cisco",        "pass": "cisco"},
    {"vendor": "Cisco RV series",    "ports": [443, 80],      "user": "admin",        "pass": "admin"},
    {"vendor": "Cisco Meraki",       "ports": [443, 80],      "user": "admin",        "pass": ""},
    {"vendor": "Cisco ASA",          "ports": [443, 22],      "user": "enable",       "pass": ""},
    {"vendor": "Cisco ASA",          "ports": [443, 22],      "user": "cisco",        "pass": "cisco"},
    {"vendor": "Cisco WLC",          "ports": [443, 80],      "user": "admin",        "pass": "admin"},
    {"vendor": "Cisco WLC",          "ports": [443, 80],      "user": "admin",        "pass": ""},
    {"vendor": "Cisco SG series",    "ports": [80, 443],      "user": "cisco",        "pass": "cisco"},

    # ── Mikrotik ─────────────────────────────────────────────────────
    {"vendor": "Mikrotik",           "ports": [8291, 80, 443],"user": "admin",        "pass": ""},
    {"vendor": "Mikrotik",           "ports": [8291, 80, 443],"user": "admin",        "pass": "admin"},

    # ── Ubiquiti ─────────────────────────────────────────────────────
    {"vendor": "Ubiquiti UniFi",     "ports": [443, 80],      "user": "ubnt",         "pass": "ubnt"},
    {"vendor": "Ubiquiti UniFi",     "ports": [443, 80],      "user": "admin",        "pass": "ubnt"},
    {"vendor": "Ubiquiti AirOS",     "ports": [443, 80],      "user": "ubnt",         "pass": "ubnt"},
    {"vendor": "Ubiquiti AirOS",     "ports": [443, 80],      "user": "admin",        "pass": ""},

    # ── TP-Link ──────────────────────────────────────────────────────
    {"vendor": "TP-Link",            "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "TP-Link",            "ports": [80, 443],      "user": "admin",        "pass": ""},
    {"vendor": "TP-Link",            "ports": [80, 443],      "user": "admin",        "pass": "tplink"},

    # ── Tenda / D-Link / Netgear ─────────────────────────────────────
    {"vendor": "Tenda",              "ports": [80],           "user": "admin",        "pass": "admin"},
    {"vendor": "D-Link",             "ports": [80, 443],      "user": "Admin",        "pass": ""},
    {"vendor": "D-Link",             "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "Netgear",            "ports": [80, 443],      "user": "admin",        "pass": "password"},
    {"vendor": "Netgear",            "ports": [80, 443],      "user": "admin",        "pass": "1234"},

    # ── Hikvision / Dahua / Axis / Reolink (cámaras IP) ─────────────
    {"vendor": "Hikvision",          "ports": [80, 8080],     "user": "admin",        "pass": "12345"},
    {"vendor": "Hikvision",          "ports": [80, 8080],     "user": "admin",        "pass": "admin"},
    {"vendor": "Dahua",              "ports": [80, 37777],    "user": "admin",        "pass": "admin"},
    {"vendor": "Dahua",              "ports": [80, 37777],    "user": "888888",       "pass": "888888"},
    {"vendor": "Axis",               "ports": [80, 443],      "user": "root",         "pass": "pass"},
    {"vendor": "Axis",               "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "Reolink",            "ports": [80, 8080],     "user": "admin",        "pass": ""},

    # ── HP / Aruba ───────────────────────────────────────────────────
    {"vendor": "HP ProCurve",        "ports": [23, 22, 80],   "user": "manager",      "pass": ""},
    {"vendor": "HP ProCurve",        "ports": [23, 22, 80],   "user": "operator",     "pass": ""},
    {"vendor": "HP Aruba",           "ports": [22, 443],      "user": "admin",        "pass": "aruba"},
    {"vendor": "HP Aruba",           "ports": [22, 443],      "user": "admin",        "pass": "admin"},

    # ── Zyxel / Huawei / ZTE ────────────────────────────────────────
    {"vendor": "Zyxel",              "ports": [80, 443],      "user": "admin",        "pass": "1234"},
    {"vendor": "Zyxel",              "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "Huawei",             "ports": [80, 22],       "user": "admin",        "pass": "Admin@huawei"},
    {"vendor": "Huawei",             "ports": [80, 22],       "user": "root",         "pass": "admin"},
    {"vendor": "Huawei",             "ports": [80, 22],       "user": "admin",        "pass": "Huawei@123"},
    {"vendor": "ZTE",                "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "ZTE",                "ports": [80, 443],      "user": "zte",          "pass": "zte"},

    # ── Fortinet / pfSense / SonicWall ──────────────────────────────
    {"vendor": "Fortinet FortiGate", "ports": [443, 80],      "user": "admin",        "pass": ""},
    {"vendor": "SonicWall",          "ports": [443, 80],      "user": "admin",        "pass": "password"},
    {"vendor": "pfSense",            "ports": [443, 80],      "user": "admin",        "pass": "pfsense"},

    # ── Impresoras ───────────────────────────────────────────────────
    {"vendor": "HP Printer",         "ports": [80, 443],      "user": "admin",        "pass": ""},
    {"vendor": "HP Printer",         "ports": [80, 443],      "user": "admin",        "pass": "admin"},
    {"vendor": "Canon Printer",      "ports": [80],           "user": "ADMIN",        "pass": "canon"},
    {"vendor": "Ricoh",              "ports": [80],           "user": "admin",        "pass": ""},
    {"vendor": "Xerox",              "ports": [80, 443],      "user": "admin",        "pass": "1111"},

    # ── Genéricos / Legacy ───────────────────────────────────────────
    {"vendor": "Generic Telnet",     "ports": [23],           "user": "admin",        "pass": "admin"},
    {"vendor": "Generic Telnet",     "ports": [23],           "user": "root",         "pass": "root"},
    {"vendor": "Generic Telnet",     "ports": [23],           "user": "user",         "pass": "user"},
    {"vendor": "Generic FTP",        "ports": [21],           "user": "anonymous",    "pass": ""},
    {"vendor": "Generic FTP",        "ports": [21],           "user": "ftp",          "pass": "ftp"},
]

# OUI prefix → vendor name (first 6 hex chars of MAC, no separators, uppercase)
_OUI_MAP = {
    # Cisco
    "001013": "Cisco", "0010F6": "Cisco", "001E13": "Cisco", "0021A0": "Cisco",
    "002689": "Cisco", "4C5E0C": "Cisco", "885A92": "Cisco", "A0F8A7": "Cisco",
    "B4A4E3": "Cisco", "C8D719": "Cisco", "D4E880": "Cisco", "F80277": "Cisco",
    # Mikrotik
    "4C5E0C": "Mikrotik", "6C3B6B": "Mikrotik", "B8690E": "Mikrotik",
    "CC2D83": "Mikrotik", "D4CA6D": "Mikrotik", "E4D3F1": "Mikrotik",
    # Ubiquiti
    "002722": "Ubiquiti", "0418D6": "Ubiquiti", "246895": "Ubiquiti",
    "44D9E7": "Ubiquiti", "68722D": "Ubiquiti", "788A20": "Ubiquiti",
    "B4FBE4": "Ubiquiti", "DC9FDB": "Ubiquiti", "F09FC2": "Ubiquiti",
    "FCECDA": "Ubiquiti",
    # TP-Link
    "1C61B4": "TP-Link",  "50FA84": "TP-Link",  "6466B3": "TP-Link",
    "A42BB0": "TP-Link",  "B0487A": "TP-Link",  "D86095": "TP-Link",
    "F81A67": "TP-Link",
    # Hikvision
    "4457AD": "Hikvision","B0C554": "Hikvision","C0563E": "Hikvision",
    "C45006": "Hikvision","D80D17": "Hikvision",
    # Dahua
    "3CB72B": "Dahua",    "908D78": "Dahua",    "E0501E": "Dahua",
    # HP / Aruba
    "001083": "HP ProCurve","3CAEF6": "HP ProCurve","6C4E2B": "HP Aruba",
    "9C8CD8": "HP Aruba", "AC7F3E": "HP Aruba",
    # Huawei
    "001E10": "Huawei",   "0026CB": "Huawei",   "286ED4": "Huawei",
    "4C8BAA": "Huawei",   "5488E2": "Huawei",   "8C0D76": "Huawei",
    "D440F0": "Huawei",   "F8E811": "Huawei",
    # Fortinet
    "000C29": "Fortinet", "0800277": "Fortinet","00090F": "Fortinet",
    "70780B": "Fortinet",
}

# HTTP banner keywords → vendor
_HTTP_BANNER_MAP = [
    ("mikrotik",          "Mikrotik"),
    ("routeros",          "Mikrotik"),
    ("hikvision",         "Hikvision"),
    ("dvr login",         "Hikvision"),
    ("dahua",             "Dahua"),
    ("ubiquiti",          "Ubiquiti"),
    ("unifi",             "Ubiquiti"),
    ("airos",             "Ubiquiti AirOS"),
    ("fortinet",          "Fortinet FortiGate"),
    ("fortigate",         "Fortinet FortiGate"),
    ("cisco",             "Cisco"),
    ("meraki",            "Cisco Meraki"),
    ("aruba",             "HP Aruba"),
    ("procurve",          "HP ProCurve"),
    ("tp-link",           "TP-Link"),
    ("d-link",            "D-Link"),
    ("netgear",           "Netgear"),
    ("zyxel",             "Zyxel"),
    ("huawei",            "Huawei"),
    ("pfsense",           "pfSense"),
    ("sonicwall",         "SonicWall"),
    ("canon",             "Canon Printer"),
    ("ricoh",             "Ricoh"),
    ("xerox",             "Xerox"),
    ("hp laserjet",       "HP Printer"),
    ("hewlett-packard",   "HP Printer"),
]

def _guess_vendor(ip: str, open_ports: list) -> str:
    """
    Heuristic vendor detection — tries ARP OUI first, then HTTP banner.
    Returns vendor string matching _DEFAULT_CREDS, or '' if unknown.
    Only 1-2 creds will be tried for the detected vendor.
    """
    import re as _re

    # 1. ARP OUI lookup (only works on same L2 segment — ideal for NekoPi)
    try:
        arp_out = run_cmd(["arp", "-n", ip], timeout=3)
        mac_m = _re.search(r"((?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2})", arp_out)
        if mac_m:
            oui = mac_m.group(1).upper().replace(":", "").replace("-", "")[:6]
            if oui in _OUI_MAP:
                return _OUI_MAP[oui]
    except Exception:
        pass

    # 2. HTTP banner (port 80 / 8080 / 443 quick grab)
    http_ports = [p["port"] for p in open_ports if p["port"] in (80, 8080, 8443, 443)]
    for port in http_ports[:2]:
        scheme = "https" if port in (443, 8443) else "http"
        try:
            body = run_cmd([
                "curl", "-sk", "--max-time", "3", "--connect-timeout", "2",
                "-L", "--max-redirs", "2",
                f"{scheme}://{ip}:{port}/"
            ], timeout=5)
            body_lower = body.lower()[:1000]
            for keyword, vendor in _HTTP_BANNER_MAP:
                if keyword in body_lower:
                    return vendor
        except Exception:
            pass

    # 3. Telnet banner (quick 2s grab)
    if any(p["port"] == 23 for p in open_ports):
        try:
            import socket as _sock
            s = _sock.create_connection((ip, 23), timeout=2)
            banner = s.recv(512).decode(errors="ignore").lower()
            s.close()
            for keyword, vendor in _HTTP_BANNER_MAP:
                if keyword in banner:
                    return vendor
            if banner:  # Has banner but unknown vendor
                return "Generic Telnet"
        except Exception:
            pass

    return ""

# Risky ports with descriptions
_RISKY_PORTS = {
    21:   {"name": "FTP",     "severity": "high",     "desc": "File transfer unencrypted — credentials exposed"},
    23:   {"name": "Telnet",  "severity": "critical", "desc": "Remote access unencrypted — full credential exposure"},
    69:   {"name": "TFTP",    "severity": "high",     "desc": "Trivial FTP — no authentication"},
    80:   {"name": "HTTP",    "severity": "medium",   "desc": "Web interface unencrypted"},
    161:  {"name": "SNMP",    "severity": "high",     "desc": "SNMP exposed — check community string"},
    445:  {"name": "SMB",     "severity": "high",     "desc": "File sharing — check for EternalBlue"},
    512:  {"name": "rexec",   "severity": "critical", "desc": "Remote exec — legacy auth"},
    513:  {"name": "rlogin",  "severity": "critical", "desc": "Remote login — no encryption"},
    514:  {"name": "rsh",     "severity": "critical", "desc": "Remote shell — no encryption"},
    1900: {"name": "UPnP",    "severity": "medium",   "desc": "UPnP exposed — potential NAT bypass"},
    2323: {"name": "Telnet",  "severity": "critical", "desc": "Alternate Telnet port"},
    4444: {"name": "Metasploit", "severity": "critical", "desc": "Known malware/backdoor port"},
    5555: {"name": "ADB",     "severity": "critical", "desc": "Android Debug Bridge exposed"},
    6666: {"name": "IRC",     "severity": "high",     "desc": "IRC — potential C2 channel"},
    8080: {"name": "HTTP-alt","severity": "medium",   "desc": "Alternate HTTP — check for admin panel"},
    8443: {"name": "HTTPS-alt","severity": "low",     "desc": "Alternate HTTPS"},
    9200: {"name": "Elasticsearch","severity":"critical","desc":"Database exposed without auth"},
    27017:{"name": "MongoDB", "severity": "critical", "desc": "Database likely exposed without auth"},
}

def _sec_add_finding(severity, title, host, detail, recommendation, cve=None):
    _SEC_FINDINGS.append({
        "severity":       severity,
        "title":          title,
        "host":           host,
        "detail":         detail,
        "recommendation": recommendation,
        "cve":            cve,
        "ts":             __import__("time").strftime("%H:%M:%S"),
    })

def _sec_score_deduct(severity):
    global _SEC_SCORE
    deduct = {"critical": 20, "high": 10, "medium": 5, "low": 2, "info": 0}
    _SEC_SCORE = max(0, _SEC_SCORE - deduct.get(severity, 0))

def _run_security_audit(subnet, wifi_iface, ssid_filter: str = "", vendor_override: str = ""):
    global _SEC_RUNNING, _SEC_PROGRESS, _SEC_STATUS, _SEC_FINDINGS, _SEC_HOSTS, _SEC_SCORE, _SEC_SUMMARY, _SEC_START_TIME
    import re as _re, subprocess as _sp, json as _json, time as _time

    _SEC_FINDINGS   = []
    _SEC_HOSTS      = []
    _SEC_SCORE      = 100
    _SEC_PROGRESS   = 0
    _SEC_STATUS     = "running"
    _SEC_START_TIME = _time.time()

    # Parse ssid_filter: comma-separated list of client SSIDs to scope the WiFi audit
    # If empty → scan all visible (includes neighbors, less useful)
    client_ssids = set()
    if ssid_filter.strip():
        client_ssids = {s.strip() for s in ssid_filter.split(",") if s.strip()}

    try:
        # ── PHASE 1: Host Discovery ──────────────────────────────
        _SEC_STATUS   = "Phase 1/4 — Host Discovery"
        _SEC_PROGRESS = 5

        ping_scan = run_cmd(["sudo", "nmap", "-sn", "--host-timeout", "5s", subnet], timeout=30)
        hosts = _re.findall(r"Nmap scan report for (?:\S+ \()?(\d+\.\d+\.\d+\.\d+)\)?", ping_scan)
        host_names = {}
        host_mac    = {}   # ip → MAC address
        host_vendor = {}   # ip → OUI vendor

        for m in _re.finditer(r"Nmap scan report for (\S+) \((\d+\.\d+\.\d+\.\d+)\)", ping_scan):
            host_names[m.group(2)] = m.group(1)

        # Extract MAC+vendor from nmap output (available for same-subnet hosts)
        for m in _re.finditer(
            r"Nmap scan report for .*?(\d+\.\d+\.\d+\.\d+).*?MAC Address: ([0-9A-F:]{17})\s+\(([^)]*)\)",
            ping_scan, _re.DOTALL
        ):
            host_mac[m.group(1)]    = m.group(2).lower()
            host_vendor[m.group(1)] = m.group(3) or "Unknown"

        # Supplement with kernel ARP table for any hosts nmap missed
        arp_out = run_cmd(["arp", "-n"])
        for line in arp_out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and _re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
                ip  = parts[0]
                mac = parts[2]
                if mac and mac != "<incomplete>" and ip not in host_mac:
                    host_mac[ip] = mac

        _SEC_PROGRESS = 15
        _SEC_SUMMARY["hosts_found"] = len(hosts)

        # ── PHASE 2: Port Scan — todos los hosts en paralelo ────────
        # Una sola llamada nmap sobre toda la lista de hosts.
        # nmap gestiona el paralelismo internamente (-T4 = aggressive).
        # Esto es exactamente como MobaXterm: scan rápido → tabla se llena sola.
        _SEC_STATUS   = "Phase 2/4 — Port scan (all hosts parallel)"
        _SEC_PROGRESS = 20

        _PORT_LABELS = {
            22: "ssh", 23: "telnet", 21: "ftp", 80: "http", 443: "https",
            161: "snmp", 3389: "rdp", 8080: "http_alt", 8443: "https_alt",
            25: "smtp", 445: "smb", 512: "rexec", 513: "rlogin", 514: "rsh",
        }
        PORT_LIST = "21,22,23,25,80,110,135,139,161,443,445,512,513,514,3389,8080,8443,8291"

        # Inicializar tabla con todos los hosts descubiertos (sin puertos aún)
        # El frontend ya los muestra con ✕ mientras llega el scan
        host_data = {}
        for host in hosts[:30]:
            _SEC_HOSTS.append({
                "ip":      host,
                "name":    host_names.get(host, ""),
                "mac":     host_mac.get(host, ""),
                "vendor":  host_vendor.get(host, ""),
                "ports":   {}, "has_issues": False, "scanning": True,
            })
            host_data[host] = {"ports": [], "name": host_names.get(host, host)}

        # ── Paso 1: TCP connect scan sobre TODOS los hosts a la vez ──
        # -sT  = TCP connect, no root needed
        # -T4  = aggressive timing (reduce timeouts)
        # --open = solo puertos abiertos en output
        # -oG - = greppable output, más fácil de parsear por host
        _SEC_PROGRESS = 25
        all_hosts_arg = hosts[:30]  # nmap acepta lista de IPs directamente

        port_scan_out = run_cmd(
            ["nmap", "-sT", "-T4", "--open",
             "-p", PORT_LIST,
             "--host-timeout", "10s",
             "-oG", "-",          # greppable output
             "--min-parallelism", "20",
             "--max-parallelism", "100",
             ] + all_hosts_arg,
            timeout=120            # 2 min máximo para toda la subnet
        )

        # Parsear salida greppable: cada línea de host tiene todos sus puertos
        # Formato: Host: 192.168.1.1 (_gateway)  Ports: 22/open/tcp//ssh///, 80/open/tcp//http///
        open_by_host = {}  # ip → {port: {svc, state}}
        for line in port_scan_out.splitlines():
            if not line.startswith("Host:"):
                continue
            host_m = _re.search(r"Host:\s+(\d+\.\d+\.\d+\.\d+)", line)
            ports_m = _re.search(r"Ports:\s+(.+?)(?:\s+Ignored|$)", line)
            if not host_m:
                continue
            ip = host_m.group(1)
            # Update hostname if nmap resolved it
            name_m = _re.search(r"\(([^)]+)\)", line.split("Ports:")[0] if "Ports:" in line else line)
            if name_m and name_m.group(1) != ip:
                host_names[ip] = name_m.group(1)

            open_by_host[ip] = {}
            if ports_m:
                for port_entry in ports_m.group(1).split(","):
                    parts = port_entry.strip().split("/")
                    if len(parts) >= 3 and parts[1] == "open":
                        pnum = int(parts[0])
                        svc  = parts[4] if len(parts) > 4 else ""
                        open_by_host[ip][pnum] = {"service": svc, "version": ""}

        _SEC_PROGRESS = 50

        # ── Paso 2: Service version SOLO en hosts con puertos abiertos ──
        # Una segunda pasada, también paralela pero solo sobre los hosts activos
        hosts_with_ports = [ip for ip, ports in open_by_host.items() if ports]
        if hosts_with_ports:
            _SEC_STATUS = f"Phase 2/4 — Service detection ({len(hosts_with_ports)} hosts)"
            # Construir lista de puertos únicos abiertos en toda la red
            all_open_ports = set()
            for ports in open_by_host.values():
                all_open_ports.update(ports.keys())

            svc_out = run_cmd(
                ["nmap", "-sT", "-sV", "--version-light", "-T4",
                 "-p", ",".join(str(p) for p in sorted(all_open_ports)),
                 "--host-timeout", "12s",
                 "-oG", "-",
                 "--min-parallelism", "10",
                 ] + hosts_with_ports,
                timeout=90
            )

            # Actualizar versiones con la segunda pasada
            for line in svc_out.splitlines():
                if not line.startswith("Host:"):
                    continue
                host_m = _re.search(r"Host:\s+(\d+\.\d+\.\d+\.\d+)", line)
                ports_m = _re.search(r"Ports:\s+(.+?)(?:\s+Ignored|$)", line)
                if not host_m or not ports_m:
                    continue
                ip = host_m.group(1)
                if ip not in open_by_host:
                    open_by_host[ip] = {}
                for port_entry in ports_m.group(1).split(","):
                    parts = port_entry.strip().split("/")
                    if len(parts) >= 3 and parts[1] == "open":
                        pnum = int(parts[0])
                        svc  = parts[4] if len(parts) > 4 else ""
                        ver  = parts[6] if len(parts) > 6 else ""
                        if pnum in open_by_host.get(ip, {}):
                            open_by_host[ip][pnum]["service"] = svc
                            open_by_host[ip][pnum]["version"] = ver

        _SEC_PROGRESS = 58

        # ── Construir host_data y _SEC_HOSTS con resultados completos ──
        for host in hosts[:30]:
            port_flags = {}
            open_ports = []
            host_findings_count = 0
            ports_found = open_by_host.get(host, {})

            for port, info in ports_found.items():
                svc = info.get("service", "")
                ver = info.get("version", "")
                label = _PORT_LABELS.get(port, f"p{port}")
                risk  = None
                open_ports.append({"port": port, "service": svc, "version": ver})

                if port in _RISKY_PORTS:
                    rp   = _RISKY_PORTS[port]
                    risk = rp["severity"]
                    _sec_add_finding(
                        rp["severity"],
                        f"{rp['name']} open on {host_names.get(host, host)}",
                        host,
                        f"Port {port}/{rp['name']} — {ver or rp['desc']}",
                        f"Disable {rp['name']} or restrict with ACL",
                    )
                    _sec_score_deduct(rp["severity"])
                    host_findings_count += 1

                port_flags[label] = {"open": True, "version": ver, "risk": risk}

            host_data[host] = {"ports": open_ports, "name": host_names.get(host, host)}

            # Actualizar entrada existente en _SEC_HOSTS (ya fue inicializada arriba)
            entry = {
                "ip":         host,
                "name":       host_names.get(host, ""),
                "mac":        host_mac.get(host, ""),
                "vendor":     host_vendor.get(host, ""),
                "ports":      port_flags,
                "has_issues": host_findings_count > 0,
                "scanning":   False,
            }
            idx = next((i for i, h in enumerate(_SEC_HOSTS) if h["ip"] == host), None)
            if idx is not None:
                _SEC_HOSTS[idx] = entry
            else:
                _SEC_HOSTS.append(entry)

        _SEC_SUMMARY["hosts_scanned"] = len(host_data)

        # ── PHASE 3: WiFi Audit ───────────────────────────────────
        _SEC_STATUS   = "Phase 3/4 — WiFi Security Audit"
        _SEC_PROGRESS = 60

        if wifi_iface != "none":
            wifi_out = run_cmd(["sudo", "iw", "dev", wifi_iface, "scan"], timeout=15)
            seen_ssids = {}
            open_nets  = []
            weak_enc   = []

            # Split into per-BSS blocks. iw uses BOTH "BSS aa:bb:.." (start of
            # line) AND "BSS Load:" / "BSS Transition" (tab-indented IEs) so a
            # naive split("BSS ") shatters each block and the RSN/WPA IEs fall
            # into the wrong chunks — that misclassifies WPA2/WPA3 nets as WEP.
            blocks = _re.split(r"(?m)^BSS\s+(?=[0-9a-f:]{17})", wifi_out)
            for block in blocks:
                bssid_m = _re.match(r"([0-9a-f:]{17})", block)
                ssid_m  = _re.search(r"SSID:\s*(.+)", block)
                if not bssid_m or not ssid_m: continue
                bssid = bssid_m.group(1)
                ssid  = ssid_m.group(1).strip()
                if not ssid or ssid == "\x00": continue

                # Apply SSID filter — skip SSIDs not in client scope
                if client_ssids and ssid not in client_ssids:
                    continue

                cap_m    = _re.search(r"capability:.*", block)
                has_priv = bool(cap_m and "Privacy" in cap_m.group(0))
                # Robust detection — iw output spacing varies between releases.
                # WPA3 = any SAE/OWE auth suite under RSN.
                has_wpa3 = bool(_re.search(r"\bSAE\b|Authentication suites:.*SAE", block, _re.I)) \
                           or "OWE" in block
                # WPA2 = any RSN information element. Match "RSN:", "RSN " or just an
                # "RSN Information" header — all current iw releases emit one of these.
                has_wpa2 = bool(_re.search(r"\bRSN(?:\s+Information)?\s*:", block)) \
                           or "Group cipher:" in block and "Pairwise ciphers:" in block
                has_wpa  = bool(_re.search(r"\bWPA\s*:", block))
                has_wep  = has_priv and not has_wpa3 and not has_wpa2 and not has_wpa
                is_open  = not has_priv

                if is_open:
                    open_nets.append({"ssid": ssid, "bssid": bssid})
                    _sec_add_finding("high", f"Open network: {ssid}", bssid,
                        f"SSID '{ssid}' has no encryption — traffic visible to anyone",
                        "Enable WPA2-Enterprise or WPA3 on this SSID")
                    _sec_score_deduct("high")
                elif has_wep:
                    weak_enc.append({"ssid": ssid, "bssid": bssid})
                    _sec_add_finding("critical", f"WEP encryption: {ssid}", bssid,
                        f"SSID '{ssid}' uses WEP — crackeable en minutos",
                        "Replace WEP with WPA2 or WPA3 immediately")
                    _sec_score_deduct("critical")
                elif has_wpa and not has_wpa2 and not has_wpa3:
                    weak_enc.append({"ssid": ssid, "bssid": bssid})
                    _sec_add_finding("medium", f"WPA-TKIP only: {ssid}", bssid,
                        f"SSID '{ssid}' uses WPA/TKIP — deprecated since 2009",
                        "Upgrade to WPA2-AES or WPA3")
                    _sec_score_deduct("medium")

                # Evil twin: same SSID, different OUI
                if ssid in seen_ssids:
                    existing_oui = seen_ssids[ssid].split(":")[:3]
                    new_oui      = bssid.split(":")[:3]
                    if existing_oui != new_oui:
                        _sec_add_finding("high", f"Possible Evil Twin: {ssid}", bssid,
                            f"SSID '{ssid}' seen from different vendors — verify if authorized",
                            "Check MAC OUI: "+":".join(existing_oui)+" vs "+":".join(new_oui))
                        _sec_score_deduct("high")
                else:
                    seen_ssids[ssid] = bssid

            _SEC_SUMMARY.update({"open_nets": len(open_nets), "weak_enc": len(weak_enc)})

        _SEC_PROGRESS = 70

        # ── PHASE 4: Vulnerability Analysis + Default Creds ──────
        _SEC_STATUS   = "Phase 4/4 — Vulnerability Analysis"

        # Deduplicate CVEs: track (host, cve_id) pairs already reported
        _seen_cves = set()

        for host, data in host_data.items():
            if not data["ports"]: continue

            # Detect vendor first — used in CVE title and creds
            detected_vendor = _guess_vendor(host, data["ports"])
            if vendor_override:
                detected_vendor = vendor_override
            host_label = detected_vendor or data["name"] or host

            # CVE scan with vulners
            port_list = ",".join(str(p["port"]) for p in data["ports"][:8])
            vuln_out = run_cmd([
                "nmap", "-sT", "-sV",
                "--script", "vulners,ssl-poodle,ssl-heartbleed,smb-vuln-ms17-010",
                "-p", port_list,
                "--host-timeout", "15s", "-T3", host
            ], timeout=25)

            for cve_m in _re.finditer(r"(CVE-\d{4}-\d+)\s+([\d.]+)\s+https", vuln_out):
                cve_id, cvss = cve_m.group(1), float(cve_m.group(2))
                dedup_key = (host, cve_id)
                if dedup_key in _seen_cves:
                    continue          # Skip duplicate — same CVE on same host
                _seen_cves.add(dedup_key)
                # When we know the vendor (auto or override), only keep CVEs whose
                # nmap context line mentions it — kills the bulk false-positive
                # spam from nmap-vulners reporting unrelated CVEs.
                if detected_vendor:
                    span_start = max(0, cve_m.start() - 200)
                    context = vuln_out[span_start:cve_m.end() + 80].lower()
                    keys = [w for w in detected_vendor.lower().split() if len(w) > 3]
                    if keys and not any(k in context for k in keys):
                        continue
                if cvss >= 7.0:
                    severity = "critical" if cvss >= 9.0 else "high"
                    _sec_add_finding(severity,
                        f"{cve_id} on {host_label}",
                        host,
                        f"CVSS {cvss} — {cve_id}" + (f" ({detected_vendor})" if detected_vendor else ""),
                        "Apply vendor security patch", cve=cve_id)
                    _sec_score_deduct(severity)

            if "VULNERABLE" in vuln_out and "ms17-010" in vuln_out:
                if (host, "CVE-2017-0144") not in _seen_cves:
                    _seen_cves.add((host, "CVE-2017-0144"))
                    _sec_add_finding("critical", f"EternalBlue (MS17-010) on {host_label}", host,
                        "SMB vulnerable to EternalBlue — ransomware vector",
                        "Apply MS17-010 patch or disable SMBv1", "CVE-2017-0144")
                    _sec_score_deduct("critical")

            # SNMP community check
            if any(p["port"] == 161 for p in data["ports"]):
                snmp_out = run_cmd(["nmap", "-sU", "-p", "161",
                    "--script", "snmp-info", "--host-timeout", "5s", host], timeout=8)
                if "public" in snmp_out.lower() or "private" in snmp_out.lower():
                    _sec_add_finding("high", f"SNMP default community on {host_label}", host,
                        "SNMP community 'public'/'private' — full device info exposed",
                        "Change community strings or migrate to SNMPv3")
                    _sec_score_deduct("high")

            # Default credentials — vendor-targeted, max 6 attempts
            _SEC_STATUS = f"Phase 4/4 — Checking default creds on {host}"
            detected_vendor = vendor_override or _guess_vendor(host, data["ports"])
            open_port_set   = {p["port"] for p in data["ports"]}

            if detected_vendor:
                candidates = [c for c in _DEFAULT_CREDS
                              if detected_vendor.lower() in c["vendor"].lower()
                              and any(p in open_port_set for p in c["ports"])]
            else:
                candidates = [c for c in _DEFAULT_CREDS
                              if c["vendor"].startswith("Generic")
                              and any(p in open_port_set for p in c["ports"])]

            cred_tested = 0
            cred_hit    = False
            for cred in candidates[:6]:
                port = next((p for p in cred["ports"] if p in open_port_set), None)
                if not port: continue
                hit = False
                cred_tested += 1
                try:
                    if port == 21:
                        import ftplib
                        ftp = ftplib.FTP(); ftp.connect(host, 21, timeout=4)
                        ftp.login(cred["user"], cred["pass"]); ftp.quit(); hit = True
                    elif port == 23:
                        import socket as _sock, time as _t
                        s = _sock.create_connection((host, 23), timeout=3)
                        s.recv(512)
                        s.sendall((cred["user"] + "\n").encode()); _t.sleep(0.4); s.recv(512)
                        s.sendall((cred["pass"] + "\n").encode()); _t.sleep(0.5)
                        resp = s.recv(512).decode(errors="ignore"); s.close()
                        failed = ("incorrect","failed","denied","invalid","error","bad")
                        hit = bool(resp.strip()) and not any(k in resp.lower() for k in failed)
                    elif port in (80, 443, 8080, 8291, 8443):
                        scheme = "https" if port in (443, 8443) else "http"
                        resp = run_cmd(["curl", "-sk", "--max-time", "4", "--connect-timeout", "2",
                            "-u", f"{cred['user']}:{cred['pass']}",
                            "-o", "/dev/null", "-w", "%{http_code}",
                            f"{scheme}://{host}:{port}/"], timeout=6)
                        hit = resp.strip() in ("200", "302", "301")
                except Exception:
                    pass
                if hit:
                    vendor_label = detected_vendor or cred["vendor"]
                    _sec_add_finding("critical",
                        f"Default credentials active on {data['name'] or host}", host,
                        f"{vendor_label} — login succeeded with {cred['user']} / "
                        f"{'(blank)' if not cred['pass'] else cred['pass']} on port {port}",
                        f"Change default credentials on {vendor_label} immediately")
                    _sec_score_deduct("critical")
                    cred_hit = True
                    break

            # Always report credential test result as info finding
            if cred_tested > 0 and not cred_hit:
                vendor_label = detected_vendor or "device"
                _sec_add_finding("info",
                    f"Default creds tested — none matched on {host_label}",
                    host,
                    f"Tested {cred_tested} known default credential(s) for {vendor_label} — all rejected",
                    "Credentials are not default — good practice")
            elif cred_tested == 0 and data["ports"]:
                _sec_add_finding("info",
                    f"Default creds — vendor unknown on {host_label}",
                    host,
                    f"Could not identify vendor for {host} — no targeted credentials tested",
                    "Manually verify admin credentials if this is a managed device")

        # ── FINALIZE ─────────────────────────────────────────────
        elapsed = int(_time.time() - _SEC_START_TIME)
        mins, secs = divmod(elapsed, 60)
        elapsed_str = f"{mins}m {secs:02d}s"

        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in _SEC_FINDINGS:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1

        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        _SEC_FINDINGS.sort(key=lambda x: sev_order.get(x["severity"], 5))

        _SEC_SUMMARY.update({
            "score":    _SEC_SCORE,
            "critical": counts["critical"],
            "high":     counts["high"],
            "medium":   counts["medium"],
            "low":      counts["low"],
            "info":     counts["info"],
            "elapsed":  elapsed_str,
            "open_nets": _SEC_SUMMARY.get("open_nets", 0),
            "weak_enc":  _SEC_SUMMARY.get("weak_enc",  0),
        })
        _SEC_PROGRESS = 100
        _SEC_STATUS   = "complete"

    except Exception as e:
        _SEC_STATUS = f"error: {str(e)}"
    finally:
        _SEC_RUNNING = False

@app.post("/api/security/start")
async def security_start(subnet: str = "", iface: str = "wlan1",
                         ssid_filter: str = "", vendor: str = ""):
    global _SEC_RUNNING, _SEC_STATUS, _SEC_PROGRESS
    if _SEC_RUNNING:
        return {"ok": False, "error": "Scan already running"}
    if not subnet:
        import re as _re
        eth0_info = run_cmd(["ip", "addr", "show", "eth0"])
        src_m = _re.search(r"inet ([\d.]+)/(\d+)", eth0_info)
        if src_m:
            parts = src_m.group(1).split(".")
            subnet = ".".join(parts[:3]) + ".0/24"
        else:
            routes = run_cmd(["ip", "route", "show"])
            for line in routes.splitlines():
                if "eth0" in line and "kernel" in line:
                    net_m = _re.search(r"([\d.]+/\d+)", line)
                    if net_m:
                        subnet = net_m.group(1); break
            if not subnet: subnet = "192.168.1.0/24"

    _SEC_RUNNING = True
    _SEC_STATUS  = "starting"

    def _launch():
        import time as _time
        _time.sleep(0.2)
        _run_security_audit(subnet, iface, ssid_filter, vendor)

    t = _sec_threading.Thread(target=_launch, daemon=True)
    t.start()
    return {"ok": True, "subnet": subnet}

@app.get("/api/security/status")
async def security_status():
    return {
        "running":  _SEC_RUNNING,
        "progress": _SEC_PROGRESS,
        "status":   _SEC_STATUS,
        "findings": len(_SEC_FINDINGS),
    }

@app.get("/api/security/results")
async def security_results():
    import time as _t
    elapsed_live = ""
    if _SEC_RUNNING and _SEC_START_TIME:
        e = int(_t.time() - _SEC_START_TIME)
        elapsed_live = f"{e//60}m {e%60:02d}s"
    return {
        "running":      _SEC_RUNNING,
        "progress":     _SEC_PROGRESS,
        "status":       _SEC_STATUS,
        "score":        _SEC_SCORE,
        "summary":      _SEC_SUMMARY,
        "hosts":        _SEC_HOSTS,
        "findings":     _SEC_FINDINGS,
        "elapsed":      _SEC_SUMMARY.get("elapsed", elapsed_live),
        "elapsed_live": elapsed_live,
    }

@app.post("/api/security/stop")
async def security_stop():
    global _SEC_RUNNING
    _SEC_RUNNING = False
    run_cmd(["sudo", "pkill", "-f", "nmap"])
    return {"ok": True}



# ═══════════════════════════════════════════════════════════════
#  RESCUE TOOLKIT
# ═══════════════════════════════════════════════════════════════
import threading as _tk_threading
import socket as _tk_socket

# ── State ────────────────────────────────────────────────────
_TK = {
    "dhcp":   {"running": False, "proc": None, "log": [], "iface": "", "range": ""},
    "tftp":   {"running": False, "proc": None, "log": [], "dir": "/opt/nekopi/tftp"},
    "syslog": {"running": False, "thread": None, "log": [], "stop_evt": None},
    "arp":    {"running": False, "results": [], "log": []},
    "mac":    {"original": {}, "current": {}},
    "staticip": {"log": []},
}

def _tk_sudo():
    """Returns ['sudo'] only if not already root"""
    import os
    return [] if os.geteuid() == 0 else ["sudo"]

def _tk_log(tool: str, msg: str):
    _TK[tool]["log"].append({"ts": time.strftime("%H:%M:%S"), "msg": msg})
    if len(_TK[tool]["log"]) > 200:
        _TK[tool]["log"] = _TK[tool]["log"][-200:]

def _get_iface_mac(iface: str) -> str:
    try:
        return Path(f"/sys/class/net/{iface}/address").read_text().strip()
    except:
        return ""

# ── DHCP Server ──────────────────────────────────────────────
@app.post("/api/toolkit/dhcp/start")
async def toolkit_dhcp_start(
    iface: str = "eth0",
    start_ip: str = "192.168.99.100",
    end_ip: str = "192.168.99.200",
    lease: str = "1h",
    gateway: str = "",
    dns: str = "8.8.8.8"
):
    if _TK["dhcp"]["running"]:
        return {"ok": False, "error": "DHCP already running", "running": True}
    try:
        _TK["dhcp"]["log"] = []
        _TK["dhcp"]["iface"] = iface
        _TK["dhcp"]["range"] = f"{start_ip} — {end_ip}"

        # Kill ONLY a dnsmasq that might be conflicting on THIS specific interface.
        # We must NOT kill the management dnsmasq (eth1) — that would drop our connection.
        # With --bind-interfaces, two dnsmasq instances can coexist on different interfaces.
        # Only kill if there's a previous NekoPi-launched instance on this same interface.
        pidfile = f"/tmp/nekopi-dnsmasq-{iface}.pid"
        if Path(pidfile).exists():
            try:
                pid = int(Path(pidfile).read_text().strip())
                run_cmd(_tk_sudo() + ["kill", str(pid)])
                time.sleep(0.3)
            except Exception:
                pass
            try: Path(pidfile).unlink()
            except: pass

        # Ensure interface is up
        run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "up"])

        # Build dnsmasq command with pidfile to track OUR process
        pidfile = f"/tmp/nekopi-dnsmasq-{iface}.pid"
        cmd = _tk_sudo() + [
            "dnsmasq",
            "--no-daemon",
            f"--interface={iface}",
            "--bind-interfaces",
            f"--pid-file={pidfile}",
            f"--dhcp-range={start_ip},{end_ip},{lease}",
            "--dhcp-authoritative",
            "--log-dhcp",
            "--no-resolv",
            f"--dhcp-option=6,{dns}",
        ]
        if gateway:
            cmd += [f"--dhcp-option=3,{gateway}"]

        _TK["dhcp"]["pidfile"] = pidfile

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        _TK["dhcp"]["proc"] = proc
        _TK["dhcp"]["running"] = True
        _tk_log("dhcp", f"▶ DHCP started on {iface} — range {start_ip} to {end_ip}")

        def _read():
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if line:
                    _tk_log("dhcp", line)
            _TK["dhcp"]["running"] = False
            _tk_log("dhcp", "■ DHCP server stopped")

        _tk_threading.Thread(target=_read, daemon=True).start()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/toolkit/dhcp/stop")
async def toolkit_dhcp_stop():
    # Kill ONLY our specific dnsmasq via pidfile — never touch the management dnsmasq
    pidfile = _TK["dhcp"].get("pidfile", "")
    if pidfile and Path(pidfile).exists():
        try:
            pid = int(Path(pidfile).read_text().strip())
            run_cmd(_tk_sudo() + ["kill", str(pid)])
            Path(pidfile).unlink(missing_ok=True)
        except Exception:
            pass
    proc = _TK["dhcp"].get("proc")
    if proc:
        try: proc.terminate()
        except: pass
    _TK["dhcp"]["running"] = False
    _tk_log("dhcp", "■ DHCP stopped — management DHCP (eth1) untouched")
    return {"ok": True}

@app.get("/api/toolkit/dhcp/status")
async def toolkit_dhcp_status():
    # Parse leases from dnsmasq log
    leases = []
    for entry in _TK["dhcp"]["log"]:
        msg = entry["msg"]
        m = re.search(r"DHCPACK.*?(\d+\.\d+\.\d+\.\d+).*?(\S+:\S+:\S+:\S+:\S+:\S+)", msg, re.I)
        if m:
            leases.append({"ip": m.group(1), "mac": m.group(2), "ts": entry["ts"]})
    return {
        "running": _TK["dhcp"]["running"],
        "iface":   _TK["dhcp"]["iface"],
        "range":   _TK["dhcp"]["range"],
        "log":     _TK["dhcp"]["log"][-50:],
        "leases":  leases,
    }

# ── TFTP Server ──────────────────────────────────────────────
@app.post("/api/toolkit/tftp/start")
async def toolkit_tftp_start(iface: str = "eth0", directory: str = "/opt/nekopi/tftp"):
    if _TK["tftp"]["running"]:
        return {"ok": False, "error": "TFTP already running", "running": True}
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
        _TK["tftp"]["log"] = []
        _TK["tftp"]["dir"] = directory

        # Kill ONLY a previous NekoPi-launched tftpd via pidfile
        # Do NOT blindly kill system tftpd service
        tftp_pidfile = "/tmp/nekopi-tftpd.pid"
        if Path(tftp_pidfile).exists():
            try:
                pid = int(Path(tftp_pidfile).read_text().strip())
                run_cmd(_tk_sudo() + ["kill", str(pid)])
                time.sleep(0.3)
            except Exception:
                pass
            try: Path(tftp_pidfile).unlink()
            except: pass

        nekopi_ip = run_cmd(["hostname", "-I"]).split()[0] if run_cmd(["hostname", "-I"]).split() else "?"

        # Stop system tftpd service if it's holding port 69
        port_check = run_cmd(["ss", "-ulnp"])
        if ":69 " in port_check or ":69\n" in port_check or port_check.count("*:69") > 0:
            _tk_log("tftp", "⚠ Port 69 in use — stopping system tftpd-hpa...")
            run_cmd(_tk_sudo() + ["systemctl", "stop", "tftpd-hpa"])
            _TK["tftp"]["system_stopped"] = True
            time.sleep(0.5)

        # tftpd-hpa: -l = standalone, --foreground = don't daemonize, -v = verbose
        if shutil.which("in.tftpd"):
            cmd = _tk_sudo() + [
                "in.tftpd", "-l", "--foreground", "-v",
                "--address", "0.0.0.0:69",
                "--secure", directory,
            ]
        elif shutil.which("busybox"):
            cmd = _tk_sudo() + ["busybox", "tftpd", "-l", "-r", directory, "-a", "0.0.0.0:69"]
        else:
            _tk_log("tftp", "⚠ in.tftpd not found — install: sudo apt install tftpd-hpa")
            return {"ok": False, "error": "tftpd-hpa not installed. Run: sudo apt install tftpd-hpa"}

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        _TK["tftp"]["proc"] = proc
        _TK["tftp"]["running"] = True
        _tk_log("tftp", f"▶ TFTP started — root: {directory}  port 69")
        _tk_log("tftp", f"  Connect: tftp {nekopi_ip}")
        _tk_log("tftp", f"  Upload:   tftp -p -l <file> {nekopi_ip}")
        _tk_log("tftp", f"  Download: tftp -g -r <file> {nekopi_ip}")

        def _read():
            import time as _t
            # Wait 1s — if process died immediately it was a startup error
            _t.sleep(1.0)
            rc = proc.poll()
            if rc is not None:
                out = proc.stdout.read().strip()
                if out:
                    _tk_log("tftp", f"❌ {out}")
                _tk_log("tftp", f"❌ tftpd exited immediately (rc={rc})")
                _tk_log("tftp", "  → sudo apt install tftpd-hpa")
                _TK["tftp"]["running"] = False
                return
            # Still alive — stream output
            for line in iter(proc.stdout.readline, ""):
                line = line.strip()
                if line: _tk_log("tftp", line)
            _TK["tftp"]["running"] = False
            _tk_log("tftp", "■ TFTP stopped")

        _tk_threading.Thread(target=_read, daemon=True).start()
        return {"ok": True, "dir": directory}
    except Exception as e:
        _TK["tftp"]["running"] = False
        return {"ok": False, "error": str(e)}

@app.post("/api/toolkit/tftp/stop")
async def toolkit_tftp_stop():
    proc = _TK["tftp"].get("proc")
    if proc:
        run_cmd(_tk_sudo() + ["pkill", "-f", "in.tftpd"])
        try: proc.terminate()
        except: pass
    _TK["tftp"]["running"] = False
    _tk_log("tftp", "■ TFTP stopped by user")
    # Restore system service if we stopped it
    if _TK["tftp"].get("system_stopped"):
        run_cmd(_tk_sudo() + ["systemctl", "start", "tftpd-hpa"])
        _TK["tftp"]["system_stopped"] = False
        _tk_log("tftp", "↺ System tftpd-hpa service restored")
    return {"ok": True}

@app.post("/api/toolkit/tftp/upload")
async def toolkit_tftp_upload(file: UploadFile = File(...)):
    """Receives a file from the web UI and writes it into the active TFTP root."""
    try:
        directory = _TK["tftp"].get("dir") or "/opt/nekopi/tftp"
        Path(directory).mkdir(parents=True, exist_ok=True)
        # Sanitize filename — strip path components, refuse traversal
        name = os.path.basename(file.filename or "upload.bin")
        if not name or name in (".", "..") or "/" in name:
            return {"ok": False, "error": "invalid filename"}
        dest = Path(directory) / name
        content = await file.read()
        if len(content) > 200 * 1024 * 1024:  # 200 MB cap
            return {"ok": False, "error": "file too large (max 200 MB)"}
        dest.write_bytes(content)
        try: dest.chmod(0o644)
        except Exception: pass
        _tk_log("tftp", f"⤓ uploaded {name} ({len(content)} bytes)")
        return {"ok": True, "name": name, "size": len(content), "path": str(dest)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/toolkit/tftp/status")
async def toolkit_tftp_status():
    # List files in TFTP directory
    files = []
    try:
        d = Path(_TK["tftp"]["dir"])
        if d.exists():
            files = [{"name": f.name, "size": f.stat().st_size,
                      "modified": time.strftime("%H:%M:%S", time.localtime(f.stat().st_mtime))}
                     for f in sorted(d.iterdir()) if f.is_file()]
    except:
        pass
    return {
        "running": _TK["tftp"]["running"],
        "dir":     _TK["tftp"]["dir"],
        "log":     _TK["tftp"]["log"][-50:],
        "files":   files,
    }

# ── MAC Clone ────────────────────────────────────────────────
@app.post("/api/toolkit/mac/clone")
async def toolkit_mac_clone(iface: str = "eth0", mac: str = ""):
    try:
        # Save original if not saved yet
        if iface not in _TK["mac"]["original"]:
            orig = _get_iface_mac(iface)
            if orig:
                _TK["mac"]["original"][iface] = orig

        if not mac:
            return {"ok": False, "error": "MAC address required"}

        # Validate MAC format
        if not re.match(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$", mac):
            return {"ok": False, "error": "Invalid MAC format (use AA:BB:CC:DD:EE:FF)"}

        run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "down"])
        out = run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "address", mac])
        run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "up"])

        current = _get_iface_mac(iface)
        _TK["mac"]["current"][iface] = current

        return {
            "ok":       True,
            "iface":    iface,
            "original": _TK["mac"]["original"].get(iface, "unknown"),
            "current":  current,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/toolkit/mac/restore")
async def toolkit_mac_restore(iface: str = "eth0"):
    orig = _TK["mac"]["original"].get(iface)
    if not orig:
        return {"ok": False, "error": f"No original MAC saved for {iface}"}
    run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "down"])
    run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "address", orig])
    run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "up"])
    _TK["mac"]["current"][iface] = _get_iface_mac(iface)
    return {"ok": True, "restored": orig}

@app.get("/api/toolkit/mac/info")
async def toolkit_mac_info():
    ifaces = get_interfaces()
    result = {}
    for iface in ifaces:
        name = iface["name"]
        result[name] = {
            "current":  _get_iface_mac(name),
            "original": _TK["mac"]["original"].get(name, ""),
            "cloned":   name in _TK["mac"]["original"],
        }
    return result

# ── ARP Scan ─────────────────────────────────────────────────
@app.post("/api/toolkit/arp/scan")
async def toolkit_arp_scan(iface: str = "eth0", subnet: str = ""):
    if _TK["arp"]["running"]:
        return {"ok": False, "error": "Scan already running"}

    if not subnet:
        # Auto-detect from interface
        out = run_cmd(["ip", "addr", "show", iface])
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", out)
        if m:
            import ipaddress
            net = ipaddress.ip_interface(f"{m.group(1)}/{m.group(2)}").network
            subnet = str(net)
        else:
            subnet = "192.168.1.0/24"

    def _run():
        import subprocess as _sp
        _TK["arp"]["running"] = True
        _TK["arp"]["results"] = []
        _TK["arp"]["log"] = [{"ts": time.strftime("%H:%M:%S"), "msg": f"▶ ARP scan on {subnet} via {iface}"}]

        # Strategy 1: arp-scan (best, needs sudo or setcap)
        if shutil.which("arp-scan"):
            # Try without sudo first (works if setcap is configured)
            out = run_cmd(["arp-scan", f"--interface={iface}", subnet], timeout=30)
            if "sudo" in out.lower() or "permission" in out.lower() or not out.strip():
                out = run_cmd(_tk_sudo() + ["arp-scan", f"--interface={iface}", subnet], timeout=30)
            for line in out.splitlines():
                m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f:]{17})\s*(.*)", line, re.I)
                if m:
                    _TK["arp"]["results"].append({
                        "ip": m.group(1), "mac": m.group(2).lower(),
                        "vendor": m.group(3).strip() or "—"
                    })

        # Strategy 2: nmap -sn (no sudo needed for ping scan)
        if not _TK["arp"]["results"] and shutil.which("nmap"):
            _tk_log("arp", "Using nmap ping scan (install arp-scan for MAC info)")
            out = run_cmd(["nmap", "-sn", "-T4", subnet, "--host-timeout", "3s"], timeout=45)
            ips  = re.findall(r"report for (?:\S+ \()?(\d+\.\d+\.\d+\.\d+)", out)
            macs = re.findall(r"MAC Address: ([0-9A-F:]{17})\s+\(([^)]*)\)", out, re.I)
            for i, ip in enumerate(ips):
                mac, vendor = macs[i] if i < len(macs) else ("", "")
                _TK["arp"]["results"].append({"ip": ip, "mac": mac.lower(), "vendor": vendor or "—"})

        # Strategy 3: ping sweep + read kernel ARP table (no root at all)
        if not _TK["arp"]["results"]:
            _tk_log("arp", "Using ping sweep + kernel ARP table (no root)")
            # Parallel ping to populate ARP cache
            try:
                import ipaddress as _ip
                net = _ip.ip_network(subnet, strict=False)
                hosts = list(net.hosts())[:254]
                # Batch ping
                procs = []
                for h in hosts:
                    p = _sp.Popen(["ping", "-c1", "-W1", str(h)],
                                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    procs.append(p)
                for p in procs:
                    p.wait()
            except Exception:
                pass
            # Read ARP table
            arp_out = run_cmd(["arp", "-n"])
            for line in arp_out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and re.match(r"\d+\.\d+\.\d+\.\d+", parts[0]):
                    ip  = parts[0]
                    mac = parts[2] if parts[2] != "<incomplete>" else ""
                    if mac:
                        _TK["arp"]["results"].append({"ip": ip, "mac": mac, "vendor": "—"})

        count = len(_TK["arp"]["results"])
        if count == 0:
            _tk_log("arp", "⚠ No results — try: sudo apt install arp-scan")
        else:
            _tk_log("arp", f"✓ Found {count} host(s)")
        _TK["arp"]["running"] = False

    _tk_threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "subnet": subnet}

@app.get("/api/toolkit/arp/status")
async def toolkit_arp_status():
    return {
        "running": _TK["arp"]["running"],
        "results": _TK["arp"]["results"],
        "log":     _TK["arp"]["log"],
        "count":   len(_TK["arp"]["results"]),
    }

# ── Captive Portal Tester ────────────────────────────────────
@app.post("/api/toolkit/captive/test")
async def toolkit_captive_test(url: str = "http://connectivity-check.ubuntu.com", iface: str = ""):
    results = []
    test_urls = [
        url,
        "http://connectivity-check.ubuntu.com",
        "http://www.msftconnecttest.com/connecttest.txt",
        "http://captive.apple.com/hotspot-detect.html",
        "http://clients3.google.com/generate_204",
    ]
    # deduplicate preserving order
    seen = set()
    unique_urls = [u for u in test_urls if not (u in seen or seen.add(u))]

    bind_opt = ["--interface", iface] if iface else []

    for test_url in unique_urls[:5]:
        try:
            out = run_cmd([
                "curl", "-s", "-L", "-m", "8", "--connect-timeout", "4",
                "-w", "%{http_code}|%{redirect_url}|%{url_effective}",
                "-o", "/dev/null",
            ] + bind_opt + [test_url], timeout=10)

            parts = out.strip().split("|")
            code     = parts[0] if parts else "?"
            redirect = parts[1] if len(parts) > 1 else ""
            final    = parts[2] if len(parts) > 2 else ""
            captive  = code in ("302", "301", "307") or (redirect and redirect != test_url)

            results.append({
                "url":      test_url,
                "code":     code,
                "redirect": redirect,
                "final":    final,
                "captive":  captive,
                "status":   "🔴 CAPTIVE PORTAL" if captive else ("✅ FREE" if code in ("200","204") else f"⚠️ {code}"),
            })
        except Exception as e:
            results.append({"url": test_url, "code": "ERR", "status": f"❌ {str(e)}", "captive": False})

    detected = any(r["captive"] for r in results)
    return {
        "ok":       True,
        "detected": detected,
        "verdict":  "🔴 Captive portal detected — authentication required" if detected else "✅ Internet appears free",
        "results":  results,
    }

# ── Static IP Setter ─────────────────────────────────────────
@app.post("/api/toolkit/staticip/set")
async def toolkit_staticip_set(
    iface: str = "eth0",
    ip: str = "",
    prefix: str = "24",
    gateway: str = "",
    dns: str = "8.8.8.8"
):
    if not ip:
        return {"ok": False, "error": "IP address required"}
    try:
        log = []

        # Flush existing addresses
        run_cmd(_tk_sudo() + ["ip", "addr", "flush", "dev", iface])
        log.append(f"Flushed existing addresses on {iface}")

        # Set new IP
        run_cmd(_tk_sudo() + ["ip", "addr", "add", f"{ip}/{prefix}", "dev", iface])
        run_cmd(_tk_sudo() + ["ip", "link", "set", iface, "up"])
        log.append(f"Set {ip}/{prefix} on {iface}")

        # Set gateway
        if gateway:
            run_cmd(_tk_sudo() + ["ip", "route", "add", "default", "via", gateway, "dev", iface])
            log.append(f"Default gateway: {gateway}")

        # Set DNS
        try:
            resolv = Path("/etc/resolv.conf")
            content = resolv.read_text() if resolv.exists() else ""
            # Prepend our DNS
            if f"nameserver {dns}" not in content:
                resolv.write_text(f"nameserver {dns}\n" + content)
            log.append(f"DNS: {dns}")
        except:
            pass

        # Verify
        actual = run_cmd(["ip", "addr", "show", iface])
        m = re.search(r"inet (\S+)", actual)
        actual_ip = m.group(1) if m else "unknown"

        _TK["staticip"]["log"] = [{"ts": time.strftime("%H:%M:%S"), "msg": l} for l in log]
        return {"ok": True, "iface": iface, "applied": actual_ip, "log": log}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/toolkit/staticip/dhcp")
async def toolkit_staticip_dhcp(iface: str = "eth0"):
    """Release static and request DHCP"""
    try:
        run_cmd(_tk_sudo() + ["ip", "addr", "flush", "dev", iface])
        out = run_cmd(_tk_sudo() + ["dhclient", "-v", iface], timeout=15)
        m = re.search(r"bound to (\S+)", out)
        ip = m.group(1) if m else "pending"
        return {"ok": True, "iface": iface, "ip": ip}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Syslog Catcher ───────────────────────────────────────────
@app.post("/api/toolkit/syslog/start")
async def toolkit_syslog_start(port: int = 514):
    if _TK["syslog"]["running"]:
        return {"ok": False, "error": "Syslog catcher already running"}
    try:
        _TK["syslog"]["log"] = []
        stop_evt = _tk_threading.Event()
        _TK["syslog"]["stop_evt"] = stop_evt

        def _listen():
            try:
                sock = _tk_socket.socket(_tk_socket.AF_INET, _tk_socket.SOCK_DGRAM)
                sock.bind(("0.0.0.0", port))
                sock.settimeout(1.0)
                _TK["syslog"]["running"] = True
                _tk_log("syslog", f"▶ Listening on UDP {port} — point devices here: {run_cmd(['hostname','-I']).split()[0]}")
                while not stop_evt.is_set():
                    try:
                        data, addr = sock.recvfrom(4096)
                        msg = data.decode("utf-8", errors="replace").strip()
                        _tk_log("syslog", f"[{addr[0]}] {msg}")
                    except _tk_socket.timeout:
                        continue
                sock.close()
            except Exception as e:
                _tk_log("syslog", f"❌ Error: {e}")
            _TK["syslog"]["running"] = False
            _tk_log("syslog", "■ Syslog catcher stopped")

        t = _tk_threading.Thread(target=_listen, daemon=True)
        _TK["syslog"]["thread"] = t
        t.start()
        return {"ok": True, "port": port}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/toolkit/syslog/stop")
async def toolkit_syslog_stop():
    evt = _TK["syslog"].get("stop_evt")
    if evt:
        evt.set()
    _TK["syslog"]["running"] = False
    return {"ok": True}

@app.get("/api/toolkit/syslog/status")
async def toolkit_syslog_status():
    return {
        "running": _TK["syslog"]["running"],
        "log":     _TK["syslog"]["log"][-100:],
        "count":   len(_TK["syslog"]["log"]),
    }

# ── Wake-on-LAN ──────────────────────────────────────────────
@app.post("/api/toolkit/wol/send")
async def toolkit_wol_send(mac: str = "", broadcast: str = "255.255.255.255", port: int = 9):
    if not mac:
        return {"ok": False, "error": "MAC address required"}
    try:
        # Validate and normalize MAC
        mac_clean = mac.replace(":", "").replace("-", "").upper()
        if len(mac_clean) != 12:
            return {"ok": False, "error": "Invalid MAC address"}

        # Build magic packet: 6x FF + 16x MAC
        magic = bytes.fromhex("FF" * 6 + mac_clean * 16)

        sock = _tk_socket.socket(_tk_socket.AF_INET, _tk_socket.SOCK_DGRAM)
        sock.setsockopt(_tk_socket.SOL_SOCKET, _tk_socket.SO_BROADCAST, 1)
        sock.sendto(magic, (broadcast, port))
        sock.close()

        return {
            "ok":        True,
            "mac":       mac,
            "broadcast": broadcast,
            "port":      port,
            "message":   f"Magic packet sent to {mac} via {broadcast}:{port}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ═══════════════════════════════════════════════════════════════
#  NETPUSH — Mass Config Pusher (Cisco IOS/IOS-XE · SSH)
# ═══════════════════════════════════════════════════════════════
import threading as _np_th
import ipaddress as _np_ip

_NP = {
    "devices":  {},   # ip → {hostname, version, platform, status, reachable}
    "creds":    {},   # {username, password, enable, port}
    "job":      {     # current running job
        "type":     "",       # discover / show / config
        "running":  False,
        "results":  {},       # ip → {output, status, error}
        "progress": 0,
        "total":    0,
        "log":      [],
    },
}

def _np_log(msg: str):
    import time as _t
    _NP["job"]["log"].append({"ts": _t.strftime("%H:%M:%S"), "msg": msg})
    if len(_NP["job"]["log"]) > 500:
        _NP["job"]["log"] = _NP["job"]["log"][-500:]

def _np_ssh(ip: str, username: str, password: str, enable: str,
            commands: list, port: int = 22, timeout: int = 10) -> dict:
    """Open SSH to a Cisco device, optionally enter enable, run commands.
    Returns {ok, output, error, hostname, version, platform}"""
    import paramiko, time as _t, re as _r

    result = {"ok": False, "output": "", "error": "", 
              "hostname": "", "version": "", "platform": ""}
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=port, username=username, password=password,
                       timeout=timeout, look_for_keys=False, allow_agent=False,
                       banner_timeout=15)

        shell = client.invoke_shell(width=200, height=200)
        _t.sleep(0.8)

        def _read(wait=0.5):
            _t.sleep(wait)
            out = ""
            while shell.recv_ready():
                out += shell.recv(65535).decode("utf-8", errors="replace")
                _t.sleep(0.1)
            return out

        banner = _read(1.0)

        # Extract hostname from prompt (e.g. "Router>", "SW1#")
        prompt_m = _r.search(r"\n?(\S+)[>#]", banner)
        hostname = prompt_m.group(1) if prompt_m else ip

        # Enter enable mode if needed
        if ">" in banner[-10:]:
            shell.send("enable\n")
            _t.sleep(0.3)
            en_out = _read(0.5)
            if "Password" in en_out or "password" in en_out:
                shell.send((enable or password) + "\n")
                _t.sleep(0.5)
                _read(0.5)

        # Disable pagination
        shell.send("terminal length 0\n")
        _read(0.5)
        shell.send("terminal width 0\n")
        _read(0.3)

        # Run all commands and collect output
        full_output = ""
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("!"):
                continue

            # Detect config mode entry
            if cmd in ("conf t", "configure terminal", "conf terminal"):
                shell.send(cmd + "\n")
                _t.sleep(0.3)
                _read(0.3)
                continue
            if cmd == "end" or cmd == "exit":
                shell.send(cmd + "\n")
                _t.sleep(0.2)
                _read(0.2)
                continue

            shell.send(cmd + "\n")
            out = _read(1.0)
            full_output += f"\n! {cmd}\n{out}"

            # Detect IOS errors
            if "% " in out or "Invalid input" in out or "Incomplete" in out:
                result["error"] = out.strip()

        # Extract show version info if available
        if "show version" in " ".join(commands).lower() or not commands:
            shell.send("show version\n")
            sv = _read(1.5)
            full_output += f"\n! show version\n{sv}"
            ver_m    = _r.search(r"Version\s+([\d\w.()]+)", sv)
            plat_m   = _r.search(r"^(Cisco .+?)[,\n]", sv, _r.M)
            hostname_m = _r.search(r"(\S+)\s+uptime", sv)
            result["version"]  = ver_m.group(1)    if ver_m    else ""
            result["platform"] = plat_m.group(1)   if plat_m   else ""
            result["hostname"] = hostname_m.group(1) if hostname_m else hostname

        result["hostname"] = result["hostname"] or hostname
        result["ok"]       = True
        result["output"]   = full_output.strip()
        client.close()

    except Exception as e:
        result["error"] = str(e)
    return result


# ── Discovery ─────────────────────────────────────────────────
@app.post("/api/netpush/discover")
async def netpush_discover(
    targets:  str = "",   # "192.168.1.0/24" or "192.168.1.1,192.168.1.2" or "192.168.1.1-10"
    username: str = "",
    password: str = "",
    enable:   str = "",
    port:     int = 22,
):
    if _NP["job"]["running"]:
        return {"ok": False, "error": "Job already running"}

    # Parse targets
    ips = []
    for part in targets.replace(" ", "").split(","):
        part = part.strip()
        if not part: continue
        try:
            if "/" in part:
                # CIDR
                net = _np_ip.ip_network(part, strict=False)
                ips += [str(h) for h in net.hosts()]
            elif "-" in part.split(".")[-1]:
                # Range like 192.168.1.1-20
                base = ".".join(part.split(".")[:3])
                rng  = part.split(".")[-1].split("-")
                ips += [f"{base}.{i}" for i in range(int(rng[0]), int(rng[1])+1)]
            else:
                ips.append(part)
        except Exception:
            pass

    if not ips:
        return {"ok": False, "error": "No valid targets"}

    # Store creds (in-memory only, never persisted)
    _NP["creds"] = {"username": username, "password": password,
                    "enable": enable, "port": port}
    _NP["devices"] = {}
    _NP["job"] = {"type": "discover", "running": True, "results": {},
                  "progress": 0, "total": len(ips), "log": []}

    _np_log(f"▶ Discovery started — {len(ips)} targets")

    def _run():
        lock = _np_th.Lock()

        def _probe(ip):
            result = _np_ssh(ip, username, password, enable,
                             [], port=port, timeout=5)
            with lock:
                status = "reachable" if result["ok"] else "unreachable"
                _NP["devices"][ip] = {
                    "ip":       ip,
                    "hostname": result.get("hostname", ip),
                    "version":  result.get("version", ""),
                    "platform": result.get("platform", ""),
                    "status":   status,
                    "error":    result.get("error", ""),
                    "selected": result["ok"],
                }
                _NP["job"]["progress"] += 1
                icon = "✓" if result["ok"] else "✗"
                _np_log(f"{icon} {ip} — {result.get('hostname','')} {result.get('version','') or result.get('error','')[:40]}")

        # Parallel — max 20 threads
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=20) as ex:
            list(ex.map(_probe, ips))

        reachable = sum(1 for d in _NP["devices"].values() if d["status"] == "reachable")
        _np_log(f"■ Discovery complete — {reachable}/{len(ips)} reachable")
        _NP["job"]["running"] = False

    _np_th.Thread(target=_run, daemon=True).start()
    return {"ok": True, "total": len(ips)}


# ── Show Commands ─────────────────────────────────────────────
@app.post("/api/netpush/show")
async def netpush_show(
    ips:      str = "",   # comma-separated, empty = all selected
    commands: str = "",
):
    if _NP["job"]["running"]:
        return {"ok": False, "error": "Job already running"}

    creds    = _NP["creds"]
    cmd_list = [c.strip() for c in commands.splitlines() if c.strip()]
    if not cmd_list:
        return {"ok": False, "error": "No commands specified"}

    target_ips = [i.strip() for i in ips.split(",") if i.strip()] if ips \
                 else [ip for ip, d in _NP["devices"].items() if d.get("selected")]

    if not target_ips:
        return {"ok": False, "error": "No devices selected"}

    _NP["job"] = {"type": "show", "running": True, "results": {},
                  "progress": 0, "total": len(target_ips), "log": []}
    _np_log(f"▶ Show — {len(target_ips)} devices · {len(cmd_list)} command(s)")

    def _run():
        lock = _np_th.Lock()

        def _exec(ip):
            dev = _NP["devices"].get(ip, {})
            result = _np_ssh(ip, creds["username"], creds["password"],
                             creds["enable"], cmd_list,
                             port=creds.get("port", 22), timeout=15)
            with lock:
                _NP["job"]["results"][ip] = {
                    "hostname": dev.get("hostname", ip),
                    "output":   result["output"],
                    "status":   "ok" if result["ok"] else "error",
                    "error":    result["error"],
                }
                _NP["job"]["progress"] += 1
                icon = "✓" if result["ok"] else "✗"
                _np_log(f"{icon} {ip} ({dev.get('hostname',ip)})")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(_exec, target_ips))

        _np_log(f"■ Show complete")
        _NP["job"]["running"] = False

    _np_th.Thread(target=_run, daemon=True).start()
    return {"ok": True, "total": len(target_ips)}


# ── Config Push ───────────────────────────────────────────────
@app.post("/api/netpush/config")
async def netpush_config(
    ips:      str = "",
    commands: str = "",
    test_ip:  str = "",   # if set, run only on this device first
):
    if _NP["job"]["running"]:
        return {"ok": False, "error": "Job already running"}

    creds    = _NP["creds"]
    cmd_list = [c.strip() for c in commands.splitlines() if c.strip()]
    if not cmd_list:
        return {"ok": False, "error": "No commands specified"}

    # Wrap in config terminal / end if not already
    if not any(c in ("conf t", "configure terminal") for c in cmd_list):
        cmd_list = ["conf t"] + cmd_list + ["end"]

    if test_ip:
        # Test mode — single device
        target_ips = [test_ip]
        job_type   = "config_test"
    else:
        target_ips = [i.strip() for i in ips.split(",") if i.strip()] if ips \
                     else [ip for ip, d in _NP["devices"].items() if d.get("selected")]
        job_type   = "config"

    if not target_ips:
        return {"ok": False, "error": "No devices selected"}

    _NP["job"] = {"type": job_type, "running": True, "results": {},
                  "progress": 0, "total": len(target_ips), "log": []}
    _np_log(f"▶ Config {'TEST' if test_ip else 'PUSH'} — {len(target_ips)} device(s)")
    for c in cmd_list:
        _np_log(f"  cmd: {c}")

    def _run():
        lock = _np_th.Lock()

        def _push(ip):
            dev = _NP["devices"].get(ip, {})
            result = _np_ssh(ip, creds["username"], creds["password"],
                             creds["enable"], cmd_list,
                             port=creds.get("port", 22), timeout=20)
            has_error = bool(result["error"]) or "% " in result["output"]
            with lock:
                _NP["job"]["results"][ip] = {
                    "hostname": dev.get("hostname", ip),
                    "output":   result["output"],
                    "status":   "error" if has_error else "ok",
                    "error":    result["error"],
                }
                _NP["job"]["progress"] += 1
                icon = "✗" if has_error else "✓"
                note = result["error"][:50] if has_error else "applied"
                _np_log(f"{icon} {ip} ({dev.get('hostname',ip)}) — {note}")

        # Config push: sequential by default to be safe
        # Use parallel only if not test mode
        from concurrent.futures import ThreadPoolExecutor
        workers = 1 if test_ip else 5
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_push, target_ips))

        _NP["job"]["running"] = False
        ok_count  = sum(1 for r in _NP["job"]["results"].values() if r["status"]=="ok")
        err_count = len(_NP["job"]["results"]) - ok_count
        _np_log(f"■ Done — ✓ {ok_count}  ✗ {err_count}")

    _np_th.Thread(target=_run, daemon=True).start()
    return {"ok": True, "total": len(target_ips)}


# ── Status / Results ──────────────────────────────────────────
@app.get("/api/netpush/status")
async def netpush_status():
    return {
        "running":  _NP["job"]["running"],
        "type":     _NP["job"]["type"],
        "progress": _NP["job"]["progress"],
        "total":    _NP["job"]["total"],
        "log":      _NP["job"]["log"][-100:],
        "results":  _NP["job"]["results"],
        "devices":  list(_NP["devices"].values()),
    }

@app.post("/api/netpush/select")
async def netpush_select(ips: str = "", select_all: bool = False):
    """Toggle device selection for push"""
    if select_all:
        for d in _NP["devices"].values():
            if d["status"] == "reachable":
                d["selected"] = True
    else:
        ip_list = [i.strip() for i in ips.split(",") if i.strip()]
        for ip in ip_list:
            if ip in _NP["devices"]:
                _NP["devices"][ip]["selected"] = not _NP["devices"][ip].get("selected", False)
    return {"ok": True}

@app.post("/api/netpush/clear")
async def netpush_clear():
    _NP["devices"] = {}
    _NP["job"] = {"type":"","running":False,"results":{},"progress":0,"total":0,"log":[]}
    _NP["creds"] = {}
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════
#  WIFI TROUBLESHOOTER — Diagnóstico asistido
# ═══════════════════════════════════════════════════════════════

def _wifi_phy_from_caps(block: str) -> str:
    """Detects the best PHY mode advertised in an iw BSS block.
    Returns one of WiFi4/5/6/7 or 'legacy' if none found."""
    if re.search(r"EHT Capabilities|Extremely High Throughput", block, re.IGNORECASE):
        return "WiFi7"
    if re.search(r"HE Capabilities|High Efficiency", block, re.IGNORECASE):
        return "WiFi6"
    if re.search(r"VHT Capabilities|Very High Throughput", block, re.IGNORECASE):
        return "WiFi5"
    if re.search(r"HT Capabilities|High Throughput", block, re.IGNORECASE):
        return "WiFi4"
    return "legacy"

def _wifi_bw_from_caps(block: str) -> int | None:
    """Guesses channel width (MHz) from iw scan block capabilities."""
    if re.search(r"EHT.*320MHz|320 MHz", block):
        return 320
    if re.search(r"VHT.*160MHz|HE.*160MHz|160 MHz", block):
        return 160
    if re.search(r"VHT.*80MHz|HE.*80MHz|80 MHz", block):
        return 80
    if re.search(r"HT40|40 MHz|secondary channel offset", block, re.IGNORECASE):
        return 40
    if re.search(r"HT20|20 MHz", block):
        return 20
    return None

def _wifi_iface_noise_floor(iface: str) -> float | None:
    """Reads noise floor from `iw dev <iface> survey dump` for the in-use channel."""
    try:
        out = run_cmd(["iw", "dev", iface, "survey", "dump"], timeout=5)
    except Exception:
        return None
    blocks = re.split(r"Survey data from", out)
    for b in blocks:
        if "in use" not in b:
            continue
        m = re.search(r"noise:\s*(-?\d+)", b)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
    return None

def _wifi_station_stats(iface: str) -> dict:
    """Parses `iw dev <iface> station dump` for retry/failed/rx/tx counters."""
    out = run_cmd(["iw", "dev", iface, "station", "dump"], timeout=5)
    if not out:
        return {}
    def _g(pat, cast=int):
        m = re.search(pat, out)
        if not m:
            return None
        try:
            return cast(m.group(1))
        except Exception:
            return None
    tx_pkts = _g(r"tx packets:\s*(\d+)")
    tx_retries = _g(r"tx retries:\s*(\d+)")
    tx_failed = _g(r"tx failed:\s*(\d+)")
    retry_rate = None
    if tx_pkts and tx_retries is not None and tx_pkts > 0:
        retry_rate = round(100.0 * tx_retries / tx_pkts, 2)
    return {
        "tx_packets": tx_pkts,
        "tx_retries": tx_retries,
        "tx_failed":  tx_failed,
        "retry_rate": retry_rate,
        "rx_bitrate": _g(r"rx bitrate:\s*([\d.]+)", float),
        "tx_bitrate": _g(r"tx bitrate:\s*([\d.]+)", float),
    }

@app.post("/api/wifits/scan")
async def wifits_scan(iface: str = "wlan0"):
    """Recopila datos reales del entorno WiFi para el diagnóstico."""
    result: dict = {}

    # 1. Signal / association
    try:
        proc = await asyncio.create_subprocess_exec(
            "iw", "dev", iface, "link",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=4)
        out = out.decode()
        connected = "Connected to" in out or "SSID:" in out
        result["connected"] = connected
        if connected:
            sig_m  = re.search(r"signal:\s*([-\d.]+)", out)
            rate_m = re.search(r"tx bitrate:\s*([\d.]+)", out)
            freq_m = re.search(r"freq:\s*(\d+)", out)
            bss_m  = re.search(r"Connected to\s*([\w:]+)", out)
            ssid_m = re.search(r"SSID:\s*(.+)", out)
            result["rssi"]   = float(sig_m.group(1))  if sig_m  else None
            result["txrate"] = float(rate_m.group(1)) if rate_m else None
            result["freq"]   = int(freq_m.group(1))   if freq_m else None
            result["bssid"]  = bss_m.group(1)         if bss_m  else ""
            result["ssid"]   = ssid_m.group(1).strip() if ssid_m else ""
            f = result.get("freq") or 0
            result["band"] = "6GHz" if f >= 5925 else ("5GHz" if f >= 5000 else ("2.4GHz" if f else ""))
            result["channel"] = None
            if f:
                if f < 3000:
                    result["channel"] = int((f - 2407) / 5)
                elif f >= 5925:
                    result["channel"] = int((f - 5950) / 5)
                else:
                    result["channel"] = int((f - 5000) / 5)
    except Exception as e:
        result["connected"] = False
        result["error_assoc"] = str(e)

    # 1b. Station stats: retry rate, tx/rx bitrate, failed
    try:
        stats = _wifi_station_stats(iface)
        result.update({
            "retry_rate":  stats.get("retry_rate"),
            "tx_retries":  stats.get("tx_retries"),
            "tx_failed":   stats.get("tx_failed"),
            "rx_bitrate":  stats.get("rx_bitrate"),
        })
    except Exception as e:
        result["error_station"] = str(e)

    # 1c. Noise floor + derived SNR
    try:
        nf = _wifi_iface_noise_floor(iface)
        if nf is not None:
            result["noise_floor"] = nf
    except Exception as e:
        result["error_survey"] = str(e)

    # 2. Ping gateway + internet
    gw_out = run_cmd(["ip", "route", "show", "default"])
    gw_m   = re.search(r"default via ([\d.]+)", gw_out)
    gw     = gw_m.group(1) if gw_m else None
    result["gateway"] = gw

    def _ping(host, count=5):
        out = run_cmd(["ping", "-c", str(count), "-W", "2", "-q", host], timeout=15)
        loss_m = re.search(r"(\d+)%\s+packet loss", out)
        rtt_m  = re.search(r"rtt.*?=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
        return {
            "reachable": "0% packet loss" in out,
            "loss_pct":  int(loss_m.group(1)) if loss_m else 100,
            "avg_ms":    float(rtt_m.group(2)) if rtt_m else None,
            "jitter_ms": float(rtt_m.group(4)) if rtt_m else None,
        }

    if gw:
        result["ping_gw"]  = _ping(gw, 5)
    result["ping_dns"] = _ping("8.8.8.8", 5)

    # 3. DNS resolution time
    import time as _t
    try:
        t0 = _t.time()
        socket.gethostbyname("www.google.com")
        result["dns_ms"] = round((_t.time() - t0) * 1000, 1)
    except:
        result["dns_ms"] = None

    # 4. Neighbor APs on same channel (interference) + PHY mode / bandwidth
    result["neighbor_aps"] = []
    result["channel_load"] = None
    result["phy_mode"]     = None
    result["bandwidth"]    = None
    result["beacon_int"]   = None
    try:
        scan_out = run_cmd(["sudo", "iw", "dev", iface, "scan"], timeout=20)
        current_ch    = result.get("channel")
        current_bssid = (result.get("bssid") or "").lower()
        same_ch = 0
        total   = 0
        for block in scan_out.split("BSS "):
            if not block.strip(): continue
            total += 1
            ch_m  = re.search(r"DS Parameter set: channel (\d+)", block)
            sig_m = re.search(r"signal:\s*([-\d.]+)", block)
            ssid_m= re.search(r"SSID:\s*(.+)", block)
            bss_m = re.search(r"^([\w:]{17})", block.strip())
            beacon_m = re.search(r"beacon interval:\s*(\d+)", block, re.IGNORECASE)
            phy = _wifi_phy_from_caps(block)
            bw  = _wifi_bw_from_caps(block)
            bssid = (bss_m.group(1).lower() if bss_m else "")
            if current_bssid and bssid == current_bssid:
                # Capabilities of the AP we are associated to
                result["phy_mode"]   = phy
                result["bandwidth"]  = bw
                if beacon_m:
                    try:
                        result["beacon_int"] = int(beacon_m.group(1))
                    except Exception:
                        pass
            if ch_m and current_ch and int(ch_m.group(1)) == current_ch:
                same_ch += 1
                result["neighbor_aps"].append({
                    "bssid":   bss_m.group(1) if bss_m else "?",
                    "ssid":    ssid_m.group(1).strip() if ssid_m else "",
                    "signal":  float(sig_m.group(1)) if sig_m else -99,
                    "channel": int(ch_m.group(1)),
                    "phy":     phy,
                    "bw":      bw,
                })
        result["co_channel_aps"] = same_ch
        result["total_aps_seen"] = total
    except Exception as e:
        result["scan_error"] = str(e)

    # 5. SNR (real noise floor if available, else -95 default)
    if result.get("rssi") is not None:
        nf = result.get("noise_floor")
        if nf is None:
            nf = -95
        result["snr"] = round(result["rssi"] - nf, 1)

    return result


@app.post("/api/wifits/diagnose")
async def wifits_diagnose(request: Request):
    """Motor de diagnóstico — cruza síntomas con datos reales del scan"""
    body = await request.json()
    symptoms  = body.get("symptoms", [])   # list of symptom keys
    scan_data = body.get("scan", {})        # result from /api/wifits/scan

    findings  = []  # {layer, severity, message, action}
    score     = 100 # health score, deducted per finding

    rssi    = scan_data.get("rssi")
    snr     = scan_data.get("snr")
    txrate  = scan_data.get("txrate")
    band    = scan_data.get("band", "")
    channel = scan_data.get("channel")
    ping_gw = scan_data.get("ping_gw", {})
    ping_dns= scan_data.get("ping_dns", {})
    dns_ms  = scan_data.get("dns_ms")
    co_ch   = scan_data.get("co_channel_aps", 0)
    connected = scan_data.get("connected", False)

    def add(layer, severity, msg, action, deduct=0):
        findings.append({"layer": layer, "severity": severity,
                         "message": msg, "action": action})
        nonlocal score
        score = max(0, score - deduct)

    # ── Layer 1: Association ─────────────────────────────────
    if not connected:
        add("Association", "critical",
            "Cliente no asociado al AP",
            "Verificar SSID, credenciales y que el AP esté operativo", 40)
    else:
        # ── Layer 2: RF / Signal ─────────────────────────────
        if rssi is not None:
            if rssi < -80:
                add("RF", "critical",
                    f"RSSI muy bajo ({rssi} dBm) — señal insuficiente",
                    "Acercar el cliente al AP o revisar ubicación del AP", 30)
            elif rssi < -70:
                add("RF", "warning",
                    f"RSSI marginal ({rssi} dBm) — límite enterprise",
                    "Considerar agregar AP o ajustar potencia de transmisión", 15)
            elif rssi > -55:
                pass  # excellent

        if snr is not None and snr < 20:
            add("RF", "warning",
                f"SNR bajo ({snr} dB) — posible interferencia o ruido",
                "Verificar fuentes de interferencia en la banda", 15)

        # ── Layer 2: Channel Interference ────────────────────
        if co_ch > 2:
            add("RF", "warning",
                f"{co_ch} APs co-canal detectados — interferencia CCI",
                "Cambiar canal del AP o usar banda 5GHz", 10)

        if band == "2.4GHz" and "slow" in symptoms:
            add("RF", "info",
                "Cliente en 2.4GHz — capacidad limitada",
                "Forzar cliente a 5GHz o activar Band Steering en el AP", 10)

        # ── Layer 3: Data Rate ────────────────────────────────
        if txrate is not None and txrate < 24:
            add("Rates", "warning",
                f"TX rate baja ({txrate} Mbps) — modulación reducida por RF",
                "Mejorar RSSI — target mínimo -67 dBm para MCS5+", 10)

        # ── Layer 4: Gateway reachability ────────────────────
        if ping_gw:
            if not ping_gw.get("reachable"):
                add("Wired/AP", "critical",
                    "Gateway no responde — problema en AP o uplink",
                    "Verificar cable del AP, VLAN y configuración de gateway", 35)
            elif ping_gw.get("loss_pct", 0) > 5:
                add("Wired/AP", "warning",
                    f"Pérdida de paquetes al gateway ({ping_gw['loss_pct']}%)",
                    "Verificar interferencia RF y roaming — posible sticky client", 15)
            elif ping_gw.get("avg_ms", 0) > 50:
                add("Wired/AP", "warning",
                    f"Latencia alta al gateway ({ping_gw['avg_ms']:.0f} ms)",
                    "Verificar carga del AP y canal de uplink", 10)

        # ── Layer 5: Internet / DNS ───────────────────────────
        if not ping_dns.get("reachable"):
            if ping_gw and ping_gw.get("reachable"):
                add("Network", "critical",
                    "Gateway OK pero internet no alcanzable",
                    "Problema en el uplink del router — verificar WAN", 25)
            else:
                add("Network", "info",
                    "Sin conectividad a internet",
                    "Derivado del problema en gateway", 0)

        if dns_ms is None:
            add("DNS", "warning",
                "Resolución DNS falló",
                "Verificar servidor DNS en la configuración de red", 15)
        elif dns_ms > 200:
            add("DNS", "warning",
                f"DNS lento ({dns_ms} ms)",
                "Cambiar a DNS local o usar 8.8.8.8 / 1.1.1.1", 5)

    # ── Síntomas sin datos medibles ──────────────────────────
    if "roaming" in symptoms:
        add("Roaming", "info",
            "Cliente reporta problemas de roaming",
            "Verificar 802.11r/k/v en el AP — usar módulo Roaming Analyzer", 5)
    if "auth_fail" in symptoms:
        add("Auth", "warning",
            "Fallas de autenticación reportadas",
            "Revisar credenciales, certificados y logs del RADIUS/PSK", 15)
    if "drops" in symptoms and not findings:
        add("RF", "info",
            "Drops intermitentes sin causa RF clara",
            "Monitorear con Path Analyzer — posible sticky client o DFS event", 5)

    # ── Health verdict ────────────────────────────────────────
    if score >= 85:
        verdict = "healthy"
        verdict_text = "Red WiFi saludable"
        verdict_color = "green"
    elif score >= 60:
        verdict = "degraded"
        verdict_text = "Rendimiento degradado"
        verdict_color = "amber"
    elif score >= 35:
        verdict = "poor"
        verdict_text = "Conectividad deficiente"
        verdict_color = "orange"
    else:
        verdict = "critical"
        verdict_text = "Problema crítico"
        verdict_color = "red"

    # Sort by severity
    sev_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda x: sev_order.get(x["severity"], 3))

    return {
        "score":        score,
        "verdict":      verdict,
        "verdict_text": verdict_text,
        "verdict_color": verdict_color,
        "findings":     findings,
        "scan":         scan_data,
    }


# ═══════════════════════════════════════════════════════════════
#  REPORTS — PDF + JSON export
# ═══════════════════════════════════════════════════════════════
from fastapi.responses import Response, JSONResponse
import html as _html_lib
import uuid as _uuid

REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

_REPORT_HISTORY: list = []  # [{id, ts, client, site, engineer, lang, pdf, json}]

_REPORT_I18N = {
    "en": {
        "title": "NekoPi Field Report",
        "client": "Client", "site": "Site", "engineer": "Engineer", "date": "Date",
        "exec_summary": "Executive Summary",
        "security": "Security Audit", "security_empty": "No audit data captured in this session.",
        "wifi": "WiFi Analysis", "wifi_empty": "No WiFi scan data captured.",
        "roaming": "Roaming Events", "roaming_empty": "No roaming events captured.",
        "network": "Network Inventory", "network_empty": "No inventory collected.",
        "qc": "Quick Check", "qc_empty": "No Quick Check data.",
        "recommendations": "Recommendations",
        "score": "Security Score",
        "findings_crit": "Critical", "findings_high": "High",
        "findings_med": "Medium", "findings_low": "Low",
        "generated_by": "Generated by NekoPi Field Unit",
    },
    "es": {
        "title": "Reporte de Campo NekoPi",
        "client": "Cliente", "site": "Sitio", "engineer": "Ingeniero", "date": "Fecha",
        "exec_summary": "Resumen Ejecutivo",
        "security": "Auditoría de Seguridad", "security_empty": "No se capturó auditoría en esta sesión.",
        "wifi": "Análisis WiFi", "wifi_empty": "No se capturaron datos WiFi.",
        "roaming": "Eventos de Roaming", "roaming_empty": "No se capturaron eventos de roaming.",
        "network": "Inventario de Red", "network_empty": "No se recolectó inventario.",
        "qc": "Chequeo Rápido", "qc_empty": "No hay datos de Chequeo Rápido.",
        "recommendations": "Recomendaciones",
        "score": "Score de Seguridad",
        "findings_crit": "Críticos", "findings_high": "Altos",
        "findings_med": "Medios", "findings_low": "Bajos",
        "generated_by": "Generado por NekoPi Field Unit",
    },
}

def _report_snapshot() -> dict:
    """Collects current backend state for embedding in a report."""
    snap = {
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "security": {
            "running":  _SEC_RUNNING,
            "score":    _SEC_SCORE,
            "summary":  dict(_SEC_SUMMARY) if _SEC_SUMMARY else {},
            "hosts":    list(_SEC_HOSTS),
            "findings": list(_SEC_FINDINGS),
        },
        "roaming": {
            "running": _ROAM_RUNNING,
            "ssid":    _ROAM_SSID,
            "iface":   _ROAM_IFACE,
            "events":  list(_ROAM_EVENTS)[-50:],
            "clients": {k: v for k, v in _ROAM_CLIENTS.items()},
        },
    }
    try:
        ifaces = get_interfaces()
        snap["network"] = {
            "gateway":    get_default_gateway(),
            "dns":        get_dns_servers(),
            "interfaces": ifaces,
        }
    except Exception as e:
        snap["network"] = {"error": str(e)}
    return snap

def _report_exec_summary(snap: dict, lang: str) -> str:
    sec = snap.get("security", {})
    score = sec.get("score", 100)
    findings = sec.get("findings") or []
    crit = sum(1 for f in findings if f.get("sev") == "critical")
    high = sum(1 for f in findings if f.get("sev") == "high")
    if lang == "es":
        verdict = ("riesgo crítico" if score < 50 else
                   "riesgo elevado" if score < 70 else
                   "riesgo moderado" if score < 85 else "postura saludable")
        return (f"La auditoría obtuvo un score de {score}/100 ({verdict}). "
                f"Se encontraron {len(findings)} hallazgos "
                f"({crit} críticos, {high} altos). "
                f"Se recomienda priorizar los hallazgos críticos y revisar la "
                f"configuración de los dispositivos de red identificados.")
    return (f"The audit scored {score}/100. "
            f"{len(findings)} findings were identified "
            f"({crit} critical, {high} high). "
            f"Prioritize critical findings and review the configuration of the "
            f"identified network devices.")

def _report_build_html(meta: dict, snap: dict) -> str:
    lang = meta.get("lang") or "en"
    if lang == "both":
        return _report_build_html({**meta, "lang": "en"}, snap) + \
               '<div style="page-break-before:always"></div>' + \
               _report_build_html({**meta, "lang": "es"}, snap)

    t = _REPORT_I18N.get(lang, _REPORT_I18N["en"])
    esc = _html_lib.escape
    sections = meta.get("sections") or ["exec","qc","wifi","security","roaming","wired","ai"]
    want = lambda key: key in sections

    sec = snap.get("security") or {}
    findings = sec.get("findings") or []
    crit = sum(1 for f in findings if f.get("sev") == "critical")
    high = sum(1 for f in findings if f.get("sev") == "high")
    med  = sum(1 for f in findings if f.get("sev") == "medium")
    low  = sum(1 for f in findings if f.get("sev") == "low")
    score = sec.get("score", 100)

    def _section(title, body_html):
        return f'<section><h2>{esc(title)}</h2>{body_html}</section>'

    # Security section
    if findings:
        rows = "".join(
            f'<tr><td class="sev sev-{esc(str(f.get("sev","")))}">{esc(str(f.get("sev","")).upper())}</td>'
            f'<td>{esc(str(f.get("title","")))}</td>'
            f'<td>{esc(str(f.get("host","")))}</td>'
            f'<td>{esc(str(f.get("detail","")))}</td></tr>'
            for f in findings
        )
        sec_body = (
            f'<div class="score-row">'
            f'<div class="score-big">{score}<span>/100</span></div>'
            f'<div class="score-pills">'
            f'<span class="pill crit">{crit} {t["findings_crit"]}</span>'
            f'<span class="pill high">{high} {t["findings_high"]}</span>'
            f'<span class="pill med">{med} {t["findings_med"]}</span>'
            f'<span class="pill low">{low} {t["findings_low"]}</span>'
            f'</div></div>'
            f'<table><thead><tr><th>Sev</th><th>Finding</th><th>Host</th><th>Detail</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
    else:
        sec_body = f'<p class="empty">{esc(t["security_empty"])}</p>'

    # Roaming section
    roam = snap.get("roaming") or {}
    roam_events = roam.get("events") or []
    if roam_events:
        rrows = "".join(
            f'<tr><td>{esc(str(e.get("ts","")))}</td>'
            f'<td>{esc(str(e.get("client","")))}</td>'
            f'<td>{esc(str(e.get("from_bssid","")))}</td>'
            f'<td>{esc(str(e.get("to_bssid","")))}</td>'
            f'<td>{esc(str(e.get("rssi","")))}</td></tr>'
            for e in roam_events[-20:]
        )
        roam_body = (
            f'<table><thead><tr><th>Time</th><th>Client</th><th>From BSSID</th>'
            f'<th>To BSSID</th><th>RSSI</th></tr></thead><tbody>{rrows}</tbody></table>'
        )
    else:
        roam_body = f'<p class="empty">{esc(t["roaming_empty"])}</p>'

    # Network
    net = snap.get("network") or {}
    ifaces = net.get("interfaces") or []
    if ifaces:
        irows = "".join(
            f'<tr><td>{esc(str(i.get("name","")))}</td>'
            f'<td>{esc(str(i.get("type","")))}</td>'
            f'<td>{esc(str(i.get("ip","")))}</td>'
            f'<td>{esc(str(i.get("mac","")))}</td></tr>'
            for i in ifaces
        )
        net_body = (
            f'<p><strong>Gateway:</strong> {esc(str(net.get("gateway","")))} '
            f'· <strong>DNS:</strong> {esc(", ".join(net.get("dns") or []))}</p>'
            f'<table><thead><tr><th>Iface</th><th>Type</th><th>IP</th><th>MAC</th></tr></thead>'
            f'<tbody>{irows}</tbody></table>'
        )
    else:
        net_body = f'<p class="empty">{esc(t["network_empty"])}</p>'

    exec_summary = _report_exec_summary(snap, lang)

    return f"""
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{esc(t["title"])} — {esc(meta.get("client",""))}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; @bottom-center {{ content: "{esc(t['generated_by'])} · Page " counter(page) " / " counter(pages); font-size: 9pt; color: #888; }} }}
  body {{ font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color:#222; font-size:10.5pt; }}
  header {{ border-bottom: 3px solid #2196F3; padding-bottom: 12px; margin-bottom: 18px; }}
  header h1 {{ font-family: "Bebas Neue", Arial, sans-serif; font-size: 28pt; letter-spacing: 2px; margin:0; color:#1a1a1a; }}
  header .meta {{ color:#555; font-size:10pt; margin-top:4px; }}
  header .client {{ color:#2196F3; font-weight:700; margin-top:6px; font-size:13pt; }}
  section {{ margin: 14px 0; break-inside: avoid; }}
  h2 {{ font-size: 13pt; color: #2196F3; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  table {{ width:100%; border-collapse: collapse; margin-top:6px; font-size:9.5pt; }}
  th, td {{ border: 1px solid #ddd; padding: 5px 7px; text-align: left; vertical-align: top; }}
  th {{ background: #f4f7fa; color:#333; font-weight:600; }}
  .empty {{ color:#888; font-style: italic; }}
  .score-row {{ display:flex; align-items:center; gap: 18px; margin:10px 0; }}
  .score-big {{ font-size: 36pt; font-weight: 700; color:#2196F3; line-height:1; }}
  .score-big span {{ font-size: 14pt; color:#888; }}
  .score-pills {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .pill {{ padding:4px 10px; border-radius:10px; font-size:9pt; font-weight:600; color:#fff; }}
  .pill.crit {{ background:#e53935; }}
  .pill.high {{ background:#fb8c00; }}
  .pill.med  {{ background:#fdd835; color:#333; }}
  .pill.low  {{ background:#1e88e5; }}
  .sev {{ font-weight:700; font-size:8.5pt; text-align:center; }}
  .sev-critical {{ background:#ffebee; color:#b71c1c; }}
  .sev-high {{ background:#fff3e0; color:#e65100; }}
  .sev-medium {{ background:#fffde7; color:#f57f17; }}
  .sev-low {{ background:#e3f2fd; color:#0d47a1; }}
  .exec {{ background:#f4f7fa; border-left: 4px solid #2196F3; padding:10px 14px; border-radius:2px; }}
</style>
</head>
<body>
  <header>
    <h1>{esc(t["title"])}</h1>
    <div class="client">{esc(meta.get("client","—"))}</div>
    <div class="meta">
      <strong>{esc(t["site"])}:</strong> {esc(meta.get("site","—"))} ·
      <strong>{esc(t["engineer"])}:</strong> {esc(meta.get("engineer","—"))} ·
      <strong>{esc(t["date"])}:</strong> {esc(meta.get("date", time.strftime("%Y-%m-%d")))}
    </div>
  </header>

  {(_section(t["exec_summary"], f'<div class="exec">{esc(exec_summary)}</div>') if want("exec") else "")}
  {(_section(t["security"], sec_body) if want("security") else "")}
  {(_section(t["roaming"], roam_body) if want("roaming") else "")}
  {(_section(t["network"], net_body) if (want("wired") or want("qc") or want("wifi")) else "")}
</body>
</html>
"""

_REPORT_PDF_ERROR: str = ""  # last WeasyPrint failure, surfaced to UI

def _report_render_pdf(html: str) -> bytes | None:
    """Returns PDF bytes if WeasyPrint is available. Surfaces the failure
    reason via _REPORT_PDF_ERROR so the UI can show "PDF unavailable: …"
    instead of silently falling back to HTML."""
    global _REPORT_PDF_ERROR
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as e:
        _REPORT_PDF_ERROR = f"WeasyPrint not installed: {e}"
        return None
    except Exception as e:
        # Native lib (cairo/pango/fontconfig) load failure — most common on Pi
        _REPORT_PDF_ERROR = f"WeasyPrint import failed: {e}"
        return None
    try:
        return HTML(string=html).write_pdf()
    except Exception as e:
        _REPORT_PDF_ERROR = f"WeasyPrint render failed: {e}"
        return None

@app.post("/api/reports/export")
async def reports_export(request: Request):
    """Returns a JSON snapshot of the current session for archival."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    meta = {
        "client":   (body.get("client")   or "—"),
        "site":     (body.get("site")     or "—"),
        "engineer": (body.get("engineer") or "—"),
        "lang":     (body.get("lang")     or "en"),
        "date":     time.strftime("%Y-%m-%d"),
        "sections": body.get("sections") or [],
    }
    snap = _report_snapshot()
    rid  = _uuid.uuid4().hex[:12]
    payload = {"id": rid, "meta": meta, "snapshot": snap}

    try:
        (REPORTS_DIR / f"{rid}.json").write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception:
        pass

    _REPORT_HISTORY.insert(0, {
        "id": rid, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "client": meta["client"], "site": meta["site"],
        "engineer": meta["engineer"], "lang": meta["lang"],
        "json": f"{rid}.json", "pdf": None,
    })
    if len(_REPORT_HISTORY) > 50:
        del _REPORT_HISTORY[50:]

    safe_client = re.sub(r"[^A-Za-z0-9._-]", "_", meta["client"])[:40] or "client"
    fname = f'nekopi-report-{safe_client}-{meta["date"]}.json'
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

@app.post("/api/reports/generate")
async def reports_generate(request: Request):
    """Generates a PDF report (WeasyPrint) or falls back to HTML if WeasyPrint
    is not installed. Saves a copy under /opt/nekopi/reports/."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    meta = {
        "client":   body.get("client")   or "Client",
        "site":     body.get("site")     or "Site",
        "engineer": body.get("engineer") or "Engineer",
        "lang":     body.get("lang")     or "en",
        "date":     time.strftime("%Y-%m-%d"),
        "sections": body.get("sections") or [],
    }
    snap = _report_snapshot()
    html = _report_build_html(meta, snap)
    pdf  = _report_render_pdf(html)

    rid = _uuid.uuid4().hex[:12]
    safe_client = re.sub(r"[^A-Za-z0-9._-]", "_", meta["client"])[:40] or "client"

    if pdf:
        fname = f'nekopi-report-{safe_client}-{meta["date"]}.pdf'
        try:
            (REPORTS_DIR / f"{rid}.pdf").write_bytes(pdf)
        except Exception:
            pass
        _REPORT_HISTORY.insert(0, {
            "id": rid, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "client": meta["client"], "site": meta["site"],
            "engineer": meta["engineer"], "lang": meta["lang"],
            "pdf": f"{rid}.pdf", "json": None,
        })
        if len(_REPORT_HISTORY) > 50:
            del _REPORT_HISTORY[50:]
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"',
                     "X-Nekopi-Report-Id": rid,
                     "X-Nekopi-Report-Format": "pdf"},
        )

    # Fallback: WeasyPrint not available → return HTML so the user can print-to-PDF.
    fname = f'nekopi-report-{safe_client}-{meta["date"]}.html'
    try:
        (REPORTS_DIR / f"{rid}.html").write_text(html)
    except Exception:
        pass
    _REPORT_HISTORY.insert(0, {
        "id": rid, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "client": meta["client"], "site": meta["site"],
        "engineer": meta["engineer"], "lang": meta["lang"],
        "pdf": None, "json": None, "html": f"{rid}.html",
    })
    if len(_REPORT_HISTORY) > 50:
        del _REPORT_HISTORY[50:]
    note = _REPORT_PDF_ERROR or "WeasyPrint not installed - served as HTML"
    return Response(
        content=html, media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{fname}"',
                 "X-Nekopi-Report-Id": rid,
                 "X-Nekopi-Report-Format": "html",
                 "X-Nekopi-Report-Note": note[:240]},
    )

@app.get("/api/reports/list")
async def reports_list():
    return {"reports": _REPORT_HISTORY}

@app.get("/api/reports/download/{rid}")
async def reports_download(rid: str):
    for ext in ("pdf", "html", "json"):
        p = REPORTS_DIR / f"{rid}.{ext}"
        if p.exists():
            media = {"pdf": "application/pdf", "html": "text/html",
                     "json": "application/json"}[ext]
            return FileResponse(str(p), media_type=media,
                                filename=f"nekopi-report-{rid}.{ext}")
    return JSONResponse({"error": "not found"}, status_code=404)


# ═══════════════════════════════════════════════════════════════
#  AI — remote backends only (Gemini API or remote Ollama agent)
#  The RPi is NEVER an Ollama host: Ollama URLs always point to a
#  remote machine on the engineer's lab/laptop network.
# ═══════════════════════════════════════════════════════════════
import urllib.request as _ai_req
import urllib.error   as _ai_err

SETTINGS_FILE = BASE_DIR / "data" / "settings.json"

def _settings_load() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        pass
    return {}

def _settings_save(d: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass

# Shared posture/safety preamble — applied to every module call so the
# assistant never replaces the on-site engineer's judgement.
AI_POSTURE_PROMPT = (
    "Eres un asistente de diagnóstico de redes para ingenieros de campo. "
    "Tu rol es SUGERIR y ORIENTAR, NO reemplazar el criterio del ingeniero.\n\n"
    "Reglas estrictas:\n"
    "- USA frases como: 'podría indicar', 'una posible causa es', "
    "'te sugiero verificar', 'esto podría deberse a'.\n"
    "- EVITA: 'el problema ES', 'la causa ES', afirmaciones absolutas sin "
    "verificación física.\n"
    "- Siempre termina con una línea: 'Para confirmar, verifica en sitio: ...'.\n"
    "- Si los datos no son suficientes para orientar, indícalo y pide la "
    "información faltante. No inventes datos que no están en el contexto recibido.\n"
    "- Responde SIEMPRE en español, máximo 4 párrafos, directo y técnico."
)

def _gemini_endpoint(model: str) -> str:
    return ("https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent")

def _ai_call_gemini(prompt: str, key: str, model: str) -> tuple[str, str]:
    if not key:
        raise RuntimeError("Gemini API key not configured")
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": f"{AI_POSTURE_PROMPT}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 768},
    }).encode()
    url = f"{_gemini_endpoint(model)}?key={key}"
    req = _ai_req.Request(url, data=body, headers={"Content-Type": "application/json"})
    with _ai_req.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
        cands = data.get("candidates") or []
        if not cands:
            return "", model
        parts = (cands[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts).strip(), model

def _ai_call_ollama(prompt: str, base_url: str) -> tuple[str, str]:
    """Calls a REMOTE Ollama agent — never localhost. Auto-detects model
    if none stored."""
    if not base_url:
        raise RuntimeError("Ollama URL not configured")
    base = base_url.rstrip("/")
    # Pick first available model (the remote agent decides what's installed)
    try:
        with _ai_req.urlopen(f"{base}/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
            models = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
    except Exception as e:
        raise RuntimeError(f"No se pudo conectar al agente Ollama remoto: {e}")
    if not models:
        raise RuntimeError("El agente remoto no tiene modelos instalados")
    model = models[0]
    body = json.dumps({
        "model": model,
        "prompt": f"{AI_POSTURE_PROMPT}\n\n{prompt}",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512, "num_ctx": 2048},
    }).encode()
    req = _ai_req.Request(f"{base}/api/generate", data=body,
                          headers={"Content-Type": "application/json"})
    with _ai_req.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
        return (data.get("response") or "").strip(), model

def _ai_probe_ollama(url: str) -> tuple[bool, str]:
    """Returns (online, first_model_name) for the given remote Ollama URL."""
    if not url:
        return False, ""
    try:
        with _ai_req.urlopen(f"{url.rstrip('/')}/api/tags", timeout=2) as r:
            tags = json.loads(r.read())
            ms = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
            if ms:
                return True, ms[0]
    except Exception:
        pass
    return False, ""


@app.get("/api/ai/status")
async def ai_status():
    """Returns the live state of BOTH backends. callAI() decides which one
    to use per call (privacy via localOnly, otherwise prefer Gemini)."""
    s = _settings_load()
    gemini_key   = s.get("gemini_key") or ""
    gemini_model = s.get("gemini_model") or "gemini-1.5-flash"
    ollama_url   = s.get("ollama_url") or ""

    gemini_configured = bool(gemini_key)
    gemini_online     = gemini_configured  # key presence is enough for Gemini

    ollama_configured = bool(ollama_url)
    ollama_online, ollama_model = _ai_probe_ollama(ollama_url) if ollama_configured else (False, "")

    # Default backend (no localOnly): prefer Gemini if configured, else Ollama.
    # localOnly callers always use Ollama regardless of this default.
    default_backend = None
    default_model   = ""
    if gemini_online:
        default_backend, default_model = "gemini", gemini_model
    elif ollama_online:
        default_backend, default_model = "ollama", ollama_model

    return {
        "gemini": {
            "configured": gemini_configured,
            "online":     gemini_online,
            "model":      gemini_model,
        },
        "ollama": {
            "configured": ollama_configured,
            "online":     ollama_online,
            "model":      ollama_model,
            "url":        ollama_url,
        },
        # Back-compat fields used by older callers — derived from above
        "backend": default_backend,
        "online":  bool(default_backend),
        "model":   default_model,
    }


@app.post("/api/ai/gemini")
async def ai_gemini(request: Request):
    """Body: { prompt: str }. Reads key from settings."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"ok": False, "error": "empty prompt"}, status_code=400)
    s = _settings_load()
    key = s.get("gemini_key") or ""
    if not key:
        return JSONResponse({"ok": False, "error": "Gemini API key not configured"},
                            status_code=400)
    model = s.get("gemini_model") or "gemini-1.5-flash"
    try:
        text, used = _ai_call_gemini(prompt, key, model)
        return {"ok": True, "backend": "gemini", "model": used, "response": text}
    except _ai_err.HTTPError as e:
        try:    detail = e.read().decode("utf-8", "ignore")[:300]
        except: detail = ""
        return JSONResponse(
            {"ok": False, "backend": "gemini",
             "error": f"HTTP {e.code}: {e.reason} {detail}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "backend": "gemini",
                             "error": str(e)}, status_code=502)


@app.post("/api/ai/ollama")
async def ai_ollama(request: Request):
    """Body: { prompt: str }. Reads remote URL from settings (NOT localhost)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse({"ok": False, "error": "empty prompt"}, status_code=400)
    s = _settings_load()
    url = s.get("ollama_url") or ""
    if not url:
        return JSONResponse({"ok": False, "error": "Ollama URL not configured"},
                            status_code=400)
    try:
        text, used = _ai_call_ollama(prompt, url)
        return {"ok": True, "backend": "ollama", "model": used, "response": text}
    except _ai_err.HTTPError as e:
        try:    detail = e.read().decode("utf-8", "ignore")[:300]
        except: detail = ""
        return JSONResponse(
            {"ok": False, "backend": "ollama",
             "error": f"HTTP {e.code}: {e.reason} {detail}"}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "backend": "ollama",
                             "error": str(e)}, status_code=502)


@app.post("/api/ai/test/gemini")
async def ai_test_gemini(request: Request):
    """Validates a Gemini API key by sending a tiny ping prompt."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    key   = (body.get("key") or "").strip()
    model = (body.get("model") or "gemini-1.5-flash").strip() or "gemini-1.5-flash"
    if not key:
        return JSONResponse({"ok": False, "error": "missing key"}, status_code=400)
    try:
        text, used = _ai_call_gemini("Responde solo: ok", key, model)
        return {"ok": True, "model": used, "response": text}
    except _ai_err.HTTPError as e:
        return JSONResponse({"ok": False, "error": f"HTTP {e.code}: {e.reason}"},
                            status_code=200)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


@app.post("/api/ai/test/ollama")
async def ai_test_ollama(request: Request):
    """Probes a remote Ollama URL: /api/tags then a tiny generate call."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = (body.get("url") or "").strip().rstrip("/")
    if not url:
        return JSONResponse({"ok": False, "error": "missing url"}, status_code=400)
    # Step 1 — discover models
    try:
        with _ai_req.urlopen(f"{url}/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
            models = [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
    except Exception as e:
        return {"ok": False, "error": "No se encuentra agente en esa dirección",
                "detail": str(e)}
    if not models:
        return {"ok": False, "error": "El agente respondió pero no tiene modelos instalados"}
    # Step 2 — confirm model can answer
    model = models[0]
    try:
        body2 = json.dumps({
            "model": model, "prompt": "responde solo: ok", "stream": False,
            "options": {"temperature": 0.0, "num_predict": 16},
        }).encode()
        req = _ai_req.Request(f"{url}/api/generate", data=body2,
                              headers={"Content-Type": "application/json"})
        with _ai_req.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            text = (data.get("response") or "").strip()
    except Exception as e:
        return {"ok": True, "model": model, "warning": f"tags ok, generate failed: {e}",
                "models": models}
    return {"ok": True, "model": model, "models": models, "response": text}

# ═══════════════════════════════════════════════════════════════
#  SENSOR MODE — pktvisor integration (on-demand only)
# ═══════════════════════════════════════════════════════════════
PKTVISOR_BIN = BASE_DIR / "bin" / "pktvisord"
PKTVISOR_HOST = "127.0.0.1"
PKTVISOR_PORT = 10853

_PKT = {"proc": None, "iface": "", "started_at": 0}

def _pktvisor_running() -> bool:
    p = _PKT.get("proc")
    return bool(p and p.poll() is None)

@app.post("/api/sensor/start")
async def sensor_start(iface: str = "auto"):
    """Launches pktvisord against the given iface. The nekopi service has
    CAP_NET_RAW + CAP_NET_ADMIN as ambient caps, so the child inherits them."""
    if not PKTVISOR_BIN.exists():
        return {"ok": False, "error": "pktvisord not installed at " + str(PKTVISOR_BIN)}
    if _pktvisor_running():
        return {"ok": True, "iface": _PKT["iface"], "running": True, "note": "already running"}

    # Sanitize iface — avoid shell injection
    if not re.match(r"^(auto|[a-zA-Z0-9_-]+)$", iface or ""):
        return {"ok": False, "error": "invalid iface"}

    cmd = [str(PKTVISOR_BIN), "-l", PKTVISOR_HOST, "-p", str(PKTVISOR_PORT),
           "--no-track", iface]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Give pktvisord ~1.2s to bind to the interface; if it dies, surface why.
    time.sleep(1.2)
    if proc.poll() is not None:
        try:    err = (proc.stderr.read() or "")[-300:]
        except: err = ""
        return {"ok": False, "error": f"pktvisord exited (rc={proc.returncode}): {err.strip()}"}

    _PKT["proc"] = proc
    _PKT["iface"] = iface
    _PKT["started_at"] = int(time.time())
    return {"ok": True, "iface": iface, "running": True,
            "url": f"http://{PKTVISOR_HOST}:{PKTVISOR_PORT}"}

@app.post("/api/sensor/stop")
async def sensor_stop():
    p = _PKT.get("proc")
    if p and p.poll() is None:
        try: p.terminate()
        except Exception: pass
        try: p.wait(timeout=3)
        except Exception:
            try: p.kill()
            except Exception: pass
    _PKT["proc"] = None
    _PKT["iface"] = ""
    return {"ok": True, "running": False}


# ── PCAP capture (one-shot, downloadable + Deep Analysis fodder) ──
CAPTURE_DIR = BASE_DIR / "captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/api/sensor/pcap/capture")
async def sensor_pcap_capture(iface: str = "eth1", seconds: int = 10, count: int = 0):
    """Captures live traffic to a downloadable .pcap. Default: 10 seconds on
    eth1. The file lives in /opt/nekopi/captures/ so the Deep Analysis module
    can analyze it locally without ever leaving the device."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", iface):
        return {"ok": False, "error": "invalid iface"}
    if seconds < 1 or seconds > 120:
        seconds = 10
    if count < 0 or count > 50000:
        count = 0
    fname = f"sensor-{int(time.time())}-{iface}.pcap"
    fpath = CAPTURE_DIR / fname
    cmd = ["sudo", "tcpdump", "-i", iface, "-w", str(fpath),
           "-G", str(seconds), "-W", "1"]
    if count > 0:
        cmd += ["-c", str(count)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=seconds + 8)
    except subprocess.TimeoutExpired:
        # tcpdump should self-terminate at -G seconds, but cap it just in case
        return {"ok": False, "error": "capture timeout"}
    if not fpath.exists() or fpath.stat().st_size == 0:
        return {"ok": False, "error": (proc.stderr or "no packets captured")[-300:]}
    return {"ok": True, "file": fname, "size": fpath.stat().st_size,
            "iface": iface, "seconds": seconds}


@app.get("/api/sensor/pcap/list")
async def sensor_pcap_list():
    files = []
    for p in sorted(CAPTURE_DIR.glob("*.pcap"), key=lambda f: f.stat().st_mtime, reverse=True):
        files.append({"name": p.name, "size": p.stat().st_size,
                      "mtime": int(p.stat().st_mtime)})
    return {"files": files[:50]}


@app.get("/api/sensor/pcap/download")
async def sensor_pcap_download(name: str):
    # Strict filename whitelist — no path traversal
    if not re.match(r"^[a-zA-Z0-9._-]+\.pcap$", name):
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    p = CAPTURE_DIR / name
    if not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(str(p), media_type="application/vnd.tcpdump.pcap",
                        filename=name)


_ANON_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")
_ANON_MAC  = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")

def _make_anonymizer():
    """Returns a (text → text) anonymizer that replaces internal IPs with
    Host-A, Host-B, … in deterministic order. Public addresses are masked
    only by their last octet so the model still sees the network topology
    without leaking the real address. Used by the Deep Analysis pipeline
    so cloud providers (Gemini) never see raw client IPs/MACs."""
    seen: dict[str, str] = {}
    next_label = [0]
    def label_for(ip: str) -> str:
        if ip in seen:
            return seen[ip]
        # RFC1918 + CGNAT + link-local treated as "internal"
        parts = ip.split(".")
        try:
            o1, o2 = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return ip
        is_internal = (
            o1 == 10 or
            (o1 == 172 and 16 <= o2 <= 31) or
            (o1 == 192 and o2 == 168) or
            (o1 == 100 and 64 <= o2 <= 127) or
            (o1 == 169 and o2 == 254) or
            ip.startswith("127.")
        )
        if is_internal:
            idx = next_label[0]
            next_label[0] += 1
            # Host-A, Host-B, …, Host-AA after Z
            if idx < 26:
                lbl = "Host-" + chr(ord("A") + idx)
            else:
                lbl = f"Host-{idx}"
        else:
            # Public: keep only the /24 prefix
            lbl = f"{parts[0]}.{parts[1]}.{parts[2]}.x"
        seen[ip] = lbl
        return lbl

    mac_seen: dict[str, str] = {}
    def label_for_mac(mac: str) -> str:
        if mac in mac_seen:
            return mac_seen[mac]
        idx = len(mac_seen)
        if idx < 26:
            lbl = "MAC-" + chr(ord("A") + idx)
        else:
            lbl = f"MAC-{idx}"
        mac_seen[mac] = lbl
        return lbl

    def anonymize(text: str) -> str:
        if not text:
            return text
        text = _ANON_IPV4.sub(lambda m: label_for(m.group(1)), text)
        text = _ANON_MAC.sub(lambda m: label_for_mac(m.group(0)), text)
        return text

    anonymize.label_for = label_for
    anonymize.label_for_mac = label_for_mac
    anonymize.seen_ips = seen
    anonymize.seen_macs = mac_seen
    return anonymize


def _pcap_summary(path: Path) -> dict:
    """Summarizes a pcap with tshark — packet count, protocols, top talkers,
    DNS queries, anomaly hints. The output is fed verbatim to the LLM via the
    Deep Analysis module. The summary stays raw here; anonymization is applied
    later by the deep-analyze pipeline so the same helper can serve both
    local-only Ollama and cloud Gemini callers."""
    if not shutil.which("tshark"):
        return {"ok": False, "error": "tshark not installed"}
    try:
        info = subprocess.run(
            ["tshark", "-r", str(path), "-q", "-z", "io,stat,0"],
            capture_output=True, text=True, timeout=20)
        conv = subprocess.run(
            ["tshark", "-r", str(path), "-q", "-z", "conv,ip"],
            capture_output=True, text=True, timeout=20)
        proto = subprocess.run(
            ["tshark", "-r", str(path), "-q", "-z", "io,phs"],
            capture_output=True, text=True, timeout=20)
        dns = subprocess.run(
            ["tshark", "-r", str(path), "-Y", "dns.qry.name", "-T", "fields",
             "-e", "dns.qry.name"],
            capture_output=True, text=True, timeout=20)
        # Bonus: cheap anomaly hints — broadcast volume, top DST ports
        bcast = subprocess.run(
            ["tshark", "-r", str(path), "-Y", "eth.dst == ff:ff:ff:ff:ff:ff",
             "-T", "fields", "-e", "frame.number"],
            capture_output=True, text=True, timeout=20)
        ports = subprocess.run(
            ["tshark", "-r", str(path), "-q", "-z", "endpoints,tcp"],
            capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tshark timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    dns_counts: dict[str, int] = {}
    for line in (dns.stdout or "").splitlines():
        q = line.strip()
        if q:
            dns_counts[q] = dns_counts.get(q, 0) + 1
    top_dns = sorted(dns_counts.items(), key=lambda x: -x[1])[:15]
    bcast_count = len([l for l in (bcast.stdout or "").splitlines() if l.strip()])

    return {
        "ok": True,
        "io_stat":     (info.stdout or "")[-1500:],
        "top_conv":    (conv.stdout or "")[-2000:],
        "protocols":   (proto.stdout or "")[-1500:],
        "top_dns":     [{"name": n, "count": c} for n, c in top_dns],
        "broadcast_count": bcast_count,
        "tcp_endpoints":   (ports.stdout or "")[-1500:],
    }


@app.get("/api/sensor/pcap/summary")
async def sensor_pcap_summary(name: str):
    if not re.match(r"^[a-zA-Z0-9._-]+\.pcap$", name):
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    p = CAPTURE_DIR / name
    if not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return _pcap_summary(p)


@app.post("/api/sensor/pcap/analyze")
async def sensor_pcap_analyze(name: str):
    """Runs the Deep Analysis pipeline (anonymize → Gemini/Ollama) against a
    pcap that's already on disk in CAPTURE_DIR — used by Sensor Mode so the
    engineer can analyze a capture without re-uploading it."""
    if not re.match(r"^[a-zA-Z0-9._-]+\.pcap$", name):
        return JSONResponse({"ok": False, "error": "invalid filename"}, status_code=400)
    p = CAPTURE_DIR / name
    if not p.exists():
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    s = _pcap_summary(p)
    if not s.get("ok"):
        return JSONResponse({"ok": False, "error": s.get("error", "pcap parse failed")},
                            status_code=500)
    summary = {"name": name, "size": p.stat().st_size, "ext": "pcap", "pcap": s}
    anon = _make_anonymizer()
    prompt = _build_deep_prompt("pcap", name, summary, anon)
    summary["anon_map"] = {"ips": len(anon.seen_ips), "macs": len(anon.seen_macs)}

    cfg = _settings_load()
    gemini_key = cfg.get("gemini_key") or ""
    ollama_url = cfg.get("ollama_url") or ""
    backend = None
    response = ""
    model = ""
    error = None

    if gemini_key:
        try:
            response, model = _ai_call_gemini(
                prompt, gemini_key, cfg.get("gemini_model") or "gemini-1.5-flash")
            backend = "gemini"
        except Exception as e:
            error = f"Gemini failed: {e}"
    if not response and ollama_url:
        try:
            response, model = _ai_call_ollama(prompt, ollama_url)
            backend = "ollama"
            error = None
        except Exception as e:
            error = (error + " · " if error else "") + f"Ollama failed: {e}"

    if not response:
        return JSONResponse({"ok": False, "error": error or "No AI backend configured",
                             "summary": summary}, status_code=502)

    return {"ok": True, "backend": backend, "model": model,
            "response": response, "summary": summary}


# ── Deep Analysis: file upload + summary for the AI module ──────────
DEEP_ANALYSIS_DIR = BASE_DIR / "captures" / "deep"
DEEP_ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
DEEP_ANALYSIS_MAX = 20 * 1024 * 1024  # 20 MB

def _deep_summary_log(text: str) -> dict:
    """Best-effort log summary: counts, top tokens, error/warning lines."""
    lines = text.splitlines()
    crit = []
    warn = []
    err  = []
    pat_crit = re.compile(r"(?i)\b(critical|fatal|panic|emerg)\b")
    pat_err  = re.compile(r"(?i)\b(error|failed|denied|unreachable|timeout)\b")
    pat_warn = re.compile(r"(?i)\b(warn|warning|deprecated|retry)\b")
    for ln in lines:
        if pat_crit.search(ln): crit.append(ln)
        elif pat_err.search(ln): err.append(ln)
        elif pat_warn.search(ln): warn.append(ln)
    return {
        "lines":    len(lines),
        "critical": crit[:25],
        "errors":   err[:25],
        "warnings": warn[:15],
        "head":     lines[:15],
        "tail":     lines[-15:] if len(lines) > 15 else [],
    }

def _deep_summary_config(text: str) -> dict:
    """Cisco-style config summary: count interfaces, ACLs, ssh/telnet, vlans."""
    lines = text.splitlines()
    return {
        "lines":          len(lines),
        "hostname":       (re.findall(r"^hostname\s+(\S+)", text, re.M) or ["—"])[0],
        "version":        (re.findall(r"^version\s+(\S+)", text, re.M) or ["—"])[0],
        "interfaces":     len(re.findall(r"^interface\s+\S+", text, re.M)),
        "acl_count":      len(re.findall(r"^(?:ip\s+)?access-list\s+", text, re.M)),
        "vlans":          len(re.findall(r"^vlan\s+\d+", text, re.M)),
        "ssh_present":    "ip ssh version" in text or "transport input ssh" in text,
        "telnet_present": "transport input telnet" in text or "transport input all" in text,
        "no_password_service": "service password-encryption" not in text,
        "snmp_v2_communities": re.findall(r"snmp-server community\s+(\S+)", text)[:5],
        "head":           lines[:15],
    }

def _build_deep_prompt(ext: str, fname: str, summary: dict, anon) -> str:
    """Builds the cloud-safe prompt for the Deep Analysis pipeline. Every
    field is run through the anonymizer so internal IPs/MACs become
    Host-A/MAC-A before reaching the model."""
    parts = [
        f"Archivo: {fname} · tipo: {ext}",
        "",
        "NOTA DE PRIVACIDAD: las IPs internas del cliente fueron reemplazadas",
        "por etiquetas Host-A, Host-B, … y las MACs por MAC-A, MAC-B, …",
        "Las IPs públicas se muestran con el último octeto enmascarado.",
        "No solicites las IPs reales — el ingeniero las verifica en sitio.",
        "",
    ]
    if ext in ("pcap", "pcapng"):
        pc = summary.get("pcap") or {}
        top_dns = "\n".join(
            f"  {anon(d['name'])} ({d['count']})" for d in (pc.get("top_dns") or [])
        ) or "  (sin DNS)"
        parts += [
            "=== I/O STAT (anonimizado) ===",
            anon(pc.get("io_stat") or ""),
            "",
            "=== TOP CONVERSATIONS (anonimizado) ===",
            anon(pc.get("top_conv") or ""),
            "",
            "=== PROTOCOL HIERARCHY ===",
            pc.get("protocols") or "",
            "",
            "=== TCP ENDPOINTS (anonimizado) ===",
            anon(pc.get("tcp_endpoints") or ""),
            "",
            "=== TOP DNS QUERIES (anonimizado) ===",
            top_dns,
            "",
            f"Broadcast frames detectados: {pc.get('broadcast_count', 0)}",
            "",
            "Resume top talkers, distribución de protocolos, anomalías "
            "(broadcast storm, posibles port scans, DNS sospechoso) y "
            "sugiere qué validar en sitio.",
        ]
    elif ext in ("cfg", "conf"):
        cf = summary.get("config") or {}
        parts += [
            f"Hostname: {anon(cf.get('hostname','—'))}",
            f"Versión: {cf.get('version','—')}",
            f"Interfaces configuradas: {cf.get('interfaces',0)}",
            f"VLANs: {cf.get('vlans',0)}",
            f"ACLs: {cf.get('acl_count',0)}",
            f"SSH presente: {cf.get('ssh_present')}",
            f"Telnet presente: {cf.get('telnet_present')} (riesgo si True)",
            f"service password-encryption ausente: {cf.get('no_password_service')}",
            f"SNMP v2 communities: {', '.join(cf.get('snmp_v2_communities') or []) or '(ninguna)'}",
            "",
            "Primeras líneas (anonimizadas):",
            anon("\n".join(cf.get("head") or [])),
            "",
            "Revisa esta configuración bajo buenas prácticas (gestión segura, "
            "hardening, logging). Sugiere qué validar.",
        ]
    else:  # log/txt
        lg = summary.get("log") or {}
        parts += [
            f"Líneas: {lg.get('lines', 0)} · Críticos: {len(lg.get('critical', []))}"
            f" · Errores: {len(lg.get('errors', []))} · Warnings: {len(lg.get('warnings', []))}",
            "",
            "=== CRÍTICOS (anonimizado) ===",
            anon("\n".join((lg.get("critical") or [])[:12])),
            "",
            "=== ERRORES (anonimizado) ===",
            anon("\n".join((lg.get("errors") or [])[:12])),
            "",
            "=== WARNINGS (anonimizado) ===",
            anon("\n".join((lg.get("warnings") or [])[:8])),
            "",
            "Identifica patrones sospechosos, fallas críticas y servicios "
            "afectados. Sugiere qué investigar primero.",
        ]
    return "\n".join(parts)


@app.post("/api/ai/deep-analyze")
async def ai_deep_analyze(file: UploadFile = File(...)):
    """Hybrid Deep Analysis pipeline:
      1. Receive the raw file (pcap/log/cfg/conf/txt).
      2. Pre-process LOCALLY → tshark/regex extracts metrics, anomalies, etc.
      3. Anonymize the summary (Host-A, Host-B, MAC-A, …) — the raw file
         and real IPs NEVER leave the device.
      4. Dispatch the anonymized summary to Gemini (preferred for quality)
         or fall back to a remote Ollama agent if Gemini is not configured.
      5. Return the anonymized summary + the model response so the engineer
         can audit what actually went out to the cloud.
    """
    name = (file.filename or "").strip()
    if not re.match(r"^[\w.\- ]+$", name):
        return JSONResponse({"ok": False, "error": "invalid filename"}, status_code=400)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("pcap", "pcapng", "log", "txt", "cfg", "conf"):
        return JSONResponse({"ok": False, "error": "unsupported file type"}, status_code=400)

    safe_name = f"{int(time.time())}-{name.replace(' ', '_')}"
    dest = DEEP_ANALYSIS_DIR / safe_name
    size = 0
    with dest.open("wb") as fh:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > DEEP_ANALYSIS_MAX:
                fh.close()
                dest.unlink(missing_ok=True)
                return JSONResponse({"ok": False, "error": "file too large (max 20MB)"},
                                    status_code=413)
            fh.write(chunk)

    # Step 1 — local pre-processing
    summary: dict = {"name": safe_name, "size": size, "ext": ext}
    if ext in ("pcap", "pcapng"):
        s = _pcap_summary(dest)
        if not s.get("ok"):
            return JSONResponse({"ok": False, "error": s.get("error", "pcap parse failed")},
                                status_code=500)
        summary["pcap"] = s
    elif ext in ("cfg", "conf"):
        try:
            text = dest.read_text("utf-8", errors="replace")[:200_000]
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        summary["config"] = _deep_summary_config(text)
    else:
        try:
            text = dest.read_text("utf-8", errors="replace")[:200_000]
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        summary["log"] = _deep_summary_log(text)

    # Step 2 — anonymize + build prompt
    anon = _make_anonymizer()
    prompt = _build_deep_prompt(ext, name, summary, anon)
    summary["anonymized_prompt"] = prompt
    summary["anon_map"] = {
        "ips":  len(anon.seen_ips),
        "macs": len(anon.seen_macs),
    }

    # Step 3 — dispatch to Gemini (preferred) or Ollama (fallback)
    s = _settings_load()
    gemini_key = s.get("gemini_key") or ""
    ollama_url = s.get("ollama_url") or ""
    backend = None
    response = ""
    model = ""
    error = None

    if gemini_key:
        try:
            response, model = _ai_call_gemini(
                prompt, gemini_key, s.get("gemini_model") or "gemini-1.5-flash")
            backend = "gemini"
        except Exception as e:
            error = f"Gemini failed: {e}"
            # fall through to Ollama

    if not response and ollama_url:
        try:
            response, model = _ai_call_ollama(prompt, ollama_url)
            backend = "ollama"
            error = None
        except Exception as e:
            error = (error + " · " if error else "") + f"Ollama failed: {e}"

    if not response:
        return JSONResponse({
            "ok":      False,
            "error":   error or "No AI backend configured",
            "summary": {k: v for k, v in summary.items() if k != "pcap"},
        }, status_code=502)

    return {
        "ok":       True,
        "backend":  backend,
        "model":    model,
        "response": response,
        "summary":  summary,
    }


# Back-compat alias — older Edge AI build called this path
@app.post("/api/ai/deep/upload")
async def ai_deep_upload_legacy(file: UploadFile = File(...)):
    return await ai_deep_analyze(file)

@app.get("/api/sensor/status")
async def sensor_status():
    return {
        "running":    _pktvisor_running(),
        "iface":      _PKT.get("iface", ""),
        "started_at": _PKT.get("started_at", 0),
        "binary":     str(PKTVISOR_BIN),
        "binary_present": PKTVISOR_BIN.exists(),
    }

@app.get("/api/sensor/metrics")
async def sensor_metrics(window: int = 2):
    """Proxies pktvisord and returns curated metrics: throughput, packet
    counts, top talkers, top DNS queries, and protocol breakdown.

    pktvisord only accepts window values of 2 or 5 (minutes)."""
    if not _pktvisor_running():
        return {"running": False, "error": "pktvisor is not running"}
    if window not in (2, 5):
        window = 2
    try:
        url = f"http://{PKTVISOR_HOST}:{PKTVISOR_PORT}/api/v1/metrics/window/{int(window)}"
        with _ai_req.urlopen(url, timeout=4) as r:
            raw = json.loads(r.read())
    except Exception as e:
        return {"running": True, "error": str(e)}

    # pktvisor wraps the response under "<N>m" (e.g. "2m")
    bucket = raw.get(f"{window}m") if isinstance(raw, dict) else None
    if not isinstance(bucket, dict):
        return {"running": True, "error": "unexpected pktvisor schema",
                "raw_keys": list(raw.keys()) if isinstance(raw, dict) else []}

    def _g(d, *keys):
        cur = d
        for k in keys:
            if not isinstance(cur, dict): return None
            cur = cur.get(k)
        return cur

    # pktvisor 4.x exposes the net handler under "packets" with flat counters.
    pkts = bucket.get("packets") or bucket.get("net") or {}
    dns  = bucket.get("dns") or {}

    duration_s = _g(pkts, "period", "length") or _g(dns, "period", "length") or (window * 60)

    rates_bytes = _g(pkts, "rates", "bytes_total", "live")
    bps = (rates_bytes * 8 / 1e6) if rates_bytes is not None else None

    return {
        "running":     True,
        "iface":       _PKT.get("iface", ""),
        "window_min":  window,
        "duration_s":  duration_s,
        "packets":     {
            "total": pkts.get("total", 0),
            "in":    pkts.get("in", 0),
            "out":   pkts.get("out", 0),
            "tcp":   pkts.get("tcp", 0),
            "udp":   pkts.get("udp", 0),
            "other": pkts.get("other_l4", 0),
            "ipv4":  pkts.get("ipv4", 0),
            "ipv6":  pkts.get("ipv6", 0),
        },
        "rates":       {
            "bps_live":  rates_bytes or 0,
            "pps_live":  _g(pkts, "rates", "pps_total", "live") or 0,
            "pps_in":    _g(pkts, "rates", "pps_in",    "live") or 0,
            "pps_out":   _g(pkts, "rates", "pps_out",   "live") or 0,
        },
        "throughput_mbps": round(bps, 3) if bps is not None else None,
        "dns":         {
            "queries": dns.get("total") or _g(dns, "wire_packets", "total") or 0,
            "top":     (dns.get("top_qname2") or [])[:10],
            "top_qtype": (dns.get("top_qtype") or [])[:5],
        },
        "top_talkers": {
            "ipv4": (pkts.get("top_ipv4") or [])[:10],
            "ipv6": (pkts.get("top_ipv6") or [])[:5],
        },
        "handlers":    [k for k in bucket.keys() if k != "period"],
    }

@app.get("/api/wifi/interfaces")
async def wifi_interfaces():
    """Lists wireless interfaces, marking which support monitor mode.
    Used by the Roaming Analyzer to refuse non-monitor-capable adapters."""
    out = run_cmd(["iw", "dev"], timeout=4)
    items: list[dict] = []
    cur: dict | None = None
    for line in out.splitlines():
        ls = line.strip()
        m = re.match(r"phy#(\d+)", ls)
        if m:
            cur_phy = "phy" + m.group(1)
            continue
        m = re.match(r"Interface\s+(\S+)", ls)
        if m:
            cur = {"name": m.group(1), "phy": cur_phy if "cur_phy" in locals() else "",
                   "type": "", "monitor": False}
            items.append(cur)
            continue
        if cur and ls.startswith("type "):
            cur["type"] = ls.split(" ", 1)[1].strip()

    # Check monitor support per phy
    phys: dict[str, bool] = {}
    for it in items:
        phy = it.get("phy", "")
        if phy and phy not in phys:
            info = run_cmd(["iw", "phy", phy, "info"], timeout=4)
            phys[phy] = "* monitor" in info or " monitor\n" in info or "monitor\n" in info
        it["monitor"] = phys.get(phy, False)
    return {"interfaces": items}

# ── Terminal sessions: ttyd local bash + per-host ttyd SSH ───────────
# We spawn one ttyd process per remote SSH session on a free port and proxy
# the iframe to the engineer. No SSH password ever touches the backend — the
# user types it inside the embedded terminal.
TTYD_BIN = shutil.which("ttyd") or "/usr/bin/ttyd"
_TTYD_LOCAL_PORT = 7681  # the systemd ttyd service port for local bash
_TTYD_SSH_PORT_BASE = 7700
_TTYD_SESSIONS: dict[str, dict] = {}  # session_id → {proc, port, host, user}

def _ttyd_alloc_port() -> int:
    used = {s.get("port") for s in _TTYD_SESSIONS.values()}
    for p in range(_TTYD_SSH_PORT_BASE, _TTYD_SSH_PORT_BASE + 30):
        if p in used:
            continue
        if _port_open(p):
            continue
        return p
    raise RuntimeError("no free ttyd port available")

@app.get("/api/terminal/local")
async def terminal_local():
    """Returns the URL of the local-bash ttyd already managed by systemd."""
    return {
        "ok": _port_open(_TTYD_LOCAL_PORT),
        "port": _TTYD_LOCAL_PORT,
        "url":  f"http://{{host}}:{_TTYD_LOCAL_PORT}/",
    }

@app.post("/api/terminal/ssh")
async def terminal_ssh(request: Request):
    """Spawns a one-shot ttyd that runs `ssh user@host`. The engineer types
    the password inside the embedded terminal — no credentials touch the
    backend. Returns {ok, session_id, port}."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    host = (body.get("host") or "").strip()
    user = (body.get("user") or "nekopi").strip()
    port_ssh = int(body.get("port") or 22)
    if not re.match(r"^[\w.\-]+$", host or ""):
        return JSONResponse({"ok": False, "error": "invalid host"}, status_code=400)
    if not re.match(r"^[\w.\-]+$", user):
        return JSONResponse({"ok": False, "error": "invalid user"}, status_code=400)
    if port_ssh < 1 or port_ssh > 65535:
        return JSONResponse({"ok": False, "error": "invalid port"}, status_code=400)
    if not Path(TTYD_BIN).exists():
        return JSONResponse({"ok": False, "error": "ttyd not installed"}, status_code=500)
    try:
        ttyd_port = _ttyd_alloc_port()
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    cmd = [
        TTYD_BIN, "-p", str(ttyd_port), "-W",
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-p", str(port_ssh),
        f"{user}@{host}",
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    time.sleep(0.6)
    if proc.poll() is not None:
        try:    err = (proc.stderr.read() or "")[-300:]
        except: err = ""
        return JSONResponse({"ok": False, "error": f"ttyd exited: {err.strip()}"},
                            status_code=500)
    session_id = f"sess-{int(time.time())}-{ttyd_port}"
    _TTYD_SESSIONS[session_id] = {
        "proc": proc, "port": ttyd_port, "host": host, "user": user,
        "started_at": int(time.time()),
    }
    return {"ok": True, "session_id": session_id, "port": ttyd_port,
            "host": host, "user": user}

@app.post("/api/terminal/stop")
async def terminal_stop(session_id: str):
    sess = _TTYD_SESSIONS.pop(session_id, None)
    if not sess:
        return {"ok": True, "note": "no such session"}
    proc = sess.get("proc")
    if proc and proc.poll() is None:
        try: proc.terminate()
        except Exception: pass
        try: proc.wait(timeout=3)
        except Exception:
            try: proc.kill()
            except Exception: pass
    return {"ok": True}

@app.get("/api/terminal/sessions")
async def terminal_sessions():
    out = []
    dead = []
    for sid, s in _TTYD_SESSIONS.items():
        proc = s.get("proc")
        if proc and proc.poll() is None:
            out.append({"session_id": sid, "port": s["port"],
                        "host": s["host"], "user": s["user"],
                        "started_at": s["started_at"]})
        else:
            dead.append(sid)
    for sid in dead:
        _TTYD_SESSIONS.pop(sid, None)
    return {"sessions": out}


@app.get("/api/system/logs")
async def system_logs(unit: str = "nekopi", lines: int = 200):
    """Returns the last N journalctl lines, optionally filtered to a unit."""
    cmd = ["journalctl", "-n", str(max(10, min(lines, 1000))), "--no-pager"]
    if unit:
        cmd += ["-u", unit]
    out = run_cmd(cmd, timeout=8)
    return {"unit": unit or "system", "lines": out.splitlines() if out else []}

@app.get("/api/settings")
async def settings_get():
    s = _settings_load()
    return {
        "ollama_url":   s.get("ollama_url",   ""),
        "gemini_key":   "••••••••" if s.get("gemini_key") else "",
        "gemini_model": s.get("gemini_model", "gemini-1.5-flash"),
        "ui_lang":      s.get("ui_lang", "es"),
        "client_name":  s.get("client_name", ""),
        "engineer":     s.get("engineer", ""),
        "device_name":  s.get("device_name", ""),
    }

@app.post("/api/settings")
async def settings_set(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    cur = _settings_load()
    for k in ("ollama_url", "gemini_model",
              "ui_lang", "client_name", "engineer", "device_name"):
        if k in body and body[k] is not None:
            cur[k] = str(body[k]).strip()
    # gemini_key only updated when caller sends a non-mask value
    if "gemini_key" in body and body["gemini_key"] is not None:
        v = str(body["gemini_key"]).strip()
        if v and not v.startswith("•"):
            cur["gemini_key"] = v
        elif v == "":
            cur.pop("gemini_key", None)
    # Drop the legacy radio field if present
    cur.pop("ai_backend", None)
    _settings_save(cur)
    return {"ok": True}
