"""Central settings. Everything tunable lives here and is echoed into the decision log."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "planpulse.duckdb"
OUT_DIR = ROOT / "outputs"
SQL_DIR = ROOT / "sql"

DEFAULT_AS_OF = "2026-10-26"  # a Monday; weeks start on Monday

MARKETS = {
    # code, SKU count, lead time range (days), demand volatility, supplier count
    "APAC": dict(code="AP", skus=45, lt=(14, 35), vol=0.18, suppliers=6),
    "India": dict(code="IN", skus=40, lt=(10, 30), vol=0.22, suppliers=5),
    "MENA-PAK": dict(code="MP", skus=35, lt=(25, 60), vol=0.28, suppliers=5),
    "South Africa": dict(code="ZA", skus=30, lt=(30, 70), vol=0.25, suppliers=4),
}

# Thresholds (see docs/decision_log.md)
HORIZON_WEEKS = 8
ACCURACY_WEEKS = 8
OTIF_WEEKS = 26
OTIF_IN_FULL_TOLERANCE = 0.98       # received >= 98% of ordered counts as in full
EXCESS_COVER_DAYS = 120
BIAS_THRESHOLD = 0.20               # |bias| above 20% over the last 8 weeks
BIAS_MIN_UNITS = 200                # ignore tiny SKUs for bias exceptions
LATE_PO_P1_DAYS = 14
DIVERGENCE_THRESHOLD = 0.35
ANOMALY_CONTAMINATION = 0.05
SLA_DAYS = {"P1": 2, "P2": 5, "P3": 10}
FRESHNESS_MAX_DAYS = 3
