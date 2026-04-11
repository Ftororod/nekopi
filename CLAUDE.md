# NekoPi Field Unit v1.0 — Codenamed "Tomás"

## Plataforma
- Raspberry Pi 5, Ubuntu 24.04 LTS
- eth0 = RTL8125B 2.5GbE HAT (interfaz TEST — conecta a red del cliente)
- eth1 = NIC nativa RPi5 (MGMT estática 192.168.99.1/24, dnsmasq DHCP)
- wlan0 = MT7925 WiFi7 HAT (conectado a red home/oficina)
- wlan1 = CF-953AX MT7921AU USB (modo monitor/profiling)

## Estructura del proyecto
- /opt/nekopi/ui/index.html     — Frontend (HTML/CSS/JS single-file, puerto 8080)
- /opt/nekopi/api/main.py       — Backend (FastAPI + uvicorn, puerto 8000)
- /opt/nekopi/logs/             — Logs del sistema
- /opt/nekopi/data/             — Datos persistentes
- /opt/nekopi/reports/          — Reportes generados
- /opt/nekopi/captures/         — Capturas de red
- Build: build_installer_v2.py
- Bilingual ES/EN en UI

## Módulos FUNCIONALES (no romper)
- Wired/LAN: LLDP/CDP, iPerf3 client/server, VLAN Probe, Port Blinker,
  802.1X detection, VoIP/QoS MOS, DNS Benchmark, DHCP Stress (nmap)
- Roaming Analyzer: tcpdump-based, wlan1 monitor mode, timer funcional
  (prueba con Cisco pendiente, ajustar parser según resultado real)
- Security Audit: 4 fases — nmap discovery → port scan → CVE/service
  detection → reporte score 0-100 + hallazgos críticos/altos/medios
  (pendiente: mejorar falsos positivos dual-band, lista curada de
  credenciales default por fabricante, CVE lookup por servicio)
- Kismet: start/stop, process kill, data retention
- Sidebar traffic panel: polling 2s, formatRate Mbps/Kbps/Gbps,
  cache anti-flicker implementado
- NAT toggle: por defecto ON, iptables MASQUERADE
- IoT: placeholder 🚧 (pendiente definir alcance)

## Endpoints backend existentes
- GET /api/wired/lldp
- GET /api/wired/link
- GET /api/iperf/server/start · /stop · /api/iperf/client
- GET /api/network/dhcp
- GET /api/qc/dns
- GET /api/traffic (polling sidebar, cache anti-flicker)

## Módulos INCOMPLETOS — INTELLIGENCE
- Edge AI: integración con Ollama/llama3 corriendo en la RPi5,
  badge LIVE en menú debe reflejar estado real del servicio,
  se integra en TODOS los módulos que tienen "Analizar con AI"
- Reports: exportar resultados de todos los módulos a PDF,
  incluir score de seguridad, hallazgos, recomendaciones,
  nombre cliente + ingeniero, fecha, logo NekoPi,
  resumen ejecutivo generado con AI
- Terminal: terminal web vía ttyd, badge SSH en menú,
  verificar si funcional o decorativo
- Tools: definir y implementar herramientas de campo adicionales

## Módulos INCOMPLETOS — SYSTEM
- Connection: estado eth0/eth1/wlan0/wlan1, IPs, gateway, DNS,
  latencia — verificar si completo o parcialmente decorativo
- Console: logs en tiempo real del sistema y NekoPi,
  verificar si funcional
- About: info dispositivo, versión SW, hardware specs
- Settings: idioma, modelo AI, config de interfaces,
  auditar qué opciones son reales vs decorativas

## WiFi Troubleshooter — debe ser completamente funcional
- Parámetros a capturar y analizar:
  - RSSI por AP/BSSID, canal, ancho de banda, PHY mode (WiFi4/5/6/7)
  - Noise floor, SNR, retry rate, beacon interval
  - Interferencia de canal (vecinos en mismo canal)
  - Roaming events (802.11r/k/v)
- Integrar análisis AI dual (ver sección AI más abajo)

## Integración Edge AI transversal
- Cada módulo con botón "Analizar con AI" debe conectarse al modelo
- Módulos que deben tener análisis AI:
  - Wired/LAN: interpretar LLDP, iPerf3, 802.1X
  - Security Audit: explicar hallazgos, sugerir remediación
  - Roaming Analyzer: interpretar eventos, recomendar config AP
  - Network Scan: clasificar dispositivos, detectar anomalías
  - WiFi Troubleshooter: diagnóstico por señal y parámetros RF
  - Reports: generar resumen ejecutivo automático
- Botón AI deshabilitado si Ollama no está corriendo, con mensaje claro
- Respuestas en el mismo idioma que la UI (ES/EN)
- Contexto enviado: JSON con resultados del módulo + prompt por módulo

## Estrategia AI dual — Local vs Externa
- Edge AI LOCAL (Ollama/llama3):
  - Datos sensibles: IPs, MACs, SSIDs, topología del cliente
  - Análisis rápido, sin salir de la RPi, funciona sin internet
- AI EXTERNA (Gemini API):
  - Recibe SOLO parámetros técnicos abstractos sin PII ni datos cliente
  - Ejemplos: "señal -72dBm, SNR 18dB, canal 6, retries 23%"
  - Prompts pre-construidos por módulo con placeholders, sin raw data
  - Mayor capacidad de análisis y contexto que llama3
  - Requiere internet (wlan0 o eth0 con salida)
  - Fallback automático a Edge AI si no hay internet
- UI indica claramente cuál AI se está usando en cada respuesta

## Validación y QA — revisión completa del código
- Auditar ui/index.html y api/main.py buscando:
  - Endpoints del frontend que llaman rutas inexistentes en backend
  - Endpoints del backend que nadie llama desde el frontend
  - Botones y acciones decorativas sin lógica real
  - Manejo de errores faltante o incorrecto (try/except vacíos)
  - Race conditions en polling y timers
  - Memory leaks (intervals no limpiados al cambiar módulo)
  - Inconsistencias ES/EN (textos mezclados)
  - Variables y funciones definidas pero nunca usadas
- Corregir bugs sin romper lo que funciona
- Verificar que build_installer_v2.py copia todos los archivos
  y que el systemd service arranca limpio

## Kismet — archivos de captura
- Los .kismet se generan en /opt/nekopi/ (mover a /opt/nekopi/captures/)
- Excluidos del repo vía .gitignore (*.kismet, *.kismet-journal)
- Arrancar solo cuando módulo activo, parar al salir

## Pendiente cuando llegue el hardware
- Cable TDR: ethtool --cable-test en eth0 (RTL8125B confirmado compatible)
  Requiere link DOWN en far end. Muestra faults por par + longitud.
  Agregar en módulo Wired con auto-detect compatibilidad.

## Convenciones y restricciones
- try/except en cada módulo, nunca except vacío
- Procesos nuevos: on-demand únicamente (no daemons permanentes)
- RAM budget: ~2.9GB disponible con AI activo — respetar
- Logs en /var/log/nekopi/
CLAUDEOF
