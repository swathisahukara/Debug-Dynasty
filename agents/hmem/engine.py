import copy, math, re
from dataclasses import dataclass, field
from typing import Optional

DAY_MS = 24 * 60 * 60 * 1000
FEEDBACK_DELTAS = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.2}
DEFAULTS = dict(retrievalTopN=5, retrievalThreshold=0.35, consolidationDays=7, archiveMinDays=30, archiveMaxAccess=2,
                synthesisCosine=0.82, dreamClusterMinSize=2, dreamRelatedness=0.35, maxDreamProposalsPerType=8,
                conflictAutoResolveGate=0.7, entityCap=10, relatedCap=5, recencyDays=14)
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
TECH_TERMS = ["react", "python", "typescript", "javascript", "rust", "sqlite", "postgres", "indexeddb", "node", "docker",
              "graphql", "redis", "webrtc", "tauri", "electron", "llm", "embedding"]
DOMAIN_KEYWORDS = {"tech": ["code", "bug", "api", "database", "deploy", "framework", "library", "server"] + TECH_TERMS,
                   "work": ["meeting", "deadline", "client", "project", "sprint", "review", "report"],
                   "personal": ["family", "hobby", "prefer", "like", "dislike", "morning", "evening"]}
OPPOSING = [(r"\balways\b", r"\bnever\b"), (r"\benable[ds]?\b", r"\bdisable[ds]?\b"), (r"\bprefer[s]?\b", r"\bavoid[s]?|dislike[s]?\b"),
            (r"\bon\b", r"\boff\b"), (r"\byes\b", r"\bno\b")]
clamp01 = lambda x: min(1.0, max(0.0, x))


# ---- deterministic embedder (same as the reference: FNV-1a hash per token into 64 dims, L2-normalised)
def tokenize(text):
    return [t for t in re.sub(r"[^a-z0-9\s]", " ", text.lower()).split() if len(t) > 1]


def _fnv1a(s):
    h = 0x811C9DC5
    for ch in s:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return h


def embed(text, dim=64):
    v = [0.0] * dim
    for t in tokenize(text):
        h = _fnv1a(t)
        v[h % dim] += (1 if ((h >> 8) % 2 == 0) else -1) * (1 + ((h >> 16) % 8) / 8)
    n = math.sqrt(sum(x * x for x in v))
    return v if n == 0 else [x / n for x in v]


cosine = lambda a, b: sum(x * y for x, y in zip(a, b))


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb: return 0.0
    return len(sa & sb) / (len(sa) + len(sb) - len(sa & sb))


@dataclass
class Memory:
    id: str; content: str; type: str; layer: str; timestamp: float; last_accessed: float; access_count: int
    tags: list; embedding: list; confidence: float; source: str; provenance: dict
    domain: str; namespace: str; entities: list
    related_to: list = field(default_factory=list)
    supersedes: Optional[str] = None; superseded_by: Optional[str] = None
    derived_from: list = field(default_factory=list)
    chat_id: Optional[str] = None; missionId: Optional[str] = None; goal_run_id: Optional[str] = None

    def snapshot(self):
        d = copy.deepcopy(self.__dict__); d.pop("embedding", None); return d


class TrustLedger:
    """Append-only audit trail; entries are never mutated or deleted."""
    def __init__(self, clock): self.clock, self.entries = clock, []

    def log(self, memory_id, action, actor, previous=None, new=None, details=None):
        e = dict(memoryId=memory_id, action=action, actor=actor, timestamp=self.clock(), previousState=previous, newState=new, details=details or {})
        self.entries.append(e); return e

    def history(self, memory_id): return [e for e in self.entries if e["memoryId"] == memory_id]
    def stats(self):
        out = {}
        for e in self.entries: out[e["action"]] = out.get(e["action"], 0) + 1
        return out


