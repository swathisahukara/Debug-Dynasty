"""Live registry converter and indicators on an offline fixture packument (no network)."""
import os, unittest
os.environ["SAMPLE_MODE"] = "1"
from datetime import datetime
from agents import indicators, live


def packument():
    t = {"created": "2020-01-01T00:00:00.000Z", "modified": "2024-05-01T10:05:00.000Z",
         "1.0.0": "2020-01-01T00:00:00.000Z", "1.0.1": "2020-02-01T00:00:00.000Z", "0.9.0": "2019-12-01T00:00:00.000Z",
         "1.1.0": "2024-05-01T10:00:00.000Z", "2.0.0": "2024-05-01T10:01:00.000Z", "1.0.2": "2024-05-01T10:02:00.000Z"}
    mk = lambda pub, scripts=None, deps=None: {"_npmUser": {"name": pub}, "scripts": scripts or {}, "dependencies": deps or {}, "maintainers": [{"name": pub}]}
    return {"time": t, "dist-tags": {"latest": "2.0.0"}, "versions": {
        "1.0.0": mk("alice"), "1.0.1": mk("alice"), "1.1.0": mk("alice"), "2.0.0": mk("alice", {"preinstall": "node x.js"}), "1.0.2": mk("alice")}}  # 0.9.0 was removed


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.rel, self.dep = live.rows("demo", packument())

    def test_rows_sorted_and_removed_version_keeps_only_time(self):
        self.assertEqual([r["version"] for r in self.rel][:3], ["0.9.0", "1.0.0", "1.0.1"])
        gone = self.rel[0]
        self.assertEqual((gone["publisher"], gone["removed"], gone["install_scripts"]), ("", 1, ""))

    def test_install_hooks_and_maintainers_extracted(self):
        v2 = next(r for r in self.rel if r["version"] == "2.0.0")
        self.assertEqual(v2["install_scripts"], "preinstall")
        self.assertEqual(v2["maintainers"], {"alice"})

    def test_burst_and_install_script_fire_with_facts(self):
        as_of = datetime(2024, 5, 1, 11, 0)
        hits = indicators.recent(indicators.compute(self.rel, self.dep, dep_ages={}), self.rel, as_of, 30)
        kinds = {h["indicator"] for h in hits}
        self.assertIn("release_burst", kinds); self.assertIn("install_script_added", kinds)
        burst = next(h for h in hits if h["indicator"] == "release_burst")
        self.assertEqual(burst["facts"]["release_lines_in_burst"], 3)

    def test_old_cutoff_sees_nothing(self):
        as_of = datetime(2020, 3, 1)
        rel = [r for r in self.rel if r["t"] <= as_of]
        self.assertEqual(indicators.recent(indicators.compute(rel, [], dep_ages={}), rel, as_of, 30), [])

    def test_bad_names_never_reach_the_network(self):
        for bad in ("../etc/passwd", "a b", "UPPER", "x;y", ""):
            with self.assertRaises(live.LiveError): live._get(bad)


if __name__ == "__main__":
    unittest.main()
