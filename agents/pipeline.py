"""Planner -> Retriever -> Skeptic -> Evaluator -> Reporter, with critique/retry loops and a JSONL run log."""
import json, time
from datetime import datetime
from . import config as C, data, evidence, indicators, llm

LOG = C.ROOT / "logs" / f"run-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
STYLE = ("Do not write any reasoning. Output only the JSON object, as compact as possible (each text field at most 25 words, at most 2 benign explanations per hit). You report risk INDICATORS (signals), never accusations. Every claim must cite row ids (like R12) that exist in the evidence. "
         "Names and dates are pseudonymized on purpose. Reply with one JSON object only, no prose.")


def log(event, **kw):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(dict(ts=datetime.now().isoformat(timespec="seconds"), event=event, **kw), default=str) + "\n")


def pack(ev, extra=""):
    return extra + "EVIDENCE:" + json.dumps(ev) + "\nENDEVIDENCE"


def valid_rows(ev): return {r["row"] for r in ev["releases"]}


def evaluate_skeptic(out, ev):
    """Evaluator: every hit assessed once, every citation is a real evidence row."""
    errs, ids = [], {h["id"] for h in ev["indicator_hits"]}
    got = [a.get("hit") for a in out.get("assessments", [])]
    for h in ids - set(got): errs.append(f"hit {h} has no assessment")
    for a in out.get("assessments", []):
        if not a.get("citations"): errs.append(f"hit {a.get('hit')} cites no rows")
        for c in a.get("citations", []):
            if c not in valid_rows(ev): errs.append(f"citation {c} is not in the evidence")
    return errs


def evaluate_report(out, ev):
    errs = []
    if out.get("risk_level") not in ("low", "medium", "high"): errs.append("risk_level must be low, medium or high")
    ids = {h["id"] for h in ev["indicator_hits"]}
    kept = [a for a in ((ev.get("skeptic_assessments") or {}).get("assessments") or []) if a.get("keep")]
    if kept and out.get("risk_level") == "low":
        errs.append(f"risk_level low contradicts the {len(kept)} indicator(s) the Skeptic kept; use medium or high, or explain why they are benign and reject them")
    if kept and not out.get("indicators"): errs.append("the Skeptic kept indicators but the report lists none")
    for i in out.get("indicators", []):
        if i.get("hit") not in ids: errs.append(f"unknown hit {i.get('hit')}")
        if not i.get("rows"): errs.append(f"hit {i.get('hit')} cites no rows")
        for c in i.get("rows", []):
            if c not in valid_rows(ev): errs.append(f"row {c} is not in the evidence")
    return errs


def loop(role, system, ev, task, checker, max_retries=2):
    feedback = ""
    for attempt in range(max_retries + 1):
        try:
            out, raw = llm.chat_json(role, system, pack(ev, task + feedback + "\n"))
        except RuntimeError as e:
            log("agent", role=role, attempt=attempt, transport_error=str(e)); print(f"[{role}] {e}")
            return None, max_retries + 1
        else:
            errs = checker(out, ev)
        log("agent", role=role, attempt=attempt, errors=errs, output=out)
        if not errs: return out, attempt
        feedback = "\nYour previous answer was rejected by the Evaluator: " + "; ".join(errs) + ". Fix these and answer again.\n"
    return None, max_retries + 1


def investigate(pkg, as_of, memory=None):
    llm.reset_meter(); t0 = time.time()
    rel, dep = data.fetch(pkg, as_of)                        # Retriever
    hits = indicators.recent(indicators.compute(rel, dep), rel, as_of, C.RECENT_DAYS)
    log("retriever", package=pkg, as_of=str(as_of), releases=len(rel), hits=[(h["indicator"], h["version"]) for h in hits])
    res = dict(package=pkg, as_of=str(as_of), hits=hits, retries=0, path="cheap")
    if not hits:                                              # compile-and-replay precursor: no anomaly, no LLM call
        res.update(risk_level="low", summary="No indicator fired.", indicators=[])
    else:
        res["path"] = "llm"
        ev, rowmap = evidence.build(pkg, rel, dep, hits)
        mem_ctx, mem_res = "", None
        if memory is not None:                                   # H-MEM recall: similar past cases, as context only
            mem_res, mem_ctx = memory.recall([h["indicator"] for h in hits])
            res["memory"] = [dict(id=r.memory.id, relevance=round(r.relevance, 3), content=r.memory.content) for r in mem_res.memories]
            log("hmem_recall", trace=mem_res.trace, recalled=[r.memory.id for r in mem_res.memories])
        res["_mem_res"] = mem_res
        res["row_versions"] = {r["row"]: r["version"] for r in ev["releases"]}
        order = {"install_script_added": 0, "new_publisher_gap": 1, "release_burst": 2, "new_dependency": 3}
        plan = dict(focus=[h["id"] for h in sorted(ev["indicator_hits"], key=lambda h: (order[h["indicator"]], h["hours_before_T0"]))],
                    note="rule-based planner: install scripts and new publishers first, then newest")
        log("planner", plan=plan); a0 = 0
        skep, a1 = loop("skeptic", STYLE, ev, mem_ctx + 'Skeptic: for EACH hit give the most plausible benign explanations from the data, then decide keep (true if the data still looks unusual). '
                        'Return {"assessments":[{"hit":"H1","benign_explanations":[...],"keep":true,"citations":["R3"]}]}.', evaluate_skeptic)
        kept = [a for a in (skep or {}).get("assessments", []) if a.get("keep")]
        ev2 = dict(ev, skeptic_assessments=skep, planner=plan)
        rep, a2 = loop("reporter", STYLE, ev2, 'Reporter: produce the final report as {"risk_level":"low|medium|high","summary":"2 sentences","indicators":[{"hit":"H1","why":"...","rows":["R3"]}]}. '
                       "Only include hits the Skeptic kept. Use cautious signal language.", evaluate_report)
        res["retries"] = a0 + a1 + a2
        if rep is None: res.update(risk_level="unknown", summary="Reporter failed Evaluator checks after retries.", indicators=[])
        else: res.update(rep)
        res["kept_by_skeptic"] = len(kept)
    res["meter"] = llm.meter_snapshot(); res["wall_s"] = round(time.time() - t0, 2)
    log("result", **{k: v for k, v in res.items() if k not in ("hits", "_mem_res")})
    return res
