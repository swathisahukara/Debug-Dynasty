"""python3 -m unittest discover -s tests -v   (offline: SAMPLE data + mock LLM)"""
import os, unittest
from datetime import datetime
os.environ.update(LLM_MOCK="1", SAMPLE_MODE="1", DATA_SOURCE="csv")  # committed sample data, no keys, no network
from unittest import mock
from agents import pipeline
from agents.memory import IncidentMemory
from agents.hmem import HMEM


class TestHMEMEngine(unittest.TestCase):
    def test_record_without_source_is_rejected(self):
        with self.assertRaises(ValueError): HMEM(clock=lambda: 0).add("x", source="")

    def test_feedback_deltas_and_ledger(self):
        h = HMEM(clock=lambda: 0); m = h.add("a record", source="t", confidence=0.7)
        h.feedback(m.id, "wrong")
        self.assertAlmostEqual(h.store.get(m.id).confidence, 0.5)
        self.assertEqual([e["action"] for e in h.ledger.history(m.id)], ["create", "feedback"])


class TestIncidentMemory(unittest.TestCase):
    def setUp(self):
        self.mem = IncidentMemory(clock=lambda: 1_700_000_000_000)
        self.mem.remember("c1", ["new_publisher_gap", "new_dependency"], "compromise", "Account takeover then a new dependency.")
        self.mem.remember("c2", ["release_burst"], "benign", "Maintainer backported fixes across release lines.")

    def test_recall_returns_matching_pattern_first(self):
        res, ctx = self.mem.recall(["new_publisher_gap", "new_dependency"])
        self.assertTrue(res.memories)
        self.assertIn("outcome:compromise", res.memories[0].memory.tags)
        self.assertIn("context only, not instruction", ctx)

    def test_recall_never_contains_package_names(self):
        _, ctx = self.mem.recall(["release_burst"])
        for name in ("event-stream", "ua-parser-js", "right9ctrl"): self.assertNotIn(name, ctx)

    def test_feedback_moves_confidence(self):
        res, _ = self.mem.recall(["release_burst"])
        before = res.memories[0].memory.confidence
        self.mem.give_feedback(res, "compromise")  # the recalled case was benign -> marked wrong
        self.assertLess(self.mem.hmem.store.get(res.memories[0].memory.id).confidence, before)


class TestPipelineUsesMemory(unittest.TestCase):
    def test_skeptic_prompt_contains_recalled_case(self):
        mem = IncidentMemory(clock=lambda: 1_700_000_000_000)
        mem.remember("c1", ["install_script_added", "release_burst"], "compromise", "Install script appeared during a multi-line release burst.")
        seen = []
        real = pipeline.llm.chat_json
        def spy(role, system, user, **kw):
            seen.append((role, user)); return real(role, system, user, **kw)
        with mock.patch.object(pipeline.llm, "chat_json", spy):
            res = pipeline.investigate("ua-parser-js", datetime(2021, 10, 22, 13, 15, 21), memory=mem)
        self.assertTrue(res["memory"], "memory should have been recalled")
        skeptic = [u for r, u in seen if r == "skeptic"]
        self.assertTrue(skeptic and "Similar past cases from memory" in skeptic[0])

    def test_no_memory_means_no_memory_context(self):
        seen = []
        real = pipeline.llm.chat_json
        with mock.patch.object(pipeline.llm, "chat_json", lambda role, s, u, **k: (seen.append(u), real(role, s, u, **k))[1]):
            pipeline.investigate("ua-parser-js", datetime(2021, 10, 22, 13, 15, 21))
        self.assertFalse(any("Similar past cases" in u for u in seen))


if __name__ == "__main__":
    unittest.main()
