# LCD HAT — Pendientes v1.4

Tracking de mejoras pendientes para el LCD HAT después del baseline v1.3.0.

## Pendientes funcionales

- [ ] DHCP Test: agregar selector de cantidad (UP/DOWN para ajustar requests antes de ejecutar, default 50) + result_fields visibles
- [ ] iPerf Server: filtrar interfaces mostradas (solo eth0/eth1 relevantes, no todas)
- [ ] Captive Test: mostrar resultado en pantalla (hoy solo muestra OK/FAIL sin detalle)
- [ ] Quick Check: mostrar resultados parciales mientras corre (progressive rendering)
- [ ] WiFi Scan: mostrar APs encontrados con RSSI en lista scrollable
- [ ] iPerf Client: reactivar en SUBMENUS["tools"] en v1.4 con selector de target (gateway/mgmt/last client/custom). Entry preserved in ACTIONS dict.
- [ ] DNS Benchmark real: el item actual "DNS" solo mide lookup time contra UN servidor. Hacer benchmark comparativo:
  - Probar resolución contra: DNS sistema, 8.8.8.8, 1.1.1.1, 9.9.9.9, 208.67.222.222
  - Para cada uno: tiempo de respuesta + tasa de éxito en N intentos
  - Mostrar ranking en pantalla con dots de color (verde el mejor, amber medios, rojo el peor)
  - Endpoint nuevo /api/qc/dns/benchmark o ampliar /api/qc/dns con param ?compare=true
- [ ] Pantalla About con logo NekoPi + versión SW + hardware specs
- [ ] Profiler /api/profiler/status enriquecido: devolver clients_count, ssid, bssid, top_rssi para mostrar datos en vivo en LCD

## Refinamiento visual (nice-to-have)

- [ ] Evaluar DejaVu Sans Mono para datos numéricos (IPs, latencias) — mejor alineación en columnas
- [ ] Validar contraste FG_DIM vs FG en pantallas con mucho texto
- [ ] Revisar márgenes verticales en listas densas

## Bugs conocidos del backend (no del LCD)

- [ ] wlan1 (Broadcom BCM43455 onboard del RPi5) está UP a pesar de `dtoverlay=disable-wifi` en config.txt. Solución: blacklist módulo brcmfmac en /etc/modprobe.d/
- [ ] CLAUDE.md tiene info incorrecta sobre wlan0: dice "MT7925 WiFi7 HAT" pero es Intel AX210 WiFi 6E
- [ ] dnsmasq.service failed en eth1 mgmt — investigar en sesión separada
