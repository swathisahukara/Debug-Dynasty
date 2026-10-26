"""Compile and replay. The agent loop's reasoning is compiled into an editable decision graph (JSON): Zetaris query nodes,
indicator nodes with parameters, and rule nodes keyed by indicator combination. Replay runs the graph with no LLM call
and cites exact package@version rows. A combination the graph has never seen is sent to the agent loop once, and the
verdict is compiled into a new rule (compile on miss)."""
import json
from pathlib import Path
from . import config as C, data, indicators

GRAPH_PATH = C.ROOT / "graphs" / "package_trail_graph.json"
SQL = {
    "q_releases": "SELECT package_name, version, published_at, publisher, install_scripts, dep_count, source FROM pkgtrail.releases_table WHERE package_name = :package AND published_at <= :as_of ORDER BY published_at",
    "q_dependencies": "SELECT version, dependency FROM pkgtrail.dependencies_table WHERE package_name = :package",
}
INDICATORS = {
    "new_publisher_gap": "publisher first seen after more than 180 days without a release",
    "release_burst": "3 or more release lines published within 10 minutes",
    "install_script_added": "an install-time script appears that the previous release lacked",
    "new_dependency": "new dependency in a same-major, non-prerelease release",
}
key = lambda hits: "+".join(sorted({h["indicator"] for h in hits}))


class CompiledGraph:
    def __init__(self, path=GRAPH_PATH, fresh=False):
        self.path = Path(path); self.rules = {}
        self.params = dict(recent_days=C.RECENT_DAYS, gap_days=180, burst_window_s=600, burst_lines=3)
        if self.path.exists() and not fresh:
            g = json.loads(self.path.read_text()); self.rules = {r["when"]: r for r in g["rules"]}; self.params = g.get("params", self.params)

    # ---- the editable artifact
    def to_json(self):
        nodes = [dict(id=i, type="zetaris_query", sql=q) for i, q in SQL.items()]
        nodes += [dict(id=f"i_{n}", type="indicator", impl=n, description=d, inputs=["q_releases", "q_dependencies"]) for n, d in INDICATORS.items()]
        nodes.append(dict(id="rules", type="rule_table", inputs=[f"i_{n}" for n in INDICATORS], default_if_no_indicator="low", unseen="llm_agent_loop_then_compile"))
        return dict(version=1, params=self.params, nodes=nodes, rules=sorted(self.rules.values(), key=lambda r: r["when"]))

    def save(self):
        self.path.parent.mkdir(exist_ok=True); self.path.write_text(json.dumps(self.to_json(), indent=1) + "\n")

    def learn(self, hits, risk, rationale, support=1, agreement=1.0, source="agent-loop"):
        k = key(hits); r = self.rules.get(k)
        if r: r["support"] += support
        else: self.rules[k] = dict(when=k, risk=risk, support=support, agreement=agreement, rationale=rationale, source=source)

    # ---- replay
    def replay(self, pkg, as_of, allow_llm=False, memory=None):
        rel, dep = data.fetch(pkg, as_of)
        return self.replay_rows(pkg, rel, dep, as_of, allow_llm=allow_llm, memory=memory)

    def replay_rows(self, pkg, rel, dep, as_of, dep_ages=None, allow_llm=False, memory=None):
        """Replay on rows already in hand (the live registry path). allow_llm needs the snapshot data, so live callers leave it off."""
        hits = indicators.recent(indicators.compute(rel, dep, dep_ages=dep_ages), rel, as_of, self.params["recent_days"])
        out = dict(package=pkg, as_of=str(as_of), llm_calls=0, est_usd=0.0, cited=[dict(indicator=h["indicator"], row=f"{pkg}@{h['version']}") for h in hits])
        if not hits: return dict(out, risk="low", path="no_indicator")
        k = key(hits); rule = self.rules.get(k)
        if rule: return dict(out, risk=rule["risk"], path="rule", rule=k, rationale=rule["rationale"])
        if not allow_llm: return dict(out, risk="medium", path="unseen_flagged_for_review", rule=k)
        from . import pipeline
        res = pipeline.investigate(pkg, as_of, memory=memory)
        self.learn(hits, res["risk_level"] if res["risk_level"] != "unknown" else "medium", res.get("summary", ""), source=f"agent-loop:{pkg}")
        return dict(out, risk=res["risk_level"], path="compiled_on_miss", rule=k, llm_calls=res["meter"]["calls"], est_usd=res["meter"]["est_usd"])
