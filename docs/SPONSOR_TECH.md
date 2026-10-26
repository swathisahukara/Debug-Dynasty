# Sponsor technology: where each one is used

## Zetaris (data layer)
- Release, maintainer and dependency rows are served as REST tables (`releases_src`, `maintainers_src`, `dependencies_src`) and exposed as SchemaStore views `pkgtrail.releases_table`, `pkgtrail.maintainers_table`, `pkgtrail.dependencies_table` (`snapshot/zetaris_setup.sql`).
- The Retriever pulls a package's rows as of a cutoff through Lightning SQL over REST (`agents/data.py`, `POST /sql-editor/sqls/run`). Indicator queries are in `agents/sql/` (burst detection uses window functions because self-joins on REST-backed views are ambiguous).
- `DATA_SOURCE=zetaris` is the default for live runs; the UI has a switch between Zetaris and local CSV, and the compiled graph's query nodes carry the same SQL. The fleet heatmap (every package x every date) and the live npm check run the same compiled graph with zero model calls.
- Verify: `python3 snapshot/zetaris_sql.py -f snapshot/zetaris_verify.sql`, or switch the data source in the UI and replay a case.

## Meterless (two uses)
1. **Nightshift endpoint:** every model call goes through the OpenAI-compatible Nightshift endpoint with app and scope headers (`agents/llm.py`). A token-based cost meter feeds the UI and the evaluation.
2. **H-MEM engine:** the Apache-2.0 Meterless H-MEM spec is ported to Python (`agents/hmem/`) with 13 of 13 conformance vectors passing (`eval/hmem_conformance.py`) and 7 integration tests (`tests/test_hmem_integration.py`). `agents/memory.py` stores abstract incident patterns (indicators that fired together plus the confirmed outcome, no package names) and the Skeptic receives recalled cases as context only. The original Meterless sources are in `engines/` unmodified.

## NVIDIA Nemotron
Skeptic and Reporter run `nvidia/nemotron-3.5-lightning-30b-a3b` via Nightshift with terse JSON prompts, `/no_think`, retry on provider errors (502, 429) and Evaluator-driven retries.

## Cursor
The repository was built and iterated in Cursor.

## Third-party and pre-existing work (declared)
`engines/` are unmodified Meterless copies (Apache-2.0). `smoke_test.py` and early notes predate the hackathon; everything else was written during the event. See README.
