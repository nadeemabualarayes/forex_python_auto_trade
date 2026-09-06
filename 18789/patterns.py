from flask import Flask, request, make_response
from datetime import datetime, timezone
from collections import Counter
import pandas as pd
import json
import logging
import sys
from typing import Any

app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("pattern_server.log", mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────

def to_float_list(src: Any, key: str) -> list[float]:
    out = []
    if isinstance(src, (list, tuple)):
        for i, v in enumerate(src):
            try: out.append(float(v))
            except: log.warning("Bad %s[%d]=%r", key, i, v)
    return out

def harmonise(ohlc: dict[str, list[float]], size: int) -> dict[str, list[float]]:
    fixed = {k: to_float_list(ohlc.get(k, []), k) for k in ("open","high","low","close")}
    for k, arr in fixed.items():
        if len(arr) >= size:
            fixed[k] = arr[-size:]
        else:
            pad = [arr[0] if arr else 0.0] * (size - len(arr))
            fixed[k] = pad + arr
    return fixed

def parse_times(src: Any, size: int) -> list[datetime]:
    dt = []
    for v in (src if isinstance(src, (list, tuple)) else []):
        try: dt.append(datetime.fromtimestamp(int(v), timezone.utc))
        except: log.warning("Bad timestamp: %r", v)
    if len(dt) >= size:
        return dt[-size:]
    pad = [dt[0] if dt else datetime.now(timezone.utc)] * (size - len(dt))
    return pad + dt

def build_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    times = parse_times(payload.get("time", []), size=len(payload.get("time", [])))
    ohlc = harmonise(payload, size=len(times))
    df = pd.DataFrame(ohlc, index=times)
    df.index.name = "datetime"
    df.rename(columns=str.upper, inplace=True)
    return df

# ─── Pattern Detection ───────────────────────────────────────────

def detect_patterns(df: pd.DataFrame) -> list[str]:
    out = ["None"] * len(df)
    for i in range(len(df)):
        o, h, l, c = df.iloc[i][["OPEN","HIGH","LOW","CLOSE"]]
        body = abs(c - o)
        rng = h - l if h > l else 1e-6
        lower = min(o, c) - l
        upper = h - max(o, c)

        # Doji
        if body / rng <= 0.1:
            out[i] = "doji"; continue
        # Hammer
        if lower >= 2 * body and upper <= body:
            out[i] = "hammer"; continue
        # Shooting Star
        if upper >= 2 * body and lower <= body:
            out[i] = "shootingstar"; continue
        # Engulfing
        if i > 0:
            po, pc = df.iloc[i-1][["OPEN","CLOSE"]]
            if c > o and po > pc and o <= pc and c >= po:
                out[i] = "bullishengulfing"; continue
            if c < o and po < pc and o >= pc and c <= po:
                out[i] = "bearishengulfing"; continue
        # Harami
        if i > 0:
            po, pc = df.iloc[i-1][["OPEN","CLOSE"]]
            if (po > pc and o > c and o < po and c > pc) or (po < pc and o < c and o > po and c < pc):
                out[i] = "harami"; continue
        # Morning Star / Evening Star
        if i > 1:
            o1, c1 = df.iloc[i-2][["OPEN","CLOSE"]]
            o2, c2, h2, l2 = df.iloc[i-1][["OPEN","CLOSE","HIGH","LOW"]]
            midpoint = (o1 + c1) / 2
            if c1 < o1 and abs(c2 - o2) < (h2 - l2) * 0.3 and c > midpoint and c > o2:
                out[i] = "morningstar"; continue
            if c1 > o1 and abs(c2 - o2) < (h2 - l2) * 0.3 and c < midpoint and c < o2:
                out[i] = "eveningstar"; continue
    return out

# ─── Flask Endpoint ──────────────────────────────────────────────

@app.route("/patterns", methods=["POST"])
def patterns():
    start = datetime.now(timezone.utc)
    raw = request.get_data(as_text=True)
    log.info("RAW BODY: %s", raw)

    try:
        idx = raw.rfind("}")
        clean = raw[:idx+1] if idx != -1 else raw
        payload = json.loads(clean)
    except json.JSONDecodeError as e:
        log.error("JSON decode failed: %s", e)
        return make_response(json.dumps({"error": str(e)}), 400, {"Content-Type": "application/json"})

    df = build_dataframe(payload)
    patterns = detect_patterns(df)
    counts = Counter(patterns)
    summary = {k: v for k, v in counts.items() if k != "None" and v > 0}
    log_lines = [f"{k}={v}" for k, v in summary.items()] + [f"total patterns={sum(summary.values())}"]
    ms = round((datetime.now(timezone.utc) - start).total_seconds() * 1000, 2)
    result = {"patterns": patterns, "log": log_lines, "ms": ms}
    log.info("SEND: %s", result)
    return make_response(json.dumps(result), 200, {"Content-Type": "application/json"})

if __name__ == "__main__":
    log.info("Pattern server running on http://127.0.0.1:5000/patterns")
    app.run(threaded=True, port=5000)
