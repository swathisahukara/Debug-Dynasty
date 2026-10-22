# Package Trail (team Debug Dynasty)

Open Agent Hackathon 2026. Ask "is this open-source package still trustworthy?" and get risk
**indicators** (signals, not accusations), each linked to a source row. The agent compiles its
reasoning into an editable graph of federated queries and rules, then replays it across many
packages and calls the LLM only on anomalies.

## Real vs synthetic data
- **Real:** public npm registry metadata (per-version publish times, publishers, maintainers, dependencies, install scripts), fetched by `snapshot/fetch_packuments.py`.
- **Synthetic:** any timelines replaying real incident patterns are generated and labeled `synthetic`. (None yet.)

## SAMPLE_MODE
`SAMPLE_MODE=1` runs on the small committed files in `data/sample/` with no network or API keys.
Full snapshot goes to `data/raw/` (git-ignored). Copy `.env.example` to `.env` for live mode.

## Layout
`snapshot/` data fetch, `data/` rows, `agents/` Planner/Retriever/Skeptic/Evaluator/Reporter, `eval/` scoring and baseline, `app/` UI.

## Pre-existing work (declared)
`smoke_test.py` (checks Zetaris, Nightshift, Nemotron connectivity) and setup notes were written before the build window opened. Everything else is built during the hackathon.