class Store:
    def __init__(self, clock, ledger, actor): self.clock, self.ledger, self.actor, self.records, self.seq = clock, ledger, actor, {}, 0

    def classify_domain(self, content, tags, mtype):
        for t in tags:
            if t.startswith("project:"): return t[8:]
            if t.startswith("tech:"): return "tech"
        toks = set(tokenize(content)); best, best_s = "general", 0
        for dom, kws in DOMAIN_KEYWORDS.items():
            s = sum(1 for k in kws if k in toks)
            if dom == "personal" and mtype in ("personal", "preference"): s += 1
            if s > best_s: best, best_s = dom, s
        return best if best_s > 0 else "general"

    def extract_entities(self, content):
        ents = []
        for t in tokenize(content):
            if t in TECH_TERMS and t not in ents: ents.append(t)
        for m in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", content):
            n = m.group(1).lower()
            if n not in ("the", "this", "that", "with") and n not in ents: ents.append(n)
        return ents[:DEFAULTS["entityCap"]]

    def add(self, content, source, type="general", layer="working", tags=None, confidence=0.7, provenance=None,
            supersedes=None, derived_from=None, chat_id=None, goal_run_id=None):
        if not source or not str(source).strip():
            raise ValueError("H-MEM: a memory record with no source must be rejected by construction")
        now = self.clock(); self.seq += 1; mid = f"mem-{self.seq}"; tags = list(tags or [])
        dom = self.classify_domain(content, tags, type)
        bucket = "profile" if type in ("preference", "personal") else "facts" if type == "factual" else "notes"
        m = Memory(id=mid, content=content, type=type, layer=layer, timestamp=now, last_accessed=now, access_count=0, tags=tags,
                   embedding=embed(content), confidence=clamp01(confidence), source=source,
                   provenance=provenance or dict(origin="manual", learnedAt=now, label=source), domain=dom, namespace=f"{dom}/{bucket}",
                   entities=self.extract_entities(content), supersedes=supersedes, derived_from=list(derived_from or []),
                   chat_id=chat_id, goal_run_id=goal_run_id)
        self._relate(m); self.records[mid] = m
        self.ledger.log(mid, "create", self.actor, new=m.snapshot()); return m

    def _relate(self, m):
        corr = re.compile(r"\b(actually|instead|no longer|not anymore|changed to|correction)\b", re.I)
        for o in self.records.values():
            if len(m.related_to) >= DEFAULTS["relatedCap"]: break
            shared = [e for e in o.entities if e in m.entities]
            if not m.supersedes and cosine(m.embedding, o.embedding) > 0.85 and corr.search(m.content):
                m.supersedes = o.id; continue
            if shared and o.domain == m.domain:
                m.related_to.append(o.id)
                if len(o.related_to) < DEFAULTS["relatedCap"] and m.id not in o.related_to: o.related_to.append(m.id)

    def get(self, mid): return self.records.get(mid)
    def all(self): return list(self.records.values())

    def update(self, mid, **patch):
        m = self._must(mid); prev = m.snapshot()
        for k, v in patch.items(): setattr(m, k, v)
        self.ledger.log(mid, "update", self.actor, prev, m.snapshot()); return m

    def delete(self, mid, reason):
        m = self._must(mid); del self.records[mid]
        self.ledger.log(mid, "delete", self.actor, previous=m.snapshot(), details=dict(reason=reason))

    def touch(self, mid):
        m = self._must(mid); m.last_accessed = self.clock(); m.access_count += 1

    def promote(self, mid, layer):
        m = self._must(mid); prev = m.snapshot(); m.layer = layer
        self.ledger.log(mid, "promote", self.actor, prev, m.snapshot())

    def _must(self, mid):
        if mid not in self.records: raise KeyError(f"H-MEM: unknown memory id {mid}")
        return self.records[mid]


