"""Single-shot LLM baseline: same pseudonymized timeline, no precomputed indicators, no Skeptic, no Evaluator, no retries."""
import json, time
from . import data, evidence, llm
from .pipeline import STYLE, pack, valid_rows


def investigate(pkg, as_of):
    llm.reset_meter(); t0 = time.time()
    rel, dep = data.fetch(pkg, as_of)
    ev, _ = evidence.build(pkg, rel, dep, [], window=40)
    res = dict(package=pkg, as_of=str(as_of), system="single_shot", row_versions={r["row"]: r["version"] for r in ev["releases"]})
    try:
        out, _ = llm.chat_json("baseline", STYLE, pack(ev, 'Assess whether this package shows signs of compromise or takeover. Return {"risk_level":"low|medium|high","summary":"2 sentences","indicators":[{"why":"...","rows":["R3"]}]}.\n'))
        res.update(risk_level=out.get("risk_level", "unknown"), indicators=out.get("indicators", []), summary=out.get("summary", ""))
    except RuntimeError as e:
        res.update(risk_level="unknown", indicators=[], summary=str(e)[:200])
    res["meter"] = llm.meter_snapshot(); res["wall_s"] = round(time.time() - t0, 2)
    return res
