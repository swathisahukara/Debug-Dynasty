"""Package Trail UI server (stdlib only). Run:  python3 -m app.server   then open http://127.0.0.1:8765
Binds to localhost. Uses the same agents/ code as the CLI and eval; nothing here hardcodes an answer."""
import csv, json, os, queue, sys, threading, traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATA_SOURCE", "csv")  # local CSV by default (same rows Zetaris serves); switch to Zetaris in the UI
from agents import config as C, data, indicators, llm, pipeline  # noqa: E402
from agents.compiled import CompiledGraph  # noqa: E402

RES = ROOT / "eval" / "results"
RUN_LOCK = threading.Lock()  # one agent run at a time (the cost meter is process-global)
RISKS = ("low", "medium", "high")


def jload(p, default=None):
    try: return json.loads(Path(p).read_text())
    except (OSError, ValueError): return default


def case_list():
    from eval.run_eval import cases
    names = {}
    for r in csv.DictReader((ROOT / "eval/answer_key.csv").open()): names[r["package"]] = r["incident"]
    out = []
    for c in cases():
        out.append(dict(id=c["id"], package=c["package"], as_of=c["as_of"].isoformat(timespec="minutes"), positive=c["positive"],
                        label=names.get(c["package"], "") if c["positive"] else "control (no known incident)"))
    return out


def state():
    try: cs = case_list()
    except Exception as e: cs = []; print("cases unavailable:", e)
    return dict(mode=dict(sample=C.SAMPLE_MODE, llm_mock=C.LLM_MOCK, data_source=C.DATA_SOURCE, model=os.environ.get("NEMOTRON_MODEL", "")),
                cases=cs, scoreboard=jload(RES / "scoreboard.json"), replay=jload(RES / "replay_scoreboard.json"), graph=CompiledGraph().to_json())


def timeline(pkg, as_of, hits, rel):
    shown = rel[-45:]
    hv = {h["version"]: h["indicator"] for h in hits}
    return [dict(version=r["version"], t=r["t"].isoformat(timespec="minutes"), publisher=r.get("publisher") or "", scripts=r.get("install_scripts") or "",
                 source=r.get("source", ""), hit=hv.get(r["version"])) for r in shown]


def replay(pkg, as_of, learn, emit):
    emit("step", role="retriever", text=f"Querying {C.DATA_SOURCE} for {pkg} up to the cutoff")
    rel, dep = data.fetch(pkg, as_of)
    hits = indicators.recent(indicators.compute(rel, dep), rel, as_of, C.RECENT_DAYS)
    emit("timeline", rows=timeline(pkg, as_of, hits, rel), as_of=as_of.isoformat(timespec="minutes"))
    emit("step", role="indicators", text=f"{len(rel)} releases, {len(hits)} indicator hit(s) in the last {C.RECENT_DAYS} days",
         hits=[dict(indicator=h["indicator"], version=h["version"], detail=h["detail"], facts=h.get("facts")) for h in hits])
    g = CompiledGraph()
    llm.reset_meter()
    r = g.replay(pkg, as_of, allow_llm=learn)
    if learn and r["path"] == "compiled_on_miss": g.save()
    msg = {"no_indicator": "No indicator fired: low risk, no rule needed, 0 LLM calls",
           "rule": f"Matched compiled rule \"{r.get('rule')}\": 0 LLM calls",
           "unseen_flagged_for_review": f"Unseen indicator combination \"{r.get('rule')}\": flagged for review (tick compile-on-miss to run the agent once and learn a rule)",
           "compiled_on_miss": f"Unseen combination \"{r.get('rule')}\": agent loop ran once and compiled a new rule"}[r["path"]]
    emit("step", role="graph", text=msg)
    emit("result", mode="replay", risk=r["risk"], path=r["path"], rule=r.get("rule"), summary=r.get("rationale") or msg, cited=r["cited"],
         meter=dict(calls=r["llm_calls"], est_usd=r["est_usd"], tokens_in=0, tokens_out=0), hits=len(hits))


