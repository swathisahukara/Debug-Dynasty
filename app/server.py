"""Package Trail UI server (stdlib only). Run:  python3 -m app.server   then open http://127.0.0.1:8765
Binds to localhost. Uses the same agents/ code as the CLI and eval; nothing here hardcodes an answer."""
import csv, json, os, queue, sys, threading, time, traceback
from datetime import datetime, timezone
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
PUBLIC = os.environ.get("PUBLIC_MODE", "0") == "1"  # hosted demo: read-only, replay only (no LLM calls, no edits, no source switching)


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
    return dict(mode=dict(public=PUBLIC, sample=C.SAMPLE_MODE, llm_mock=C.LLM_MOCK, data_source=C.DATA_SOURCE, model=os.environ.get("NEMOTRON_MODEL", "")),
                cases=cs, recorded=recorded_summary(), scoreboard=jload(RES / "scoreboard.json"), replay=jload(RES / "replay_scoreboard.json"), graph=CompiledGraph().to_json())


RECORDED = ROOT / "data/public/recorded"
REC_SPEED = float(os.environ.get("RECORDED_SPEED", "0.25"))  # playback runs faster than the original run (at most 5 s per step)


def recordings():
    out = []
    for f in (sorted(RECORDED.glob("*.json")) if RECORDED.exists() else []):
        try: out.append(json.loads(f.read_text()))
        except ValueError: pass
    return out


def find_recording(pkg, as_of):
    key = as_of.isoformat(timespec="minutes")
    return next((r for r in recordings() if r["package"] == pkg and r["as_of"] == key), None)


def recorded_summary():
    return [dict(package=r["package"], as_of=r["as_of"], recorded_at=r["recorded_at"], wall_s=r["wall_s"], calls=r["calls"], source=r["source"]) for r in recordings()]


def play_recording(rec, emit):
    emit("step", role="recorded", text=f"Replaying a recorded run: real {rec['model'] or 'Nemotron'} calls through Meterless Nightshift, data from {rec['source']}, recorded {rec['recorded_at'][:10]}, original run {rec['wall_s']} s. Nothing is called live on this public site.", hits=[])
    prev = 0.0
    for ev in rec["events"]:
        time.sleep(min(max(ev["t"] - prev, 0) * REC_SPEED, 5)); prev = ev["t"]
        kw = dict(ev["data"])
        if ev["type"] == "result": kw["recorded"] = dict(at=rec["recorded_at"], wall_s=rec["wall_s"], source=rec["source"], model=rec["model"])
        emit(ev["type"], **kw)


def record(pkg, as_of, source):
    """Run the real agent loop once (local machine only) and store its event stream so the public site can replay it."""
    events, t0 = [], time.time()
    def emit(type_, **kw): events.append(dict(t=round(time.time() - t0, 2), type=type_, data=json.loads(json.dumps(kw, default=str))))
    old = C.DATA_SOURCE; C.DATA_SOURCE = source
    try: agent(pkg, as_of, emit)
    finally: C.DATA_SOURCE = old
    res = next((e["data"] for e in events if e["type"] == "result"), None)
    errs = [e["data"].get("text") for e in events if e["type"] == "error"]
    if errs or not res: raise RuntimeError("run failed: " + str(errs[:1]))
    if res.get("path") != "llm": raise RuntimeError("no indicator fired at this cutoff, nothing to record")
    key = as_of.isoformat(timespec="minutes")
    rec = dict(package=pkg, as_of=key, recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), source=source, model=os.environ.get("NEMOTRON_MODEL", ""),
               wall_s=res.get("wall_s"), calls=(res.get("meter") or {}).get("calls"), events=events)
    text = json.dumps(rec, indent=1)
    for secret in (os.environ.get("METERLESS_RUNTIME_TOKEN"), os.environ.get("ZETARIS_API_KEY")):
        if secret and secret in text: raise RuntimeError("refusing to save: a secret appears in the trace")
    RECORDED.mkdir(parents=True, exist_ok=True)
    path = RECORDED / f"{pkg}_{key.replace('-', '').replace(':', '')}.json"
    path.write_text(text)
    return dict(saved=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), events=len(events), wall_s=rec["wall_s"], calls=rec["calls"], source=source)


def timeline(pkg, as_of, hits, rel):
    shown = rel[-45:]
    hv = {h["version"]: h["indicator"] for h in hits}
    return [dict(version=r["version"], t=r["t"].isoformat(timespec="minutes"), publisher=r.get("publisher") or "", scripts=r.get("install_scripts") or "",
                 source=r.get("source", ""), hit=hv.get(r["version"])) for r in shown]


RATE = {}


def rate_ok(ip, limit=12, window=60):
    """Small in-memory limiter for live registry checks (protects the registry and the host)."""
    now = time.time(); q = [t for t in RATE.get(ip, []) if now - t < window]
    if len(q) >= limit: RATE[ip] = q; return False
    RATE[ip] = q + [now]
    if len(RATE) > 2000: RATE.clear()
    return True


