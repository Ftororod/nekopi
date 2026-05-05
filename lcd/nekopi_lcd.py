#!/usr/bin/env python3
"""
NekoPi LCD HAT Daemon — state machine + screen navigation.
All GPIO/SPI on main thread. Input polling enqueues events.
Background threads handle API polling and timers via the queue.
"""

import sys
import os
import time
import threading
import traceback
from queue import Queue, Empty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lgpio
from lib.st7735s import LCD
from lib.input import Input
from lib.api import get
from lib.actions import ACTIONS, SUBMENUS, HOME_STATUS_ICONS
from lib import api_actions
from lib.local_state import LocalState

import screens.splash
import screens.home
import screens.menu
import screens.dashboard
import screens.quickcheck
import screens.wifiscan
import screens.system
import screens.power
import screens.tools
import screens.captures
import screens.services
import screens.action_view as action_view

# Menu items — order matches menu.py ITEMS
MENU_TARGETS = [
    "dashboard", "tools", "captures", "services",
    "quickcheck", "wifiscan", "system", "power",
]

SUBMENU_KEYS = {"tools", "captures", "services"}
AUTO_REFRESH_SCREENS = {"HOME", "SCREEN_dashboard", "SCREEN_system"}

POWER_CONFIRM_S = 5
ACTION_CONFIRM_S = 5