class Retrieval:
    def __init__(self, store, ledger, clock, actor): self.store, self.ledger, self.clock, self.actor = store, ledger, clock, actor

    def _score(self, m, qe, qt, qents, qdom):
        age = (self.clock() - m.last_accessed) / DAY_MS
        raw = (0.35 * clamp01(cosine(qe, m.embedding)) + 0.2 * jaccard(qt, tokenize(m.content)) + 0.1 * jaccard(qt, [t.lower() for t in m.tags])
               + 0.1 * (1 if m.domain == qdom else 0) + 0.15 * jaccard(qents, m.entities) + 0.05 * LAYER_WEIGHT[m.layer]
               + 0.05 * math.exp(-age / DEFAULTS["recencyDays"]) - 0.2 * (1 if m.superseded_by else 0))
        return clamp01(raw) * m.confidence

    def query(self, query, topN=None, threshold=None, chat_id=None, tags_any=None):
        topN = DEFAULTS["retrievalTopN"] if topN is None else topN
        threshold = DEFAULTS["retrievalThreshold"] if threshold is None else threshold
        qe, qt, qents = embed(query), tokenize(query)[:8], self.store.extract_entities(query)
        qdom = self.store.classify_domain(query, [], "general")
        scored = []
        for m in self.store.all():
            if chat_id and m.chat_id and m.chat_id != chat_id: continue
            if tags_any and not (set(tags_any) & set(m.tags)): continue
            s = self._score(m, qe, qt, qents, qdom)
            if s >= threshold: scored.append((m, s))
        scored.sort(key=lambda x: (-x[1], x[0].id)); top = scored[:topN]
        for m, _ in top:
            self.store.touch(m.id); self.ledger.log(m.id, "read", self.actor, details=dict(query=query))
        n = len(top)
        strategy = "minimal" if n <= 1 else "personal" if any(m.type in ("personal", "preference") for m, _ in top) else "comprehensive"
        return QueryResult(memories=[Retrieved(m, s) for m, s in top], context=self.format(top),
                           trace=dict(retrievalReason=f'hybrid ranking for "{query}" (domain: {qdom})', strategy=strategy,
                                      scores={m.id: round(s, 4) for m, s in top}))

    def format(self, items):
        if not items: return ""
        by = {}
        for m, _ in items: by.setdefault(m.domain, []).append(m)
        lines = ["[MEMORY CONTEXT]"]
        for dom in sorted(by):
            lines.append(f"## {dom}")
            for m in by[dom]:
                mk = {"long_term": "LT", "working": "WK", "short_term": "ST"}[m.layer]
                ents = f" (entities: {', '.join(m.entities)})" if m.entities else ""
                lines.append(f"- [{mk}] {m.content}{ents} <{m.id}>")
        lines.append("[/MEMORY CONTEXT]"); return "\n".join(lines)

    def feedback(self, mid, kind):
        m = self.store.get(mid)
        if not m: raise KeyError(f"H-MEM: unknown memory id {mid}")
        prev = m.snapshot()
        if kind == "helpful": m.access_count += 1
        m.confidence = clamp01(m.confidence + FEEDBACK_DELTAS[kind])
        if kind == "wrong" and "review" not in m.tags: m.tags.append("review")
        self.ledger.log(mid, "feedback", self.actor, prev, m.snapshot(), dict(kind=kind, delta=FEEDBACK_DELTAS[kind]))


@dataclass
class Retrieved:
    memory: Memory; relevance: float


@dataclass
class QueryResult:
    memories: list; context: str; trace: dict


class Conflicts:
    def __init__(self, store, ledger, clock, actor): self.store, self.ledger, self.clock, self.actor, self.found, self.seq = store, ledger, clock, actor, [], 0

    def scan(self):
        out, al = [], self.store.all()
        for i in range(len(al)):
            for j in range(i + 1, len(al)):
                c = self._check(al[i], al[j])
                if c:
                    out.append(c); self.found.append(c)
                    self.ledger.log(c["memoryA"], "conflict_detected", self.store.actor, details=dict(with_=c["memoryB"], reason=c["reason"], confidence=c["confidence"]))
        return out

    def _check(self, a, b):
        if a.supersedes == b.id or b.supersedes == a.id or a.superseded_by == b.id or b.superseded_by == a.id: return None
        sim = cosine(a.embedding, b.embedding); reason, conf = "", 0.0
        for p, q in OPPOSING:
            if (re.search(p, a.content, re.I) and re.search(q, b.content, re.I)) or (re.search(q, a.content, re.I) and re.search(p, b.content, re.I)):
                if sim > 0.5: reason, conf = "opposing phrase pair on similar content", 0.5 + 0.3 * sim
        if not reason and sim > 0.8:
            na, nb = re.findall(r"\d+(?:\.\d+)?", a.content), re.findall(r"\d+(?:\.\d+)?", b.content)
            if na and nb and ",".join(na) != ",".join(nb): reason, conf = "high-similarity conflicting numeric values", 0.55 + 0.25 * sim
        if not reason: return None
        if [e for e in a.entities if e in b.entities]: conf += 0.1
        if a.domain == b.domain: conf += 0.05
        if b.id in a.related_to: conf -= 0.1
        self.seq += 1
        return dict(id=f"conflict-{self.seq}", memoryA=a.id, memoryB=b.id, reason=reason, confidence=clamp01(conf), resolved=False)

    def auto_resolve(self, c):
        a, b = self.store.get(c["memoryA"]), self.store.get(c["memoryB"])
        sc = lambda m: (0.3 * (m.last_accessed / max(1, self.clock())) + 0.2 * min(1, m.access_count / 10) + 0.25 * m.confidence
                        + 0.1 * min(1, len(m.content) / 200) + 0.15 * (1 if m.provenance.get("origin") == "user_correction" else 0.5))
        sa, sb = sc(a), sc(b); margin = abs(sa - sb) / max(sa, sb)
        dc = clamp01(c["confidence"] * 0.6 + margin * 0.8)
        if dc < DEFAULTS["conflictAutoResolveGate"]: return "queued"
        win, lose = (a, b) if sa >= sb else (b, a); prev = lose.snapshot(); lose.superseded_by = win.id
        c["resolved"] = True; c["resolution"] = "keep_a" if win.id == c["memoryA"] else "keep_b"
        self.ledger.log(lose.id, "conflict_resolved", self.store.actor, prev, lose.snapshot(), dict(conflictId=c["id"], winner=win.id, decisionConfidence=round(dc, 3)))
        return "resolved"