def path_msg(r, live=False):
    return {"no_indicator": "No indicator fired: low risk, no rule needed, 0 LLM calls",
            "rule": f"Matched compiled rule \"{r.get('rule')}\": 0 LLM calls",
            "unseen_flagged_for_review": f"Unseen indicator combination \"{r.get('rule')}\": flagged for review" + (" (live checks never call the agent)" if live else " (tick compile-on-miss to run the agent once and learn a rule)"),
            "compiled_on_miss": f"Unseen combination \"{r.get('rule')}\": agent loop ran once and compiled a new rule"}[r["path"]]


def live_check(pkg, as_of, emit):
    """Any npm package, straight from registry.npmjs.org, through the same indicators and compiled graph. No LLM."""
    from agents import live
    emit("step", role="retriever", text=f"Fetching {pkg} from registry.npmjs.org (live)")
    try: rel, dep, ages, as_of, meta = live.load(pkg, as_of)
    except live.LiveError as e: return emit("error", text=str(e))
    hits = indicators.recent(indicators.compute(rel, dep, dep_ages=ages), rel, as_of, C.RECENT_DAYS)
    emit("timeline", rows=timeline(pkg, as_of, hits, rel), as_of=as_of.isoformat(timespec="minutes"))
    emit("step", role="indicators", text=f"{meta['versions_used']} releases up to the cutoff ({meta['versions_on_registry']} on the registry), {len(hits)} indicator hit(s) in the last {C.RECENT_DAYS} days",
         hits=[dict(indicator=h["indicator"], version=h["version"], detail=h["detail"], facts=h.get("facts")) for h in hits])
    if ages: emit("step", role="dep ages", text=f"Looked up first-publish dates for {len(ages)} newly added dependencies")
    r = CompiledGraph().replay_rows(pkg, rel, dep, as_of, dep_ages=ages)
    emit("step", role="graph", text=path_msg(r, live=True))
    emit("result", mode="replay", live=True, risk=r["risk"], path=r["path"], rule=r.get("rule"), summary=r.get("rationale") or path_msg(r, True), cited=r["cited"],
         meter=dict(calls=0, est_usd=0.0, tokens_in=0, tokens_out=0), hits=len(hits), meta=meta,
         note="Live registry data. Versions the registry removed keep only their publish time, so content-based indicators (install scripts, dependencies) cannot fire on them.")


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
    msg = path_msg(r)
    emit("step", role="graph", text=msg)
    emit("result", mode="replay", risk=r["risk"], path=r["path"], rule=r.get("rule"), summary=r.get("rationale") or msg, cited=r["cited"],
         meter=dict(calls=r["llm_calls"], est_usd=r["est_usd"], tokens_in=0, tokens_out=0), hits=len(hits))


_FLEET = {"key": None, "val": None}
_FLEET_LOCK = threading.Lock()


PRECOMPUTED = ROOT / "data/public/fleet.json"


def _graph_sha():
    import hashlib
    from agents.compiled import GRAPH_PATH
    return hashlib.sha256(GRAPH_PATH.read_bytes()).hexdigest()