def agent(pkg, as_of, emit):
    with RUN_LOCK:
        q = queue.Queue(); box = {}
        def work():
            try: box["res"] = pipeline.investigate(pkg, as_of)
            except Exception as e: box["err"] = f"{type(e).__name__}: {e}"; traceback.print_exc()
            q.put(None)
        listener = lambda ev: q.put(ev)
        pipeline.LISTENERS.append(listener)
        try:
            threading.Thread(target=work, daemon=True).start()
            while (ev := q.get()) is not None:
                if ev["event"] == "retriever":
                    rel, dep = data.fetch(pkg, as_of); hits = indicators.recent(indicators.compute(rel, dep), rel, as_of, C.RECENT_DAYS)
                    emit("timeline", rows=timeline(pkg, as_of, hits, rel), as_of=as_of.isoformat(timespec="minutes"))
                emit("log", rec=ev)
        finally:
            if listener in pipeline.LISTENERS: pipeline.LISTENERS.remove(listener)
        if "err" in box: emit("error", text=box["err"]); return
        res = box["res"]; res.pop("_mem_res", None)
        hits = res.pop("hits", [])
        emit("result", mode="agent", risk=res.get("risk_level"), path=res.get("path"), summary=res.get("summary"), indicators=res.get("indicators", []),
             retries=res.get("retries", 0), kept=res.get("kept_by_skeptic"), meter=res.get("meter"), wall_s=res.get("wall_s"),
             cited=[dict(indicator=h["indicator"], row=f"{pkg}@{h['version']}") for h in hits], row_versions=res.get("row_versions", {}), hits=len(hits))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, default=str)).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"): return self.send(200, (ROOT / "app" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/state": return self.send(200, state())
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try: b = self.body()
        except ValueError: return self.send(400, {"error": "bad json"})
        if self.path == "/api/source":
            if b.get("source") not in ("csv", "zetaris"): return self.send(400, {"error": "source must be csv or zetaris"})
            C.DATA_SOURCE = b["source"]; return self.send(200, {"data_source": C.DATA_SOURCE})
        if self.path == "/api/rule":
            g = CompiledGraph()
            if b.get("when") not in g.rules or b.get("risk") not in RISKS: return self.send(400, {"error": "unknown rule or risk"})
            g.rules[b["when"]]["risk"] = b["risk"]; g.rules[b["when"]]["source"] = "edited in UI"; g.save()
            return self.send(200, g.to_json())
        if self.path != "/api/investigate": return self.send(404, {"error": "not found"})
        pkg = str(b.get("package", "")).strip()
        if not data.PKG_RE.match(pkg): return self.send(400, {"error": "bad package name"})
        try: as_of = datetime.fromisoformat(b["as_of"]) if b.get("as_of") else datetime(2100, 1, 1)
        except ValueError: return self.send(400, {"error": "bad as_of"})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store"); self.end_headers()
        def emit(type_, **kw):
            self.wfile.write(("data: " + json.dumps(dict(type=type_, **kw), default=str) + "\n\n").encode()); self.wfile.flush()
        try:
            if not data._csv_by_pkg("releases").get(pkg) and C.DATA_SOURCE == "csv": return emit("error", text=f"{pkg} is not in the local dataset (39 packages). Try one from the list.")
            replay(pkg, as_of, bool(b.get("learn")), emit) if b.get("mode") != "agent" else agent(pkg, as_of, emit)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as e:
            traceback.print_exc()
            try: emit("error", text=f"{type(e).__name__}: {e}")
            except OSError: pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    print(f"Package Trail UI on http://127.0.0.1:{port}  (data source: {C.DATA_SOURCE}, SAMPLE_MODE={int(C.SAMPLE_MODE)}, LLM_MOCK={int(C.LLM_MOCK)})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
