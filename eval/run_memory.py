"""agent+memory: replay the 40 cases in chronological order with Meterless H-MEM. Memory starts empty; after each case is
resolved (answer key) its abstract indicator pattern and outcome are stored, so a case can only recall EARLIER cases.
Controls are ordered before incidents that share a cutoff. Resumable: cached cases are re-learned without LLM calls.
Usage: python3 -m eval.run_memory   (needs Nightshift for uncached cases)"""
import os
os.environ.setdefault("DATA_SOURCE", "csv")  # same rows Zetaris serves; set DATA_SOURCE=zetaris to query live
import json
from agents import config as C, data, indicators, pipeline
from agents.memory import IncidentMemory
from eval.run_eval import cases, load_cache, score, CACHE, RES

SYSTEM = "agent_mem"


def main():
    cs = sorted(cases(), key=lambda c: (c["as_of"], c["positive"])); cache = load_cache(); mem = IncidentMemory()
    print(f"{len(cs)} cases in chronological order; {sum((c['id'], SYSTEM) in cache for c in cs)} cached", flush=True)
    for n, c in enumerate(cs, 1):
        rel, dep = data.fetch(c["package"], c["as_of"]); hits = indicators.recent(indicators.compute(rel, dep), rel, c["as_of"], C.RECENT_DAYS)
        outcome = "compromise" if c["positive"] else "benign"; res = cache.get((c["id"], SYSTEM))
        if res is None:
            res = pipeline.investigate(c["package"], c["as_of"], memory=mem if hits else None)
            mr = res.pop("_mem_res", None); res.pop("hits", None)
            res.update(case=c["id"], system=SYSTEM, package=c["package"], positive=c["positive"], as_of=str(c["as_of"]),
                       truth_list=sorted(map(list, c["truth"])), memories_recalled=len(res.get("memory", [])))
            with CACHE.open("a") as f: f.write(json.dumps(res, default=str) + "\n")
            if mr is not None: mem.give_feedback(mr, outcome)
            print(f"  [{n}/{len(cs)}] {c['id']:34} recalled {res['memories_recalled']} -> {res['risk_level']}", flush=True)
        if hits: mem.remember(c["id"], [h["indicator"] for h in hits], outcome)
    cache = load_cache(); ids = {c["id"] for c in cs}
    rows = [dict(r, truth={tuple(x) for x in r["truth_list"]}) for (cid, _), r in cache.items() if cid in ids]
    sc = score(rows); (RES / "scoreboard.json").write_text(json.dumps(sc, indent=1)); print(json.dumps(sc, indent=1))


if __name__ == "__main__": main()
