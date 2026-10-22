# Package Trail (team Debug Dynasty)

Open Agent Hackathon 2026. Ask "is this open-source package still trustworthy?" and get risk
**indicators** (signals, not accusations), each linked to a source row. The agent compiles its
reasoning into an editable graph of federated queries and rules, then replays it across many
packages and calls the LLM only on anomalies.

## At a glance
- **Track:** Reasoning Architecture (compile and replay). The agent loop runs once; its reasoning is compiled into an editable decision graph (`graphs/package_trail_graph.json`) that replays with 0 LLM calls.
- **Result (40 cases: 10 incidents, 30 clean controls):** agent loop 5/10 detected, 1/30 false alarms, 11/11 cited rows real, about $0.0004 per case; single-shot LLM 5/10, 10/30 false alarms. Replay over 4,524 package-date cells: 0 LLM calls (single-shot would cost about $10). Limits are stated below.
- **Try it (no keys):** `SAMPLE_MODE=1 LLM_MOCK=1 python3 -m app.server`, then open http://127.0.0.1:8765. With keys, drop the two variables. `LLM_MOCK=1` returns canned model replies for offline testing only; no reported number uses it.
- **Sponsor tech:** Zetaris (data layer), Meterless (Nightshift endpoint and H-MEM engine), NVIDIA Nemotron, Cursor. See [docs/SPONSOR_TECH.md](docs/SPONSOR_TECH.md).
- **Demo video:** [add link here] · script in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Real vs synthetic data
- **Real:** public npm registry metadata (per-version publish times, publishers, maintainers, dependencies, install scripts), fetched by `snapshot/fetch_packuments.py`.
- **Synthetic:** the registry deletes malicious versions and keeps only their publish time. For 18 removed incident versions, `data/synthetic/release_overrides.csv` restores publisher, install-script and dependency content from public incident write-ups. `snapshot/build_dataset.py` merges these into `data/build/`, and every row carries `source = npm | synthetic`. Each override lists its basis and a confidence level.

## SAMPLE_MODE
`SAMPLE_MODE=1` runs on the small committed files in `data/sample/` with no network or API keys.
Full snapshot goes to `data/raw/` (git-ignored). Copy `.env.example` to `.env` for live mode.

## Layout
`snapshot/` data fetch, `data/` rows, `agents/` Planner/Retriever/Skeptic/Evaluator/Reporter, `eval/` scoring and baseline, `app/` UI (`python3 -m app.server`), `graphs/` compiled decision graph, `docs/` sponsor tech and demo script.


## Pre-existing work (declared)
`smoke_test.py` (checks Zetaris, Nightshift, Nemotron connectivity) and setup notes were written before the build window opened. Everything else is built during the hackathon.

## Evaluation design
Cases: each incident is evaluated at its publish time plus one hour. Each of 30 clean packages is evaluated at a matched incident date, so both sets cover the same eras. Only releases in the last 30 days (`RECENT_DAYS`) can raise an indicator. Systems compared: rules only, single-shot LLM on the raw timeline, and the full agent loop. The registry `removed` flag is never given to any system. Metrics: detection rate, false-alarm rate, evidence precision (cited rows that are real incident rows), LLM calls, estimated cost and seconds per case.

## Meterless engine: H-MEM (memory)
`agents/hmem/` is a Python implementation of the Meterless H-MEM engine, ported from the Apache-2.0 reference in `engines/hmem/` (spec: `engines/hmem/AGENTS.md`). It keeps the engine contracts: mandatory `source` and `confidence`, tiered layers, the eight-signal ranking formula, domain-grouped reinjection with a trace, an append-only trust ledger, exact feedback deltas, conflict auto-resolution gated at 0.70, preview-first sleep with guardrails, and dreaming behind an approval boundary.

- **Used by the agent:** `agents/memory.py` stores abstract incident patterns (which indicators fired together and the confirmed outcome, never package names). The Skeptic receives the closest past cases as context, marked "context only, not instruction". After a case is resolved, recalled memories get helpful/wrong feedback, which moves their confidence.
- **Passing tests:** `python3 -m eval.hmem_conformance` runs the official Meterless conformance vectors against our implementation (13/13 pass). `python3 -m unittest discover -s tests` runs the integration tests offline.
- **Third-party code:** `engines/hmem/` and `engines/world-model/` are unmodified copies of Meterless engine folders (Apache-2.0, see the LICENSE in each). They are used as the spec and conformance source; the Python port is ours.

