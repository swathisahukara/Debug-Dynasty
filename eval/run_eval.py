"""Scoreboard: rules-only vs single-shot LLM vs full agent loop on incident cases and matched clean controls.
Resumable (eval/results/cache.jsonl). Usage: python3 -m eval.run_eval [--workers 2] [--limit N] [--systems rules,single,agent]"""
import argparse, csv, json, collections, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from agents import config as C, data, pipeline, baseline, llm

PRECURSORS = {("event-stream", "3.3.5")}  # new-publisher takeover step that precedes the malicious release
RES = C.ROOT / "eval/results"; RES.mkdir(parents=True, exist_ok=True)
CACHE = RES / "cache.jsonl"; lock = threading.Lock()


def cases():
    key = list(csv.DictReader((C.ROOT / "eval/answer_key.csv").open()))
    rel = list(csv.DictReader((C.DATA_DIR / "releases.csv").open()))
    when = {(r["package"], r["version"]): data._ts(r["published_at"]) for r in rel}
    groups = collections.defaultdict(list)
    for k in key: groups[(k["incident"], k["package"])].append(k)
    inc = []
    for (name, p), ks in groups.items():
        if not all((k["package"], k["version"]) in when for k in ks): continue  # incident not fully present (the small SAMPLE_MODE dataset)
        inc.append(dict(id=f"inc:{p}:{name[:20]}", package=p, positive=True, as_of=min(when[(k["package"], k["version"])] for k in ks) + timedelta(hours=1),
                                              truth={(k["package"], k["version"]) for k in ks} | {x for x in PRECURSORS if x[0] == p}))
    inc.sort(key=lambda c: c["as_of"])
    controls = sorted({r["package"] for r in rel if r["role"] == "control"})
    out = list(inc)
    for i, p in enumerate(controls):
        n = [when[(r["package"], r["version"])] for r in rel if r["package"] == p]
        as_of = max(n)  # no incident cutoff available (SAMPLE_MODE): evaluate at the latest release
        for j in range(len(inc)):
            as_of = inc[(i + j) % len(inc)]["as_of"]
            if sum(t <= as_of for t in n) >= 5: break
        out.append(dict(id=f"ctl:{p}", package=p, positive=False, as_of=as_of, truth=set()))
    return out


def load_cache():
    d = {}
    if CACHE.exists():
        for l in CACHE.read_text().splitlines():
            r = json.loads(l); d[(r["case"], r["system"])] = r
    return d


def run_case(c, system):
    if system == "rules":
        rel, dep = data.fetch(c["package"], c["as_of"]); from agents import indicators
        h = indicators.recent(indicators.compute(rel, dep), rel, c["as_of"], C.RECENT_DAYS)
        return dict(risk_level="medium" if h else "low", indicators=[], row_versions={}, meter=dict(calls=0, tokens_in=0, tokens_out=0, seconds=0, est_usd=0))
    r = baseline.investigate(c["package"], c["as_of"]) if system == "single" else pipeline.investigate(c["package"], c["as_of"])
    r.pop("hits", None); return r


def score(rows):
    s = {}
    for system in ("rules", "single", "agent", "agent_mem"):
        rs = [r for r in rows if r["system"] == system]
        if not rs: continue
        pos, neg = [r for r in rs if r["positive"]], [r for r in rs if not r["positive"]]
        flagged = lambda r: r["risk_level"] in ("medium", "high")
        cited = supp = 0
        for r in pos:
            for ind in r.get("indicators", []):
                vs = {(r["package"], r["row_versions"].get(x)) for x in ind.get("rows", [])}
                cited += 1; supp += bool(vs & r["truth"])
        s[system] = dict(detection=f"{sum(map(flagged, pos))}/{len(pos)}", false_alarm=f"{sum(map(flagged, neg))}/{len(neg)}",
                         evidence_precision=(f"{supp}/{cited}" if cited else "n/a"),
                         llm_calls_per_case=round(sum(r["meter"]["calls"] for r in rs) / len(rs), 2),
                         est_usd_per_case=round(sum(r["meter"]["est_usd"] for r in rs) / len(rs), 5),
                         seconds_per_case=round(sum(r["meter"].get("seconds", 0) for r in rs) / len(rs), 1))
    return s


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=2); ap.add_argument("--limit", type=int)
    ap.add_argument("--systems", default="rules,single,agent"); ap.add_argument("--only")
    a = ap.parse_args(); cs = cases()
    if a.only: cs = [c for c in cs if a.only in c["id"]]
    if a.limit: cs = [c for c in cs if c["positive"]][:a.limit // 2 + 1] + [c for c in cs if not c["positive"]][:a.limit // 2]
    cache = load_cache(); jobs = [(c, s) for c in cs for s in a.systems.split(",") if (c["id"], s) not in cache]
    print(f"{len(cs)} cases, {len(jobs)} runs to do ({len(cache)} cached)", flush=True)

    def work(job):
        c, s = job
        try: r = run_case(c, s)
        except Exception as e: r = dict(risk_level="unknown", indicators=[], row_versions={}, error=str(e)[:200], meter=dict(calls=0, tokens_in=0, tokens_out=0, seconds=0, est_usd=0))
        r.update(case=c["id"], system=s, package=c["package"], positive=c["positive"], as_of=str(c["as_of"]))
        r["truth_list"] = sorted(map(list, c["truth"]))
        with lock:
            CACHE.open("a").write(json.dumps(r, default=str) + "\n"); print(f"  done {c['id']:28} {s:7} -> {r['risk_level']}", flush=True)
    # LLM systems go through the model; rules are instant
    with ThreadPoolExecutor(a.workers) as ex: list(ex.map(work, jobs))
    cache = load_cache(); ids = {c["id"] for c in cs}
    rows = [dict(r, truth={tuple(x) for x in r["truth_list"]}) for (cid, _), r in cache.items() if cid in ids]
    sc = score(rows); (RES / "scoreboard.json").write_text(json.dumps(sc, indent=1))
    print(json.dumps(sc, indent=1))


if __name__ == "__main__": main()