class Sleep:
    def __init__(self, store, ledger, clock, actor): self.store, self.ledger, self.clock, self.actor, self.backups, self.bseq = store, ledger, clock, actor, {}, 0

    def preview(self):
        now, al = self.clock(), self.store.all(); ref = set()
        for m in al:
            ref.update(m.related_to); ref.update(m.derived_from)
            if m.supersedes: ref.add(m.supersedes)
        cons = [m.id for m in al if m.layer == "short_term" and now - m.last_accessed >= DEFAULTS["consolidationDays"] * DAY_MS]
        arch = []
        for m in al:
            if not (now - m.timestamp >= DEFAULTS["archiveMinDays"] * DAY_MS and m.access_count <= DEFAULTS["archiveMaxAccess"] and m.id not in ref): continue
            if m.supersedes or m.derived_from or len(m.related_to) >= 3: continue  # guardrails
            arch.append(m.id)
        syn, used = [], set()
        for i, a in enumerate(al):
            if a.id in used: continue
            grp = [a] + [b for b in al[i + 1:] if b.id not in used and cosine(a.embedding, b.embedding) >= DEFAULTS["synthesisCosine"]]
            if len(grp) >= 2:
                used.update(g.id for g in grp); syn.append([g.id for g in grp])
        return dict(toConsolidate=cons, toArchive=arch, toSynthesize=syn)

    def execute(self, plan=None):
        plan = plan or self.preview(); self.bseq += 1; bid = f"backup-{self.bseq}"
        self.backups[bid] = (copy.deepcopy(self.store.records), self.store.seq); log = [f"backup {bid} created"]
        for i in plan["toConsolidate"]:
            if self.store.get(i): self.store.promote(i, "long_term"); self.ledger.log(i, "sleep_consolidate", self.actor); log.append(f"consolidated {i}")
        for i in plan["toArchive"]:
            m = self.store.get(i)
            if m: self.ledger.log(i, "sleep_archive", self.actor, details=dict(accessCount=m.access_count)); self.store.delete(i, "sleep archive"); log.append(f"archived {i}")
        syn = 0
        for grp in plan["toSynthesize"]:
            mem = [self.store.get(i) for i in grp]; mem = [m for m in mem if m]
            if len(mem) < 2: continue
            n = self.store.add("Synthesis: " + " | ".join(m.content for m in mem), source="sleep:synthesis", type="factual", layer="long_term",
                               tags=sorted({t for m in mem for t in m.tags}), confidence=max(m.confidence for m in mem),
                               provenance=dict(origin="sleep_synthesis", learnedAt=self.clock(), label=f"synthesized from {len(mem)} memories"),
                               derived_from=[m.id for m in mem])
            self.ledger.log(n.id, "sleep_synthesize", self.actor, details=dict(sources=grp))
            for m in mem: self.store.delete(m.id, "merged by sleep synthesis")
            syn += 1
        return dict(backupId=bid, consolidated=len(plan["toConsolidate"]), archived=len(plan["toArchive"]), synthesized=syn, actionLog=log)

    def restore(self, bid):
        recs, seq = self.backups[bid]; self.store.records, self.store.seq = copy.deepcopy(recs), seq; self.ledger.log("*", "restore", self.actor, details=dict(backupId=bid))


