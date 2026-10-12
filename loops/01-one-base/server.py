"""One base — Palimpsest loop 01.

Serves the page and scores DNA with Evo 2 7B. For every position it returns
the log-probability Evo 2 gave the base that is actually there, given every
base before it, plus its probabilities for A, C, G and T at that position.

Run with the evo2 conda env's Python:
    /home/meow/miniconda3/envs/evo2/bin/python loops/01-one-base/server.py
"""
import collections
import csv
import hashlib
import importlib.util
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent.parent / "data" / "loops" / "01-one-base" / "runs.jsonl"
PORT = int(os.environ.get("ONE_BASE_PORT", "8770"))
# 2,500 bp peaked at 14.65 GB on 15 Sep; 3,000 bp failed. Keep headroom.
MAX_LEN = 2000
BASES = "ACGT"

STATE = {"state": "loading", "msg": "Evo 2 is loading onto the GPU…", "model": None}
GPU = threading.Lock()
CACHE = collections.OrderedDict()   # sha256(seq) -> (lp, p4); repeats return instantly
CACHE_MAX = 96
EVENTS = RUNS.parent / "events.jsonl"


def prompts_csv() -> Path:
    spec = importlib.util.find_spec("evo2")
    return Path(spec.origin).parent / "test" / "data" / "prompts.csv"


def ecolac() -> str:
    with open(prompts_csv()) as f:
        row = next(r for r in csv.DictReader(f) if r["Name"] == "ECOLAC")
    return row["Sequence"].upper()


def load_model():
    try:
        from evo2 import Evo2

        t = time.time()
        STATE["model"] = Evo2("evo2_7b")
        STATE.update(state="ready", msg=f"Evo 2 7B ready · loaded in {time.time() - t:.0f} s")
    except Exception as e:  # shown on the page, not swallowed
        STATE.update(state="error", msg=f"Evo 2 failed to load: {type(e).__name__}: {e}")


def score(seq: str):
    import torch

    m = STATE["model"]
    ids = torch.tensor(m.tokenizer.tokenize(seq), dtype=torch.long).unsqueeze(0).to("cuda:0")
    acgt = torch.tensor([ord(c) for c in BASES], device=ids.device)
    with GPU, torch.inference_mode():
        out, _ = m(ids)
        logp = torch.log_softmax(out[0][0].float(), dim=-1)  # (len, vocab), full vocabulary
        # Row i predicts position i+1 from positions 0..i.
        lp = logp[:-1].gather(1, ids[0, 1:].unsqueeze(1)).squeeze(1)
        p4 = logp[:-1][:, acgt].exp()  # not renormalised; the rest of the vocab keeps its share
    lp = [None] + [round(v, 5) for v in lp.cpu().tolist()]
    p4 = [None] + [[round(v, 5) for v in row] for row in p4.cpu().tolist()]
    return lp, p4


def receipt(label: str, seq: str, ms: int, lp):
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    vals = [v for v in lp if v is not None]
    rec = {
        "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label[:200],
        "n": len(seq),
        "sha256": hashlib.sha256(seq.encode()).hexdigest(),
        "ms": ms,
        "mean_logprob": round(sum(vals) / len(vals), 5) if vals else None,
    }
    with open(RUNS, "a") as f:
        f.write(json.dumps(rec) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path  # ignore ?v=… variant tags
        if path in ("/", "/index.html"):
            self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/status":
            self.send(200, {"state": STATE["state"], "msg": STATE["msg"]})
        elif path == "/seq":
            self.send(200, {"name": "ECOLAC", "source": str(prompts_csv()), "seq": SEQ, "max_len": MAX_LEN})
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except json.JSONDecodeError:
            return self.send(400, {"error": "body is not JSON"})
        if self.path == "/quit":
            self.send(200, {"ok": True})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        if self.path == "/event":
            EVENTS.parent.mkdir(parents=True, exist_ok=True)
            body["server_t"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with open(EVENTS, "a") as f:
                f.write(json.dumps(body)[:2000] + "\n")
            return self.send(200, {"ok": True})
        if self.path != "/score":
            return self.send(404, {"error": "not found"})
        if STATE["state"] != "ready":
            return self.send(503, {"error": STATE["msg"]})
        seq = str(body.get("seq", "")).upper()
        if not (2 <= len(seq) <= MAX_LEN) or set(seq) - set(BASES):
            return self.send(400, {"error": f"sequence must be 2–{MAX_LEN} bases of A, C, G, T"})
        t = time.time()
        key = hashlib.sha256(seq.encode()).hexdigest()
        try:
            if key in CACHE:
                CACHE.move_to_end(key)
                lp, p4 = CACHE[key]
            else:
                lp, p4 = score(seq)
                CACHE[key] = (lp, p4)
                if len(CACHE) > CACHE_MAX:
                    CACHE.popitem(last=False)
        except Exception as e:
            return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        ms = round((time.time() - t) * 1000)
        receipt(str(body.get("label", "")), seq, ms, lp)
        self.send(200, {"lp": lp, "p4": p4, "ms": ms})


SEQ = ecolac()

if __name__ == "__main__":
    threading.Thread(target=load_model, daemon=True).start()
    print(f"One base: http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
