"""Compile the decision graph from cached agent-loop runs (no LLM calls). Usage: python3 -m eval.compile_graph"""
import json, collections
from agents import config as C, data, indicators
from agents.compiled import CompiledGraph, key
from eval.run_eval import cases, load_cache


def compile_graph(exclude=()):
    g = CompiledGraph(fresh=True); cache = load_cache(); by = collections.defaultdict(list)
    for c in cases():
        if c["id"] in exclude or (c["id"], "agent") not in cache: continue
        rel, dep = data.fetch(c["package"], c["as_of"]); hits = indicators.recent(indicators.compute(rel, dep), rel, c["as_of"], C.RECENT_DAYS)
        if hits: by[key(hits)].append((hits, cache[(c["id"], "agent")]))
    for k, runs in by.items():
        votes = collections.Counter("low" if r["risk_level"] == "low" else "medium" if r["risk_level"] != "high" else "high" for _, r in runs)
        risk, n = votes.most_common(1)[0]
        if len(votes) > 1 and votes["medium"] + votes["high"] > 0: risk = "medium"  # disagreement -> conservative
        why = next((r.get("summary", "") for _, r in runs if r["risk_level"] == risk and r.get("summary")), "")
        g.learn(runs[0][0], risk, why, support=len(runs), agreement=round(n / len(runs), 2), source="compiled from agent-loop runs")
    return g


if __name__ == "__main__":
    g = compile_graph(); g.save(); print(f"compiled {len(g.rules)} rules -> {g.path}")
    for r in g.to_json()["rules"]: print(f"  {r['when']:50} -> {r['risk']:6} (support {r['support']}, agreement {r['agreement']})")
