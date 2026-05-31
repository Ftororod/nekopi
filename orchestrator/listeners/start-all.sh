#!/usr/bin/env bash
# Despacho automatico de prompts — plantilla generica.
# Personaliza CODES con tus ejecutores. Requiere inotify-tools (Linux).
#
# Por cada code: vigila prompts/active/<code>/ y al crearse un .md ejecuta el
# CLI del ejecutor en su repo, dejando la salida en inbox/<code>/.

set -euo pipefail

ORCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${HOME}/.cache/orchestrator-listeners"
mkdir -p "${LOG_DIR}"

# Formato: "<code>:<ruta-del-repo-ejecutor>"
CODES=(
  "code-1:/path/al/repo/del/ejecutor-1"
  # "code-2:/path/al/repo/del/ejecutor-2"
)

dispatch_one() {
  local code="$1" repo="$2" prompt_file="$3"
  local base resp
  base="$(basename "${prompt_file}" .md)"
  resp="${ORCH_ROOT}/orchestrator/inbox/${code}/${base}_response.md"
  mkdir -p "$(dirname "${resp}")"
  echo "$(date -Iseconds) Prompt detectado: ${prompt_file}" >>"${LOG_DIR}/listener-${code}.log"
  echo "$(date -Iseconds) Ejecutando claude -p en ${repo}" >>"${LOG_DIR}/listener-${code}.log"
  # Ajusta el comando del CLI a tu herramienta:
  ( cd "${repo}" && claude -p "$(cat "${prompt_file}")" >"${resp}" 2>>"${LOG_DIR}/listener-${code}.log" ) || \
    echo "$(date -Iseconds) ERROR ejecutando ${prompt_file}" >>"${LOG_DIR}/listener-${code}.log"
}

watch_code() {
  local code="$1" repo="$2"
  local active="${ORCH_ROOT}/orchestrator/prompts/active/${code}"
  mkdir -p "${active}"
  # Re-disparar prompts pendientes ya presentes al arrancar:
  for f in "${active}"/*.md; do
    [ -e "${f}" ] || continue
    dispatch_one "${code}" "${repo}" "${f}"
  done
  # Vigilar nuevos:
  inotifywait -m -e create -e moved_to --format '%w%f' "${active}" | while read -r f; do
    case "${f}" in *.md) dispatch_one "${code}" "${repo}" "${f}" ;; esac
  done
}

for entry in "${CODES[@]}"; do
  code="${entry%%:*}"; repo="${entry#*:}"
  watch_code "${code}" "${repo}" &
  echo "Listener arrancado para ${code} (${repo})"
done

wait
