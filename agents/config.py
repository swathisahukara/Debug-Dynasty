import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


load_env()
SAMPLE_MODE = os.environ.get("SAMPLE_MODE", "0") == "1"
LLM_MOCK = os.environ.get("LLM_MOCK", "0") == "1"
DATA_SOURCE = os.environ.get("DATA_SOURCE", "csv" if SAMPLE_MODE else "zetaris")  # zetaris | csv
DATA_DIR = ROOT / os.environ.get("DATA_DIR", "data/sample" if SAMPLE_MODE else "data/build")  # DATA_DIR=data/public for the hosted demo
# Cost meter: Nightshift reports 0 USD on the free trial, so estimate from tokens (override in .env).
USD_PER_MTOK_IN = float(os.environ.get("USD_PER_MTOK_IN", "0.20"))
USD_PER_MTOK_OUT = float(os.environ.get("USD_PER_MTOK_OUT", "0.60"))
RECENT_DAYS = int(os.environ.get("RECENT_DAYS", "30"))  # only releases this recent can raise an indicator