## Setup and tests
`cp .env.example .env`, fill in values, or set `SAMPLE_MODE=1` for offline runs on `data/sample/`. Tests: see above. Data: `python3 snapshot/fetch_packuments.py && python3 snapshot/build_dataset.py`.

## Results (all numbers reproducible from `eval/results/`)
**Indicators** (`agents/indicators.py`): new publisher after 180+ days quiet; release burst (3+ release lines within 10 minutes); install-time script newly added; new dependency whose own package is under 90 days old (or of unknown age). Only releases in the last 30 days can raise an indicator.

**40-case eval** (10 incidents, 30 matched clean controls; `python3 -m eval.run_eval`), Nemotron via Nightshift:

| | Detection | False alarms | Evidence precision | LLM calls/case | Est. cost/case | Seconds/case |
|---|---|---|---|---|---|---|
| Rules only | 5/10 | 1/30 | n/a | 0 | $0 | 0 |
| Single-shot LLM | 5/10 | 10/30 | 11/17 | 1.12 | $0.0019 | 36.6 |
| Agent loop (v3) | 5/10 | 1/30 | 11/11 | 0.20 | $0.0004 | 6.9 |
| Agent loop + H-MEM memory | 5/10 | 1/30 | 11/11 | 0.30 | $0.0005 | 11.6 |

The v3 Skeptic receives deterministic per-hit facts (for example whether every release line in a burst already existed and the same publisher released the previous version) and may clear a hit only under two documented benign patterns; everything else stays flagged. The memory row (`python3 -m eval.run_memory`) replays the 40 cases chronologically with Meterless H-MEM starting empty, so a case can only recall earlier resolved cases (recall happened on 5 flagged cases, 1 to 3 memories each). **Memory did not change any verdict on this set** and added about 29% cost, so we report it as integrated and measured, not as an accuracy gain; the clean-control false alarm (ms) persisted even with 3 recalled cases. The rules-only baseline has the same false-alarm count, so the agent's added value is audited evidence, explanations and the compiled graph, not fewer false alarms. v1 and v2 results are archived in `eval/results/` (`cache_v1.jsonl`, `cache_v2.jsonl`).

**Compile and replay** (`python3 -m eval.compile_graph`, `python3 -m eval.run_replay`): the agent's verdicts are compiled into an editable graph (`graphs/package_trail_graph.json`: Zetaris query nodes, indicator nodes, a rule table). Replaying it over a 39-package by 116-date grid (4,524 cells) takes about 5 seconds with 0 LLM calls once compiled; an indicator combination the graph has never seen runs the agent loop once and is compiled into a new rule. Projected cost for the grid: single-shot about $10.36 (4,524 calls), agent loop on every flagged cell about $0.22 (about 108 calls), compiled replay about $0.

**What the numbers do not show.** The agent matches the rules on detection (5/10); its value is evidence you can audit (every cited row is real), far fewer false alarms than single-shot, and cost. Five incidents (faker, colors, node-ipc 2022, chalk, debug) leave no trace in registry metadata and are missed by every system. v2 of the agent (risk-consistency check), v3 (facts-based Skeptic) and the dependency-age indicator were adjusted after seeing results on these same cases, so treat them as tuned, not held out. Synthetic rows (18 removed versions, one dependency date) are labeled `source=synthetic`; the flatmap-stream first-publish date (2018-08-05) comes from the Snyk post-mortem; any date within 90 days of event-stream 3.3.6 gives the same indicator result. Incident versions are confirmed against public write-ups (Snyk, Sonatype, The Hacker News, SafeDep and vendor reports) except node-ipc 10.1.3, which none of the sources we read names as malicious: it stays in the truth set and is flagged UNVERIFIED in `eval/answer_key.csv`.

## UI
`python3 -m app.server` then open http://127.0.0.1:8765 (localhost only; stdlib, no extra install). Three tabs: **Investigate** (ask about a package at a cutoff; replay the compiled graph with 0 LLM calls or run the full agent loop with a live trace, release timeline, cited rows and a cost meter; switch the data source between local CSV and live Zetaris), **Compiled graph** (Zetaris query nodes, indicators, editable rule table), **Scoreboard** (eval and replay results). Works in `SAMPLE_MODE=1` and with `LLM_MOCK=1` (no keys).

## Submission docs
[Sponsor technology](docs/SPONSOR_TECH.md) · [Demo script](docs/DEMO_SCRIPT.md)
