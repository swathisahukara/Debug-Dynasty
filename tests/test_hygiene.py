"""Submission hygiene: no secrets in the tracked template, and .env is never tracked."""
import subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAFE_DEFAULTS = {"SAMPLE_MODE", "METERLESS_APP"}  # the only keys allowed to carry a value in the template


class HygieneTests(unittest.TestCase):
    def test_env_example_has_no_values_for_secrets(self):
        for line in (ROOT / ".env.example").read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in SAFE_DEFAULTS:
                    self.assertEqual(v.strip(), "", f".env.example must not hold a value for {k.strip()} (put real values in .env)")

    def test_env_file_is_not_tracked(self):
        out = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:  # skipped when run outside a git checkout
            self.assertEqual(out.stdout.strip(), "")


    def test_recorded_traces_are_complete_and_carry_no_secrets(self):
        import json
        files = sorted((ROOT / "data/public/recorded").glob("*.json"))
        self.assertTrue(files, "no recorded agent runs committed")
        for f in files:
            text = f.read_text(); rec = json.loads(text)
            self.assertEqual(rec["events"][-1]["type"], "result", f.name)
            self.assertGreater(rec["calls"], 0, f.name)
            for needle in ("Bearer", "api_key", "nvapi-", "sk-"):
                self.assertNotIn(needle, text, f"{f.name} must not contain {needle}")


if __name__ == "__main__":
    unittest.main()
