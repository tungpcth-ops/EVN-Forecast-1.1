import json
from pathlib import Path
from datetime import datetime

DEFAULT_STATE = {
    "version": "1.4.1",
    "updated_at": None,
    "latest_month": None,
    "model_weights": {},
    "backtest": [],
    "forecast_history": [],
    "actual_history": [],
    "events": [],
    "outage_history": [],
    "notes": "",
    "pcth_mode": {},
}


def load_state(path="model_state.json"):
    p = Path(path)
    if not p.exists():
        return DEFAULT_STATE.copy()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        out = DEFAULT_STATE.copy()
        out.update(data)
        for k in ["forecast_history", "actual_history", "events", "outage_history"]:
            if not isinstance(out.get(k), list):
                out[k] = []
        return out
    except Exception:
        return DEFAULT_STATE.copy()


def save_state(state, path="model_state.json"):
    state = dict(state)
    state["version"] = "1.4.1"
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    Path(path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def state_to_bytes(state):
    return json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")


def merge_uploaded_state(raw_bytes):
    data = json.loads(raw_bytes.decode("utf-8"))
    out = DEFAULT_STATE.copy()
    out.update(data)
    for k in ["forecast_history", "actual_history", "events", "outage_history"]:
        if not isinstance(out.get(k), list):
            out[k] = []
    return out