class App:
    def __init__(self):
        self._gpio = lgpio.gpiochip_open(4)
        self.lcd = LCD(gpio_handle=self._gpio)
        self.queue = Queue()
        self.input = Input(callback=lambda e: self.queue.put(("input", e)),
                           gpio_handle=self._gpio)

        self.state = "SPLASH"
        self.backlight_on = True
        self.local = LocalState()
        self.dirty = True
        self._running = True

        # Shared context
        self.ctx = {
            "about": None, "metrics": None, "network": None, "traffic": None, "wifi_info": None,
            "menu_idx": 0,
            "submenu_idx": 0, "submenu_key": None,
            "action_id": None,
            "statuses": {},
            "status_data": {},
            "results_cache": {},
            "results_ts": {},
            # Home rotativo
            "home_page": "network",
            "home_auto_rotate": True,
            "home_data": {},  # latency, public_ip — from home worker
            # Power
            "power_idx": 0, "power_confirm": False, "power_confirm_remaining": 0,
            # QC / WiFi
            "qc_state": "idle", "qc_result": None,
            "wifi_state": "idle", "wifi_results": None, "wifi_offset": 0,
            # Action confirm
            "confirm_level": 0, "confirm_countdown": 0, "confirm_deadline": 0,
            # Spinner
            "spinner_frame": 0, "action_message": "",
        }
        self._home_last_rotate = time.time()

    # ── RENDERING ─────────────────────────────────────────────

    def _render(self):
        try:
            img = self._render_state()
            if img:
                self.lcd.show_image(img)
        except Exception:
            traceback.print_exc()

    def _render_state(self):
        s = self.state
        ctx = self.ctx

        if s == "SPLASH":
            return screens.splash.render(ctx)
        if s == "HOME":
            return screens.home.render(ctx)
        if s == "MENU":
            return screens.menu.render(ctx)
        if s == "SUBMENU":
            key = ctx["submenu_key"]
            mod = {"tools": screens.tools, "captures": screens.captures,
                   "services": screens.services}.get(key)
            return mod.render(ctx) if mod else None

        if s == "SCREEN_dashboard":
            return screens.dashboard.render(ctx)
        if s == "SCREEN_quickcheck":
            return screens.quickcheck.render(ctx)
        if s == "SCREEN_wifiscan":
            return screens.wifiscan.render(ctx)
        if s == "SCREEN_system":
            return screens.system.render(ctx)
        if s == "SCREEN_power":
            return screens.power.render(ctx)

        if s == "ACTION_VIEW":
            return action_view.render(ctx["action_id"], ctx)
        if s in ("ACTION_CONFIRM_1", "ACTION_CONFIRM_2"):
            level = 1 if s == "ACTION_CONFIRM_1" else 2
            return action_view.render_confirm(
                ctx["action_id"], ctx, level=level,
                countdown=ctx["confirm_countdown"])
        if s == "ACTION_RUNNING":
            return action_view.render_transient(
                "running", ctx["action_id"], ctx=ctx,
                spinner_frame=ctx["spinner_frame"],
                message=ctx["action_message"])
        if s == "ACTION_SUCCESS":
            return action_view.render_transient(
                "success", ctx["action_id"], ctx=ctx,
                message=ctx["action_message"])
        if s == "ACTION_ERROR":
            return action_view.render_transient(
                "error", ctx["action_id"], ctx=ctx,
                message=ctx["action_message"])

        return None

    # ── INPUT HANDLING ────────────────────────────────────────

    def _handle_input(self, event):
        s = self.state

        # Global shortcuts (except transient states)
        if s not in ("SPLASH", "ACTION_CONFIRM_1", "ACTION_CONFIRM_2",
                      "ACTION_RUNNING", "ACTION_SUCCESS", "ACTION_ERROR"):
            if event == "KEY1":
                if s == "HOME":
                    # Reset to page 1 + reactivate auto-rotate
                    self.ctx["home_page"] = "network"
                    self.ctx["home_auto_rotate"] = True
                    self._home_last_rotate = time.time()
                    self.dirty = True
                else:
                    self._goto("HOME")
                self._fetch_data_async()
                return
            if event == "KEY3":
                self.backlight_on = not self.backlight_on
                self.lcd.backlight(self.backlight_on)
                return
            if event == "KEY2":
                self._fetch_data_async()
                if s == "ACTION_VIEW":
                    self._refresh_action_status()
                elif s == "SCREEN_quickcheck":
                    self._run_quickcheck()
                elif s == "SCREEN_wifiscan":
                    self._run_wifiscan()
                self.dirty = True
                return

        handler = getattr(self, f"_input_{s}", None)
        if handler:
            handler(event)

    def _input_HOME(self, event):
        if event == "PRESS":
            self._goto("MENU")
        elif event == "RIGHT":
            if not self.ctx["home_auto_rotate"]:
                self._home_next_page()
            else:
                self._goto("MENU")
        elif event == "LEFT":
            self.ctx["home_auto_rotate"] = False
            self._home_prev_page()
        elif event == "DOWN":
            self.ctx["home_auto_rotate"] = False
            self._home_next_page()
        elif event == "UP":
            self.ctx["home_auto_rotate"] = False
            self._home_prev_page()

    def _input_MENU(self, event):
        if event == "UP":
            self.ctx["menu_idx"] = (self.ctx["menu_idx"] - 1) % len(MENU_TARGETS)
            self.dirty = True
        elif event == "DOWN":
            self.ctx["menu_idx"] = (self.ctx["menu_idx"] + 1) % len(MENU_TARGETS)
            self.dirty = True
        elif event in ("PRESS", "RIGHT"):
            target = MENU_TARGETS[self.ctx["menu_idx"]]
            if target in SUBMENU_KEYS:
                self.ctx["submenu_key"] = target
                self.ctx["submenu_idx"] = 0
                self._goto("SUBMENU")
            elif target == "power":
                self.ctx["power_idx"] = 0
                self.ctx["power_confirm"] = False
                self._goto("SCREEN_power")
            else:
                self._goto(f"SCREEN_{target}")
                self._fetch_data_async()
        elif event == "LEFT":
            self._goto("HOME")
            self._fetch_data_async()

    def _input_SUBMENU(self, event):
        key = self.ctx["submenu_key"]
        items = SUBMENUS[key]
        if event == "UP":
            self.ctx["submenu_idx"] = (self.ctx["submenu_idx"] - 1) % len(items)
            self.dirty = True
        elif event == "DOWN":
            self.ctx["submenu_idx"] = (self.ctx["submenu_idx"] + 1) % len(items)
            self.dirty = True
        elif event in ("PRESS", "RIGHT"):
            action_id = items[self.ctx["submenu_idx"]]
            self.ctx["action_id"] = action_id
            self._refresh_action_status()
            self._goto("ACTION_VIEW")
        elif event == "LEFT":
            self._goto("MENU")

    def _input_ACTION_VIEW(self, event):
        if event == "LEFT":
            self._goto("SUBMENU")
        elif event == "PRESS":
            action_id = self.ctx["action_id"]
            action = ACTIONS.get(action_id, {})
            atype = action.get("type")

            if atype == "info":
                return  # info screens have no action on PRESS

            # Start confirm flow
            self.ctx["confirm_level"] = 1
            self.ctx["confirm_countdown"] = ACTION_CONFIRM_S
            self.ctx["confirm_deadline"] = time.monotonic() + ACTION_CONFIRM_S
            self._goto("ACTION_CONFIRM_1")

    def _input_ACTION_CONFIRM_1(self, event):
        if event == "LEFT":
            self._goto("ACTION_VIEW")
        elif event == "PRESS":
            action_id = self.ctx["action_id"]
            action = ACTIONS.get(action_id, {})
            if action.get("warn_destructive"):
                # Need second confirm
                self.ctx["confirm_level"] = 2
                self.ctx["confirm_countdown"] = ACTION_CONFIRM_S
                self.ctx["confirm_deadline"] = time.monotonic() + ACTION_CONFIRM_S
                self._goto("ACTION_CONFIRM_2")
            else:
                self._execute_action()

    def _input_ACTION_CONFIRM_2(self, event):
        if event == "LEFT":
            self._goto("ACTION_VIEW")
        elif event == "PRESS":
            self._execute_action()

    # Power screen has its own confirm flow
    def _input_SCREEN_power(self, event):
        if event == "LEFT":
            self.ctx["power_confirm"] = False
            self._goto("MENU")
        elif event == "UP":
            self.ctx["power_confirm"] = False
            self.ctx["power_idx"] = (self.ctx["power_idx"] - 1) % 3
            self.dirty = True
        elif event == "DOWN":
            self.ctx["power_confirm"] = False
            self.ctx["power_idx"] = (self.ctx["power_idx"] + 1) % 3
            self.dirty = True
        elif event == "PRESS":
            idx = self.ctx["power_idx"]
            if idx == 0:
                self._goto("MENU")
            elif self.ctx["power_confirm"]:
                self.ctx["power_confirm"] = False
                action = "reboot" if idx == 1 else "shutdown"
                self._execute_power(action)
            else:
                self.ctx["power_confirm"] = True
                self.ctx["power_confirm_remaining"] = POWER_CONFIRM_S
                self.ctx["_power_deadline"] = time.monotonic() + POWER_CONFIRM_S
                self.dirty = True

    # Simple sub-screens
    def _input_SCREEN_dashboard(self, event):
        if event == "LEFT":
            self._goto("MENU")

    def _input_SCREEN_system(self, event):
        if event == "LEFT":
            self._goto("MENU")

    def _input_SCREEN_quickcheck(self, event):
        if event == "LEFT":
            self.ctx["qc_state"] = "idle"
            self._goto("MENU")
        elif event == "PRESS":
            self._run_quickcheck()

    def _input_SCREEN_wifiscan(self, event):
        if event == "LEFT":
            self.ctx["wifi_state"] = "idle"
            self._goto("MENU")
        elif event == "PRESS":
            self._run_wifiscan()
        elif event == "UP" and self.ctx["wifi_offset"] > 0:
            self.ctx["wifi_offset"] -= 1
            self.dirty = True
        elif event == "DOWN":
            self.ctx["wifi_offset"] += 1
            self.dirty = True

    # ── HOME PAGE ROTATION ────────────────────────────────────

    def _home_next_page(self):
        from screens.home import PAGES
        cur = self.ctx['home_page']
        idx = (PAGES.index(cur) + 1) % len(PAGES) if cur in PAGES else 0
        self.ctx['home_page'] = PAGES[idx]
        self._home_last_rotate = time.time()
        self.dirty = True

    def _home_prev_page(self):
        from screens.home import PAGES
        cur = self.ctx['home_page']
        idx = (PAGES.index(cur) - 1) % len(PAGES) if cur in PAGES else 0
        self.ctx['home_page'] = PAGES[idx]
        self._home_last_rotate = time.time()
        self.dirty = True

    # ── STATE TRANSITIONS ─────────────────────────────────────

    def _goto(self, new_state):
        self.state = new_state
        self.dirty = True

    # ── ACTION EXECUTION ──────────────────────────────────────

    def _execute_action(self):
        action_id = self.ctx["action_id"]
        action = ACTIONS.get(action_id, {})
        atype = action.get("type")
        status = self.ctx["statuses"].get(action_id, "stopped")

        if atype == "toggle":
            op = "stop" if status == "running" else "start"
            self.ctx["action_message"] = f"{'Stopping' if op == 'stop' else 'Starting'}..."
        else:
            op = "run"
            self.ctx["action_message"] = action.get("feedback_text", "Running...")

        self.ctx["spinner_frame"] = 0
        self._goto("ACTION_RUNNING")

        def _worker():
            result = api_actions.execute(action_id, op, self.ctx)
            self.queue.put(("action_result", action_id, op, result))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_action_result(self, action_id, op, result):
        if result.get("ok"):
            self.ctx["action_message"] = "Done"

            action = ACTIONS.get(action_id, {})
            atype = action.get("type")

            if atype == "toggle":
                if op == "start":
                    self.ctx["statuses"][action_id] = "running"
                    self.local.on_action_start(action_id)
                else:
                    self.ctx["statuses"][action_id] = "stopped"
                    self.local.on_action_stop(action_id)

            elif atype == "oneshot":
                data = result.get("data")
                self.local.on_oneshot_complete(action_id, data)
                self.ctx["results_cache"] = dict(self.local.results_cache)
                self.ctx["results_ts"] = dict(self.local.results_ts)

            # Refresh action status data
            self._refresh_action_status()
            self._goto("ACTION_SUCCESS")
            # Auto-return after 1.5s
            threading.Thread(target=self._auto_return, args=(1.5,), daemon=True).start()
        else:
            self.ctx["action_message"] = result.get("error", "Failed")[:40]
            self._goto("ACTION_ERROR")
            threading.Thread(target=self._auto_return, args=(3.0,), daemon=True).start()

    def _auto_return(self, delay):
        time.sleep(delay)
        self.queue.put(("goto", "ACTION_VIEW"))

    def _execute_power(self, action):
        """POST to reboot/shutdown — show splash variant and stay until killed."""
        variant = 'rebooting' if action == 'reboot' else 'shutdown'

        # Show splash immediately
        self.lcd.show_image(screens.splash.render(variant=variant))

        # Call API (may not respond — system is going down)
        import urllib.request, ssl
        ctx_ssl = ssl.create_default_context()
        ctx_ssl.check_hostname = False
        ctx_ssl.verify_mode = ssl.CERT_NONE
        try:
            req = urllib.request.Request(
                f"https://localhost:8080/api/system/{action}",
                method="POST", data=b"")
            urllib.request.urlopen(req, timeout=5, context=ctx_ssl)
        except Exception:
            pass

        # Stay in this screen until systemd kills us
        while True:
            self.lcd.show_image(screens.splash.render(variant=variant))
            time.sleep(1)

    # ── ASYNC DATA + STATUS ───────────────────────────────────

    def _fetch_data_sync(self):
        self.ctx["about"] = get("/api/about")
        self.ctx["metrics"] = get("/api/system/metrics")
        self.ctx["network"] = get("/api/network/info")
        self.ctx["traffic"] = get("/api/network/traffic")
        self.ctx["wifi_info"] = get("/api/wifi/info")

    def _fetch_data_async(self):
        def _w():
            about = get("/api/about")
            metrics = get("/api/system/metrics")
            network = get("/api/network/info")
            traffic = get("/api/network/traffic")
            wifi_info = get("/api/wifi/info")
            self.queue.put(("data", about, metrics, network, traffic, wifi_info))
        threading.Thread(target=_w, daemon=True).start()

    def _refresh_action_status(self):
        """Refresh status for current action in background."""
        action_id = self.ctx.get("action_id")
        if not action_id:
            return
        def _w():
            data = api_actions.fetch_status(action_id)
            if data is not None:
                self.queue.put(("action_status", action_id, data))
        threading.Thread(target=_w, daemon=True).start()

    def _run_quickcheck(self):
        if self.ctx["qc_state"] == "running":
            return
        self.ctx["qc_state"] = "running"
        self.dirty = True
        def _w():
            result = get("/api/qc/run")
            self.queue.put(("qc_done", result))
        threading.Thread(target=_w, daemon=True).start()

    def _run_wifiscan(self):
        if self.ctx["wifi_state"] == "running":
            return
        self.ctx["wifi_state"] = "running"
        self.ctx["wifi_offset"] = 0
        self.dirty = True
        def _w():
            result = get("/api/wifi/scan?iface=wlan2")
            self.queue.put(("wifi_done", result))
        threading.Thread(target=_w, daemon=True).start()

    # ── QUEUE MESSAGE PROCESSING ──────────────────────────────

    def _process_message(self, msg):
        tag = msg[0]

        if tag == "input":
            self._handle_input(msg[1])

        elif tag == "data":
            _, about, metrics, network, traffic, wifi_info = msg
            self.ctx["about"] = about
            self.ctx["metrics"] = metrics
            self.ctx["network"] = network
            self.ctx["traffic"] = traffic
            self.ctx["wifi_info"] = wifi_info
            self.dirty = True

        elif tag == "action_status":
            _, action_id, data = msg
            self.ctx["status_data"][action_id] = data
            action = ACTIONS.get(action_id, {})
            sf = action.get("status_field")
            if sf and isinstance(data, dict):
                self.ctx["statuses"][action_id] = "running" if data.get(sf) else "stopped"
            self.dirty = True

        elif tag == "action_result":
            _, action_id, op, result = msg
            self._on_action_result(action_id, op, result)

        elif tag == "goto":
            self._goto(msg[1])

        elif tag == "qc_done":
            self.ctx["qc_result"] = msg[1]
            self.ctx["qc_state"] = "done"
            if self.state == "SCREEN_quickcheck":
                self.dirty = True

        elif tag == "wifi_done":
            self.ctx["wifi_results"] = msg[1]
            self.ctx["wifi_state"] = "done"
            if self.state == "SCREEN_wifiscan":
                self.dirty = True

        elif tag == "status_poll":
            # Batch update of all statuses
            for action_id, data in msg[1].items():
                self.ctx["status_data"][action_id] = data
                action = ACTIONS.get(action_id, {})
                sf = action.get("status_field")
                if sf and isinstance(data, dict):
                    self.ctx["statuses"][action_id] = "running" if data.get(sf) else "stopped"
            self.dirty = True

    # ── BACKGROUND WORKERS ────────────────────────────────────

    def _status_polling_worker(self):
        """Poll status of all actions with status endpoints every 8s."""
        while self._running:
            try:
                results = {}
                for action_id, action in ACTIONS.items():
                    if action.get("status"):
                        data = api_actions.fetch_status(action_id)
                        if data is not None:
                            results[action_id] = data
                if results:
                    self.queue.put(("status_poll", results))
            except Exception:
                traceback.print_exc()
            time.sleep(8)

    def _auto_refresh_worker(self):
        """Auto-refresh data for screens that need it."""
        while self._running:
            time.sleep(5)
            try:
                if self.state in AUTO_REFRESH_SCREENS:
                    self._fetch_data_async()
                elif self.state == "ACTION_VIEW":
                    action_id = self.ctx.get("action_id")
                    if action_id:
                        action = ACTIONS.get(action_id, {})
                        rs = action.get("refresh_seconds", 0)
                        if rs > 0:
                            self._refresh_action_status()
                            if action_id == "network_traffic":
                                self._fetch_data_async()
            except Exception:
                traceback.print_exc()

    def _home_data_worker(self):
        """Staggered polling for Home page data.

        - Every 10s: /api/system/metrics + /api/network/info + DHCP lease + CIDRs
        - Every 30s: one latency test (rotating: gateway, dns_local, google_dns, cloudflare)
        - Every 300s: /api/network/public-ip
        """
        import collections
        import subprocess

        LATENCY_TESTS = [
            ('gateway',    '/api/qc/gateway',             'rtt_avg'),
            ('dns_local',  '/api/qc/dns',                 'ms'),
            ('google_dns', '/api/qc/dns?server=8.8.8.8',  'ms'),
            ('cloudflare', '/api/qc/ping?target=1.1.1.1', 'rtt_avg'),
        ]

        latency_idx = 0
        last_metrics = 0
        last_latency = 0
        last_public_ip = 0

        lat_cache = {}
        lat_history = {k: collections.deque(maxlen=10) for k, _, _ in LATENCY_TESTS}
        public_ip_cache = None

        def poll_metrics():
            metrics = get("/api/system/metrics")
            if metrics:
                self.ctx["metrics"] = metrics

        def poll_network():
            network = get("/api/network/info")
            if network:
                self.ctx["network"] = network

        def poll_cidrs():
            """Get CIDRs from ip addr — API doesn't provide mask."""
            try:
                out = subprocess.check_output(
                    ["ip", "-4", "-o", "addr", "show"], timeout=5,
                    text=True, stderr=subprocess.DEVNULL)
                cidrs = {}
                for line in out.splitlines():
                    parts = line.split()
                    # Format: idx name inet IP/CIDR ...
                    if len(parts) >= 4:
                        iface = parts[1]
                        cidr = parts[3]  # e.g. 192.168.50.156/24
                        if iface in ('eth0', 'eth1', 'wlan0'):
                            cidrs[iface] = cidr
                self.ctx["home_data"]["cidrs"] = cidrs
            except Exception:
                pass

        def poll_dhcp_lease():
            """Read last active DHCP lease from dnsmasq for eth1 clients."""
            try:
                with open('/var/lib/misc/dnsmasq.leases') as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4 and parts[2].startswith('192.168.99.'):
                            self.ctx["home_data"]["dhcp_client_ip"] = parts[2]
                            return
                # No lease found
                self.ctx["home_data"]["dhcp_client_ip"] = None
            except Exception:
                pass

        lat_ts = {}  # timestamps per test

        def poll_latency(idx):
            key, endpoint, field = LATENCY_TESTS[idx % len(LATENCY_TESTS)]
            try:
                r = get(endpoint)
                if r and r.get("ok"):
                    ms = r.get(field)
                    if ms is not None:
                        lat_cache[key] = ms
                        lat_history[key].append(ms)
                        lat_ts[key] = time.time()
            except Exception:
                pass
            self.ctx["home_data"]["latency"] = dict(lat_cache)
            self.ctx["home_data"]["latency_history"] = {
                k: list(v) for k, v in lat_history.items()
            }
            self.ctx["home_data"]["latency_ts"] = dict(lat_ts)

        def poll_hotspot():
            try:
                r = get("/api/hotspot/status")
                if r and isinstance(r, dict):
                    self.ctx["home_data"]["hotspot"] = r
            except Exception:
                pass

        def poll_public_ip():
            nonlocal public_ip_cache
            try:
                r = get("/api/network/public-ip")
                if r and r.get("ok"):
                    public_ip_cache = r.get("ip")
            except Exception:
                pass
            if public_ip_cache:
                self.ctx["home_data"]["public_ip"] = public_ip_cache

        # ─── Initial sync (fill cache ASAP) ───
        try:
            poll_metrics()
            poll_network()
            poll_cidrs()
            poll_dhcp_lease()
            poll_hotspot()
            poll_latency(0)
            latency_idx = 1
            poll_public_ip()
            last_metrics = time.time()
            last_latency = time.time()
            last_public_ip = time.time()
            if self.state == "HOME":
                self.dirty = True
        except Exception:
            traceback.print_exc()

        # ─── Main polling loop ───
        while self._running:
            time.sleep(1)
            now = time.time()
            updated = False

            try:
                # Metrics + network + DHCP + hotspot every 10s
                if now - last_metrics >= 10.0:
                    last_metrics = now
                    poll_metrics()
                    poll_network()
                    poll_cidrs()
                    poll_dhcp_lease()
                    poll_hotspot()
                    updated = True

                # One latency test every 10s (rotating — full cycle 40s)
                if now - last_latency >= 10.0:
                    last_latency = now
                    poll_latency(latency_idx)
                    latency_idx += 1
                    updated = True

                # Public IP every 300s
                if now - last_public_ip >= 300.0:
                    last_public_ip = now
                    poll_public_ip()
                    updated = True

                if updated and self.state == "HOME":
                    self.dirty = True

            except Exception:
                traceback.print_exc()

    def _timer_worker(self):
        """Handle timed events: confirm countdowns, spinner, power confirm, home rotate."""
        while self._running:
            time.sleep(0.2)
            try:
                # Home auto-rotate
                if self.state == "HOME" and self.ctx.get("home_auto_rotate", True):
                    if time.time() - self._home_last_rotate >= 6.0:
                        self._home_next_page()

                # Spinner animation
                if self.state == "ACTION_RUNNING":
                    self.ctx["spinner_frame"] = (self.ctx["spinner_frame"] + 1) % 8
                    self.dirty = True

                # Confirm countdown
                if self.state in ("ACTION_CONFIRM_1", "ACTION_CONFIRM_2"):
                    deadline = self.ctx.get("confirm_deadline", 0)
                    remaining = max(0, int(deadline - time.monotonic()))
                    if remaining != self.ctx.get("confirm_countdown"):
                        self.ctx["confirm_countdown"] = remaining
                        self.dirty = True
                    if remaining <= 0:
                        self.queue.put(("goto", "ACTION_VIEW"))

                # Power confirm countdown
                if self.state == "SCREEN_power" and self.ctx.get("power_confirm"):
                    deadline = self.ctx.get("_power_deadline", 0)
                    remaining = max(0, int(deadline - time.monotonic()))
                    if remaining != self.ctx.get("power_confirm_remaining"):
                        self.ctx["power_confirm_remaining"] = remaining
                        self.dirty = True
                    if remaining <= 0:
                        self.ctx["power_confirm"] = False
                        self.ctx["power_idx"] = 0
                        self.dirty = True

            except Exception:
                traceback.print_exc()

    # ── MAIN LOOP ─────────────────────────────────────────────

    def _splash_wait_for_api(self):
        """Show boot splash, poll API until ready or timeout (30s)."""
        print("[nekopi-lcd] Splash — waiting for API...", flush=True)
        self.lcd.show_image(screens.splash.render(variant='api_wait'))

        start = time.time()
        api_ready = False
        last_check = 0

        while time.time() - start < 30.0:
            now = time.time()
            # Check API every 1s
            if now - last_check >= 1.0:
                last_check = now
                try:
                    resp = get("/api/about")
                    if resp and isinstance(resp, dict) and "nekopi" in resp:
                        api_ready = True
                        self.ctx["about"] = resp
                        break
                except Exception:
                    pass
                self.lcd.show_image(screens.splash.render(variant='api_wait'))

            # Drain input queue (discard during splash)
            try:
                self.queue.get_nowait()
            except Empty:
                pass
            time.sleep(0.1)

        if api_ready:
            print("[nekopi-lcd] API ready — showing ready splash", flush=True)
            self.lcd.show_image(screens.splash.render(ctx=self.ctx, variant='ready'))
            time.sleep(1.5)
            # Fetch full data before entering HOME
            self._fetch_data_sync()
        else:
            print("[nekopi-lcd] API timeout — entering HOME without data", flush=True)
            self.ctx["api_offline"] = True

    def run(self):
        print("[nekopi-lcd] Starting...", flush=True)

        # Splash boot — wait for API with visual feedback
        self._splash_wait_for_api()

        # Switch to HOME
        self._goto("HOME")
        self._render()
        print("[nekopi-lcd] Ready — Home screen", flush=True)

        # Start background workers
        threading.Thread(target=self._status_polling_worker, daemon=True).start()
        threading.Thread(target=self._auto_refresh_worker, daemon=True).start()
        threading.Thread(target=self._timer_worker, daemon=True).start()
        threading.Thread(target=self._home_data_worker, daemon=True).start()

        # Main event loop
        try:
            while self._running:
                try:
                    msg = self.queue.get(timeout=0.1)
                    self._process_message(msg)
                except Empty:
                    pass

                if self.dirty:
                    self._render()
                    self.dirty = False
        except KeyboardInterrupt:
            print("\n[nekopi-lcd] Shutting down...", flush=True)

        self._running = False
        self.input.close()
        self.lcd.clear()
        self.lcd.backlight(False)
        lgpio.gpiochip_close(self._gpio)


if __name__ == "__main__":
    App().run()
