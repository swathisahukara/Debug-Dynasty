"""UI server endpoints (in-process, mock LLM, SAMPLE_MODE data). No network, no keys."""
import json, os, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path
os.environ.update(SAMPLE_MODE="1", LLM_MOCK="1", DATA_SOURCE="csv")
from http.server import ThreadingHTTPServer
from app import server


def call(port, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def events(self, body):
        code, text = call(self.port, "/api/investigate", body)
        self.assertEqual(code, 200, text)
        return [json.loads(l[6:]) for l in text.split("\n\n") if l.startswith("data: ")]

    def test_state_has_graph_and_cases(self):
        code, text = call(self.port, "/api/state"); d = json.loads(text)
        self.assertEqual(code, 200); self.assertGreater(len(d["graph"]["rules"]), 0); self.assertGreater(len(d["cases"]), 0)

    def test_replay_flags_the_incident_with_zero_llm_calls(self):
        c = next(c for c in json.loads(call(self.port, "/api/state")[1])["cases"] if c["package"] == "ua-parser-js")
        res = [e for e in self.events({"package": "ua-parser-js", "as_of": c["as_of"], "mode": "replay"}) if e["type"] == "result"][0]
        self.assertEqual(res["risk"], "medium"); self.assertEqual(res["meter"]["calls"], 0); self.assertTrue(res["cited"])

    def test_agent_mode_streams_log_and_result_with_mock_llm(self):
        c = next(c for c in json.loads(call(self.port, "/api/state")[1])["cases"] if c["package"] == "ua-parser-js")
        ev = self.events({"package": "ua-parser-js", "as_of": c["as_of"], "mode": "agent"})
        self.assertIn("agent_start", [e["rec"]["event"] for e in ev if e["type"] == "log"])
        self.assertEqual([e for e in ev if e["type"] == "result"][0]["mode"], "agent")

    def test_bad_package_name_is_rejected(self):
        self.assertEqual(call(self.port, "/api/investigate", {"package": "x; rm -rf"})[0], 400)

    def test_public_mode_is_read_only(self):
        old = server.PUBLIC; server.PUBLIC = True
        try:
            self.assertEqual(call(self.port, "/api/investigate", {"package": "ua-parser-js", "mode": "agent"})[0], 403)
            self.assertEqual(call(self.port, "/api/investigate", {"package": "ua-parser-js", "learn": True})[0], 403)
            self.assertEqual(call(self.port, "/api/rule", {"when": "release_burst", "risk": "low"})[0], 403)
            self.assertEqual(call(self.port, "/api/source", {"source": "zetaris"})[0], 403)
        finally: server.PUBLIC = old

    def test_fleet_grid_shape(self):
        d = json.loads(call(self.port, "/api/fleet")[1])
        self.assertEqual(len(d["cells"]), len(d["packages"])); self.assertTrue(all(len(r) == len(d["dates"]) for r in d["cells"]))
        self.assertEqual(d["stats"]["llm_calls"], 0); self.assertGreater(d["stats"]["cells"], 0)

    def _incident(self):
        return next(c for c in json.loads(call(self.port, "/api/state")[1])["cases"] if c["package"] == "ua-parser-js")

    def test_record_saves_a_replayable_trace_and_public_mode_plays_it(self):
        c = self._incident(); old = (server.RECORDED, server.REC_SPEED, server.PUBLIC)
        with tempfile.TemporaryDirectory() as d:
            server.RECORDED, server.REC_SPEED = Path(d), 0
            try:
                code, text = call(self.port, "/api/record", {"package": "ua-parser-js", "as_of": c["as_of"], "source": "csv"})
                self.assertEqual(code, 200, text); self.assertEqual(len(list(Path(d).glob("*.json"))), 1)
                server.PUBLIC = True
                code, text = call(self.port, "/api/investigate", {"package": "ua-parser-js", "as_of": c["as_of"], "mode": "agent"})
                self.assertEqual(code, 200, text)
                ev = [json.loads(l[6:]) for l in text.split("\n\n") if l.startswith("data: ")]
                self.assertEqual(ev[0]["role"], "recorded")
                res = [e for e in ev if e["type"] == "result"][0]
                self.assertEqual(res["mode"], "agent"); self.assertIn("recorded", res); self.assertEqual(res["recorded"]["source"], "csv")
                code, text = call(self.port, "/api/investigate", {"package": "async", "mode": "agent"})   # no recording for this case
                self.assertEqual(code, 403); self.assertIn("recorded", text)
            finally: server.RECORDED, server.REC_SPEED, server.PUBLIC = old

    def test_record_is_local_only(self):
        c = self._incident(); body = {"package": "ua-parser-js", "as_of": c["as_of"], "source": "csv"}
        self.assertEqual(call(self.port, "/api/record", body, {"X-Forwarded-For": "8.8.8.8"})[0], 403)   # arrived through a tunnel or proxy
        self.assertEqual(call(self.port, "/api/record", body, {"Cf-Ray": "abc"})[0], 403)
        old = server.PUBLIC; server.PUBLIC = True
        try: self.assertEqual(call(self.port, "/api/record", body)[0], 403)
        finally: server.PUBLIC = old

    def test_precomputed_public_grid_matches_current_graph(self):
        pre = json.loads(server.PRECOMPUTED.read_text())
        self.assertEqual(pre["graph_sha"], server._graph_sha(), "graph changed: run DATA_DIR=data/public python3 -m app.server --build-fleet")
        self.assertEqual(pre["stats"]["llm_calls"], 0)

    def test_rate_limiter(self):
        server.RATE.clear()
        self.assertTrue(all(server.rate_ok("1.2.3.4", limit=3) for _ in range(3)))
        self.assertFalse(server.rate_ok("1.2.3.4", limit=3)); self.assertTrue(server.rate_ok("5.6.7.8", limit=3))


if __name__ == "__main__":
    unittest.main()
