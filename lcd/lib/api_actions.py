"""Execute actions from the registry against the NekoPi API."""

from lib import api
from lib.actions import ACTIONS
from lib.util import iperf_client_params


def execute(action_id, op="run", ctx=None):
    """
    Execute an action.
    op: 'start' | 'stop' | 'run' (oneshot)
    Returns: {'ok': bool, 'data': dict|None, 'error': str|None}
    """
    action = ACTIONS.get(action_id)
    if not action:
        return {"ok": False, "error": f"Unknown action: {action_id}"}

    t = action.get("type")
    try:
        if t == "toggle":
            return _exec_toggle(action, op)
        if t == "oneshot":
            return _exec_oneshot(action_id, action)
        return {"ok": False, "error": f"Cannot execute type: {t}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def fetch_status(action_id):
    """Fetch status for a single action. Returns dict or None."""
    action = ACTIONS.get(action_id, {})
    status_spec = action.get("status")
    if not status_spec:
        return None
    return api.get(status_spec["url"])


def _exec_toggle(action, op):
    if op == "start":
        spec = action["start"]
    elif op == "stop":
        spec = action["stop"]
    else:
        return {"ok": False, "error": f"Invalid op: {op}"}

    if spec["method"].upper() == "POST":
        result = api.post(spec["url"])
    else:
        result = api.get(spec["url"])

    if result is None:
        return {"ok": False, "error": "API call failed"}
    return {"ok": True, "data": result}


def _exec_oneshot(action_id, action):
    method = action["method"].upper()
    url = action["url"]

    if action.get("params_dynamic") == "iperf_client_params":
        params = iperf_client_params()
    else:
        params = action.get("params", {})

    if method == "POST":
        result = api.post(url, body=params if params else None)
    else:
        result = api.get(url, params=params if params else None)

    if result is None:
        return {"ok": False, "error": "API call failed"}
    return {"ok": True, "data": result}