def fleet():
    """Replay the compiled graph over every package x date cell (local CSV only, never Zetaris), cached until the graph file changes."""
    from agents.compiled import GRAPH_PATH
    key = GRAPH_PATH.stat().st_mtime if GRAPH_PATH.exists() else 0
    with _FLEET_LOCK:
        if _FLEET["key"] == key and _FLEET["val"]: return _FLEET["val"]
        if PUBLIC and PRECOMPUTED.exists():  # slow shared CPU on the free host: serve the grid computed by this same graph, verified by hash
            try:
                pre = json.loads(PRECOMPUTED.read_text())
                if pre.get("graph_sha") == _graph_sha():
                    pre["precomputed"] = True; _FLEET.update(key=key, val=pre); return pre
            except (OSError, ValueError): pass
        t0 = time.time(); g = CompiledGraph(); cs = case_list()
        inc = {}
        for c in cs:
            if c["positive"]: inc.setdefault(c["package"], []).append(c["as_of"])
        pkgs = sorted({c["package"] for c in cs}, key=lambda p: (p not in inc, p))
        months = [datetime(y, m, 1) for y in range(2018, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
        dates = sorted(set(months) | {datetime.fromisoformat(c["as_of"]) for c in cs})
        iso = [d.isoformat(timespec="minutes") for d in dates]
        cells, flagged, incidents, counts = [], {}, {}, dict(cells=0, flagged=0, control_cells=0, control_flagged=0)
        for pi, p in enumerate(pkgs):
            row = []
            for di, d in enumerate(dates):
                rel, dep = data.fetch(p, d, source="csv")
                if len(rel) < 5: row.append("0"); continue
                r = g.replay_rows(p, rel, dep, d)
                code = "1" if r["path"] == "no_indicator" else "3" if r["path"] == "unseen_flagged_for_review" else "2"
                row.append(code); counts["cells"] += 1; counts["flagged"] += code != "1"
                if p not in inc: counts["control_cells"] += 1; counts["control_flagged"] += code != "1"
                if code != "1": flagged[f"{pi},{di}"] = dict(risk=r["risk"], rule=r.get("rule"))
            cells.append("".join(row))
            if p in inc: incidents[pi] = [iso.index(a) for a in inc[p] if a in iso]
        val = dict(packages=[dict(name=p, incident=p in inc) for p in pkgs], dates=iso, cells=cells, flagged=flagged, incidents=incidents,
                   stats=dict(counts, seconds=round(time.time() - t0, 2), llm_calls=0, rules=len(g.rules)))
        val["graph_sha"] = _graph_sha()
        _FLEET.update(key=key, val=val)
        return val


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
        if self.path == "/api/fleet":
            try: return self.send(200, fleet())
            except Exception as e: traceback.print_exc(); return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try: b = self.body()
        except ValueError: return self.send(400, {"error": "bad json"})
        if self.path == "/api/record":
            local = self.client_address[0] in ("127.0.0.1", "::1") and not any(self.headers.get(h) for h in ("X-Forwarded-For", "CF-Connecting-IP", "Cf-Ray"))
            if PUBLIC or not local: return self.send(403, {"error": "recording is only allowed from the local machine"})
            try: pkg, as_of = str(b.get("package", "")).strip(), datetime.fromisoformat(b["as_of"])
            except (KeyError, ValueError): return self.send(400, {"error": "package and as_of are required"})
            if not data.PKG_RE.match(pkg) or b.get("source", "zetaris") not in ("csv", "zetaris"): return self.send(400, {"error": "bad package or source"})
            try: return self.send(200, record(pkg, as_of, b.get("source", "zetaris")))
            except Exception as e: traceback.print_exc(); return self.send(500, {"error": f"{type(e).__name__}: {e}"})
        if PUBLIC and self.path in ("/api/source", "/api/rule"): return self.send(403, {"error": "read-only public demo"})
        if PUBLIC and b.get("learn"): return self.send(403, {"error": "the public demo is replay only; live agent runs happen locally"})
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
        live_mode = bool(b.get("live"))
        try: as_of = datetime.fromisoformat(b["as_of"]) if b.get("as_of") else (None if live_mode else datetime(2100, 1, 1))
        except ValueError: return self.send(400, {"error": "bad as_of"})
        rec = None
        if PUBLIC and b.get("mode") == "agent" and not live_mode:
            rec = find_recording(pkg, as_of)
            if not rec:
                have = ", ".join(f"{r['package']} {r['as_of'][:10]}" for r in recordings())
                return self.send(403, {"error": "The public demo replays recorded agent runs only" + (f" ({have}). Pick one of those red-dot known cases." if have else ". Live agent runs happen locally.")})
        if live_mode and not rate_ok((self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()):
            return self.send(429, {"error": "too many live checks, wait a minute"})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store"); self.end_headers()
        def emit(type_, **kw):
            self.wfile.write(("data: " + json.dumps(dict(type=type_, **kw), default=str) + "\n\n").encode()); self.wfile.flush()
        try:
            if live_mode: return live_check(pkg, as_of, emit)
            if rec: return play_recording(rec, emit)
            if not data._csv_by_pkg("releases").get(pkg) and C.DATA_SOURCE == "csv": return emit("error", text=f"{pkg} is not in the local dataset (39 packages). Tick \"live from the npm registry\" to check any package.")
            replay(pkg, as_of, bool(b.get("learn")), emit) if b.get("mode") != "agent" else agent(pkg, as_of, emit)
        except (BrokenPipeError, ConnectionResetError): pass
        except Exception as e:
            traceback.print_exc()
            try: emit("error", text=f"{type(e).__name__}: {e}")
            except OSError: pass


if __name__ == "__main__":
    if "--build-fleet" in sys.argv:  # DATA_DIR=data/public python3 -m app.server --build-fleet
        v = fleet(); PRECOMPUTED.write_text(json.dumps(v, separators=(",", ":")))
        print(f"wrote {PRECOMPUTED} ({v['stats']['cells']} cells in {v['stats']['seconds']} s, {v['stats']['llm_calls']} LLM calls)"); sys.exit(0)
    port = int(os.environ.get("PORT", "8765"))
    print(f"Package Trail UI on port {port}{' (PUBLIC read-only)' if PUBLIC else ''}  (data source: {C.DATA_SOURCE}, SAMPLE_MODE={int(C.SAMPLE_MODE)}, LLM_MOCK={int(C.LLM_MOCK)})")
    host = os.environ.get("HOST", "127.0.0.1")  # 0.0.0.0 on a host that sets PORT (Render, Fly)
    threading.Thread(target=lambda: fleet(), daemon=True).start()  # warm the heatmap cache
    ThreadingHTTPServer((host, port), H).serve_forever()
