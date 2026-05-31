# listeners/ — despacho automatico de prompts (opcional)

Patron opcional para que el orquestador no le pida al PO copiar/pegar prompts a
mano. Un listener por code vigila `prompts/active/<code>/` y, al detectar un
archivo nuevo, ejecuta el ejecutor en modo headless contra ese prompt.

## Concepto

1. El orquestador escribe `prompts/active/<code>/<archivo>.md` y comitea.
2. `inotifywait` (Linux) detecta el `create` y dispara `claude -p` en el repo del ejecutor con el contenido del prompt.
3. El ejecutor corre y deja su salida en `inbox/<code>/<archivo>_response.md`.
4. El orquestador la procesa en la siguiente sesion (o cuando el PO avisa).

## Requisitos

- Linux con `inotify-tools` (`inotifywait`). En macOS usa `fswatch`; en otros, un poller.
- El CLI del ejecutor instalado y autenticado en cada repo destino.
- Rutas de cada code configuradas en `start-all.sh`.

## Uso

    bash orchestrator/listeners/start-all.sh

Verifica que esten corriendo:

    ps aux | grep inotifywait | grep -v grep

## Alternativa sin infra

Si no quieres listeners, el flujo funciona igual de forma manual: el orquestador
escribe el prompt, tu lo corres en el code ejecutor, el ejecutor escribe la
respuesta en `inbox/`. Los listeners solo eliminan el paso manual.
