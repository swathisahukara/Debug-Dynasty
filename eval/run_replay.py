"""Replay the compiled graph over a package x month grid and compare cost against the other systems.
Offline by default (unseen indicator combinations are flagged for review). With --allow-llm, an unseen combination runs the
agent loop once and is compiled into a new rule (needs Nightshift). Usage: python3 -m eval.run_replay [--allow-llm --max-llm 5]"""
import os
os.environ.setdefault("DATA_SOURCE", "csv")  # thousands of cells: read the local merged CSVs (same rows Zetaris serves)
import argparse, json, time
from datetime import datetime
from agents import config as C, data, indicators
from agents.compiled import CompiledGraph, key
from eval.compile_graph import compile_graph
from eval.run_eval import cases, load_cache, RES


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--allow-llm", action="store_true"); ap.add_argument("--max-llm", type=int, default=5)
    a = ap.parse_args(); cs = cases(); cache = load_cache()
    inc = {c["id"]: c for c in cs if c["positive"]}; ctl_pkgs = {c["package"] for c in cs if not c["positive"]}
    pkgs = sorted({c["package"] for c in cs})
    months = [datetime(y, m, 1) for y in range(2018, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
    dates = sorted(set(months) | {c["as_of"] for c in cs})
    print('compiling graph from cached agent runs...', flush=True); base = compile_graph(); g = CompiledGraph()                      # keep rules already learned live
    for k, r in base.rules.items(): g.rules.setdefault(k, r)
    g.save()
    print(f'graph has {len(g.rules)} rules; replaying grid...', flush=True)
    cells, hit_cells, calls, usd, unseen, rules_flag, replay_flag, replay_fa, ctl_cells, fa_rules = 0, 0, 0, 0.0, [], 0, 0, 0, 0, 0
    t0 = time.time(); llm_used = 0; paths = {}
    for p in pkgs:
        for d in dates:
            if len(data.fetch(p, d)[0]) < 5: continue
            cells += 1
            if cells % 500 == 0: print(f'  ...{cells} cells replayed', flush=True)
            allow = a.allow_llm and llm_used < a.max_llm
            r = g.replay(p, d, allow_llm=allow)
            paths[r["path"]] = paths.get(r["path"], 0) + 1
            if r["path"] != "no_indicator": hit_cells += 1
            if r["path"] == "compiled_on_miss": llm_used += 1; calls += r["llm_calls"]; usd += r["est_usd"]
            if r["path"] == "unseen_flagged_for_review": unseen.append((p, str(d)[:10], r["rule"]))
            if p in ctl_pkgs:
                ctl_cells += 1; replay_fa += r["risk"] in ("medium", "high"); fa_rules += r["path"] != "no_indicator"
    if a.allow_llm: g.save()
    # held-out check: compile without each incident's own trace, replay that incident
    loo = []
    for cid, c in inc.items():
        gl = compile_graph(exclude={cid}); r = gl.replay(c["package"], c["as_of"])
        agent = cache.get((cid, "agent"), {}).get("risk_level")
        loo.append(dict(case=cid, replay=r["risk"], path=r["path"], agent=agent))
    sc = json.load(open(RES / "scoreboard.json"))
    agent_runs = [r for (cid, s), r in cache.items() if s == "agent" and r["meter"]["calls"] > 0]
    agent_per_llm_case = sum(r["meter"]["est_usd"] for r in agent_runs) / max(1, len(agent_runs))
    out = dict(grid=dict(packages=len(pkgs), dates=len(dates), cells=cells, cells_with_recent_indicator=hit_cells, control_cells=ctl_cells),
               rules_in_graph=len(g.rules), replay_paths=paths, replay_false_alarms_on_control_cells=f"{replay_fa}/{ctl_cells}",
               replay_llm_calls=calls, replay_est_usd=round(usd, 5), unseen_combinations_flagged_for_review=len({u[2] for u in unseen}),
               projected_usd=dict(single_shot_on_every_cell=round(cells * sc["single"]["est_usd_per_case"], 3),
                                  agent_loop_on_every_flagged_cell=round(hit_cells * agent_per_llm_case, 4),
                                  compiled_replay=round(usd + len({u[2] for u in unseen}) * agent_per_llm_case, 4)),
               projected_llm_calls=dict(single_shot=cells, agent_loop=round(hit_cells * (sum(r["meter"]["calls"] for r in agent_runs) / max(1, len(agent_runs)))), compiled_replay=calls + len({u[2] for u in unseen}) * 2),
               leave_one_incident_out=loo, seconds=round(time.time() - t0, 1))
    (RES / "replay_scoreboard.json").write_text(json.dumps(out, indent=1, default=str)); print(json.dumps(out, indent=1, default=str))
    if unseen: print("unseen combinations:", sorted({u[2] for u in unseen}))


if __name__ == "__main__": main()
