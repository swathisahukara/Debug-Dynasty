"""H-MEM (Meterless memory engine) implemented in Python for Package Trail.

Port of the Apache-2.0 reference at engines/hmem (spec: engines/hmem/AGENTS.md). Same contracts: mandatory source and
confidence, tiered layers, the eight-signal ranking formula, domain-grouped reinjection with trace, an append-only trust
ledger, exact feedback deltas, conflict auto-resolution gated at 0.70, preview-first sleep with guardrails, and dreaming
with an approval boundary. Verified against the official conformance vectors by eval/hmem_conformance.py.
"""
from .engine import HMEM, DEFAULTS, FEEDBACK_DELTAS, embed, cosine, tokenize, jaccard  # noqa: F401