class Dreaming:
    def __init__(self, store, ledger, clock, actor): self.store, self.ledger, self.clock, self.actor, self.props, self.seq = store, ledger, clock, actor, {}, 0

    def _rel(self, a, b):
        return (0.5 * max(0, cosine(a.embedding, b.embedding)) + 0.2 * jaccard(a.tags, b.tags) + 0.1 * (a.domain == b.domain) + 0.2 * jaccard(a.entities, b.entities))

    def dream(self):
        out = []
        def propose(typ, content, derived, dom=None):
            self.seq += 1; p = dict(id=f"dream-{self.seq}", type=typ, content=content, derivedFrom=derived, suggestedDomain=dom, status="proposed")
            self.props[p["id"]] = p; out.append(p); self.ledger.log(p["id"], "dream_proposed", self.actor, details=dict(type=typ, derivedFrom=derived))
        al, used, n = self.store.all(), set(), 0
        for seed in al:
            if seed.id in used: continue
            grp = [seed] + [o for o in al if o.id != seed.id and o.id not in used and self._rel(seed, o) >= DEFAULTS["dreamRelatedness"]]
            if len(grp) >= DEFAULTS["dreamClusterMinSize"] and n < DEFAULTS["maxDreamProposalsPerType"]:
                used.update(g.id for g in grp); n += 1
                propose("insight", f"Across {len(grp)} related memories ({'/'.join(sorted({m.domain for m in grp}))}): " + " + ".join(m.content for m in grp), [m.id for m in grp])
        nd = 0
        for m in self.store.all():
            if nd >= DEFAULTS["maxDreamProposalsPerType"]: break
            if m.domain == "general":
                s = self.store.classify_domain(m.content, m.tags, m.type)
                if s != "general": propose("domain", f'Reclassify "{m.content[:60]}" as {s}', [m.id], s); nd += 1
        by = {}
        for m in self.store.all():
            if m.type in ("preference", "personal") or "event:user_correction" in m.tags: by.setdefault(m.domain, []).append(m)
        ni = 0
        for dom, lst in by.items():
            if ni >= DEFAULTS["maxDreamProposalsPerType"]: break
            if len(lst) >= 2: propose("invariant", f"Stable pattern in {dom}: " + "; ".join(m.content for m in lst), [m.id for m in lst]); ni += 1
        return out

    def approve(self, pid):
        p = self.props.get(pid)
        if not p or p["status"] != "proposed": raise KeyError(f"H-MEM: no pending proposal {pid}")
        p["status"] = "approved"; self.ledger.log(pid, "dream_approved", self.actor, details=dict(type=p["type"]))
        if p["type"] == "domain":
            for i in p["derivedFrom"]:
                if self.store.get(i) and p["suggestedDomain"]: self.store.update(i, domain=p["suggestedDomain"])
            return None
        return self.store.add(p["content"], source="dreaming", type="factual" if p["type"] == "insight" else "preference", layer="long_term",
                              tags=[f"dream:{p['type']}"], confidence=0.75, provenance=dict(origin="dream", learnedAt=self.clock(), label=f"approved {p['type']} proposal"),
                              derived_from=p["derivedFrom"])

    def reject(self, pid):
        p = self.props.get(pid)
        if not p or p["status"] != "proposed": raise KeyError(f"H-MEM: no pending proposal {pid}")
        p["status"] = "rejected"; self.ledger.log(pid, "dream_rejected", self.actor, details=dict(type=p["type"]))


class HMEM:
    def __init__(self, clock=None, actor="system"):
        import time
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.ledger = TrustLedger(self.clock); self.store = Store(self.clock, self.ledger, actor)
        self.retrieval = Retrieval(self.store, self.ledger, self.clock, actor)
        self.conflicts = Conflicts(self.store, self.ledger, self.clock, actor)
        self.sleep = Sleep(self.store, self.ledger, self.clock, actor); self.dreaming = Dreaming(self.store, self.ledger, self.clock, actor)

    def add(self, content, source, **kw): return self.store.add(content, source, **kw)
    def query(self, query, **kw): return self.retrieval.query(query, **kw)
    def feedback(self, memory_id, kind): self.retrieval.feedback(memory_id, kind)
