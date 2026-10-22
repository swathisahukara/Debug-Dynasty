"""Runs the official Meterless H-MEM conformance vectors (engines/hmem/conformance/vectors/vectors.json) against agents.hmem.
Mirrors the checks in the reference runner.ts. Exit code 0 = all pass.  Usage: python3 -m eval.hmem_conformance"""
import json, sys
from pathlib import Path
from agents.hmem import HMEM

V = json.loads((Path(__file__).resolve().parent.parent / "engines/hmem/conformance/vectors/vectors.json").read_text())
T0, DAY = V["clock"], 24 * 60 * 60 * 1000
results = []


def case(section, c, fn):
    try: fn(c); results.append((section, c["id"], c["description"], True, ""))
    except AssertionError as e: results.append((section, c["id"], c["description"], False, str(e)))
    except Exception as e: results.append((section, c["id"], c["description"], False, repr(e)))


def ok(cond, msg):
    if not cond: raise AssertionError(msg)


def rv(c):
    h = HMEM(clock=lambda: T0); rejected = False
    try: h.add(c["input"]["content"], source=c["input"]["source"])
    except ValueError: rejected = True
    ok(rejected == (c["expect"] == "reject"), f"expected {c['expect']}")


def fd(c):
    h = HMEM(clock=lambda: T0); m = h.add("feedback target record", source="conformance", confidence=c["start"]); before = m.access_count
    h.feedback(m.id, c["kind"]); a = h.store.get(m.id)
    ok(abs(a.confidence - c["expectConfidence"]) < 1e-9, f"confidence {a.confidence}, expected {c['expectConfidence']}")
    if "expectAccessDelta" in c: ok(a.access_count - before == c["expectAccessDelta"], "access delta")
    if "expectTag" in c: ok(c["expectTag"] in a.tags, "missing tag")


def ro(c):
    h = HMEM(clock=lambda: T0); by = {}
    for r in c["records"]: by[r["key"]] = h.add(r["content"], source="conformance", confidence=r["confidence"], layer=r["layer"])
    for r in c["records"]:
        if r.get("supersededByKey"): by[r["key"]].superseded_by = by[r["supersededByKey"]].id
    order = [x.memory.id for x in h.query(c["query"], threshold=0, topN=10).memories]
    exp = [by[k].id for k in c["expectOrder"]]
    for i in range(len(exp) - 1): ok(order.index(exp[i]) < order.index(exp[i + 1]), f"expected {c['expectOrder'][i]} before {c['expectOrder'][i+1]}, got {order}")


def sg(c):
    now = [T0]; h = HMEM(clock=lambda: now[0]); by = {}
    for r in c["records"]: by[r["key"]] = h.add(r["content"], source=r["source"], derived_from=r.get("derivedFrom"))
    now[0] = T0 + c["ageDays"] * DAY; before = sorted(m.id for m in h.store.all()); p = h.sleep.preview()
    ok(sorted(m.id for m in h.store.all()) == before, "preview mutated the store")
    for k in c["expectArchived"]: ok(by[k].id in p["toArchive"], f"{k} should be archivable")
    for k in c["expectProtected"]: ok(by[k].id not in p["toArchive"], f"{k} is guardrail-protected")
    rep = h.sleep.execute(p)
    for k in c["expectProtected"]: ok(h.store.get(by[k].id) is not None, f"{k} deleted despite guardrails")
    ok(isinstance(rep["backupId"], str) and rep["backupId"], "execute must return backupId")


def cg(c):
    h = HMEM(clock=lambda: T0); a = h.add(c["a"]["content"], source="conformance", confidence=c["a"]["confidence"]); b = h.add(c["b"]["content"], source="conformance", confidence=c["b"]["confidence"])
    found = h.conflicts.scan(); ok(found, "opposing always/never pair must be detected")
    out = h.conflicts.auto_resolve(found[0]); ok(out in ("resolved", "queued"), out)
    if out == "resolved": ok(any(x and x.superseded_by for x in (h.store.get(a.id), h.store.get(b.id))), "loser must be superseded")
    ok(h.store.get(a.id) and h.store.get(b.id), "conflict resolution must never delete records")


def la(c):
    h = HMEM(clock=lambda: T0); m = h.add("audited record", source="conformance", confidence=c["start"]); h.feedback(m.id, c["kind"])
    hist = h.ledger.history(m.id); ok([e["action"] for e in hist] == c["expectActions"], f"actions {[e['action'] for e in hist]}")
    fb = hist[-1]; ok(abs(fb["previousState"]["confidence"] - c["expectPrev"]) < 1e-9, "prev"); ok(abs(fb["newState"]["confidence"] - c["expectNew"]) < 1e-9, "new")


def db(c):
    h = HMEM(clock=lambda: T0)
    for r in c["records"]: h.add(r["content"], source="conformance", type=r["type"])
    n = len(h.store.all()); props = h.dreaming.dream(); ok(props, "two related preferences must produce a proposal")
    ok(len(h.store.all()) == n, "dreaming must not materialize before approval")
    made = h.dreaming.approve(props[0]["id"])
    if made: ok(made.layer == "long_term", "approved -> long_term"); ok(made.derived_from, "lineage required")


for section, fn in [("record-validation", rv), ("feedback-deltas", fd), ("ranking-order", ro), ("sleep-guardrails", sg), ("conflict-gate", cg), ("ledger-audit", la), ("dream-boundary", db)]:
    for c in V["sections"][section]: case(section, c, fn)
cur = ""
for s, i, d, p, det in results:
    if s != cur: cur = s; print(f"\n  {s}")
    print(f"    {'PASS' if p else 'FAIL'} {i} {d}" + (f"\n         {det}" if det else ""))
n = sum(r[3] for r in results); print(f"\n  {n}/{len(results)} checks passed"); sys.exit(0 if n == len(results) else 1)
