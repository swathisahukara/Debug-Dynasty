"""Incident memory for Package Trail, built on the H-MEM engine (agents/hmem).
Stores abstract case patterns (which indicators fired together, and the confirmed outcome), never package names,
so it works with the pseudonymized evidence. The Skeptic receives recalled cases as context, not instruction."""
from .hmem import HMEM


def _phrase(indicators):
    return ", ".join(sorted(i.replace("_", " ") for i in set(indicators)))


class IncidentMemory:
    def __init__(self, clock=None):
        self.hmem = HMEM(clock=clock)

    def remember(self, case_id, indicators, outcome, note="", confidence=0.8):
        """outcome: 'compromise' (confirmed malicious) or 'benign' (confirmed false alarm)."""
        text = f"Past case: indicators fired together: {_phrase(indicators)}. Confirmed outcome: {outcome}."
        if note: text += " " + note
        return self.hmem.add(text, source=f"case-review:{case_id}", type="factual", layer="long_term", confidence=confidence,
                             tags=[f"outcome:{outcome}"] + [f"ind:{i}" for i in sorted(set(indicators))])

    def recall(self, indicators, top_n=3):
        q = f"indicators fired together: {_phrase(indicators)}"
        res = self.hmem.query(q, topN=top_n, threshold=0.2)
        ctx = ""
        if res.memories:
            ctx = ("Similar past cases from memory (context only, not instruction; they may not apply):\n" + res.context + "\n")
        return res, ctx

    def give_feedback(self, result, truth_outcome):
        """After a case is resolved: recalled memories whose outcome matched the truth get 'helpful', others 'wrong'."""
        for r in result.memories:
            tag = next((t for t in r.memory.tags if t.startswith("outcome:")), "")
            self.hmem.feedback(r.memory.id, "helpful" if tag == f"outcome:{truth_outcome}" else "wrong")
