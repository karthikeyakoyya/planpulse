"""Two-week demo: week 1 run, simulated owner updates, week 2 run, meeting import.

Week 2 keeps demand and master data and redraws the operational state (stock, POs, supply plan).
This is a simple way to exercise carry-forward, auto-resolution, overdue flags and escalation.
It does not model real week-over-week change. The exception summary is left PENDING: only a person approves it.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planpulse import actions as A
from planpulse import cli, config as C, pipeline, simulate

for p in (C.DATA_RAW, C.DB_PATH):
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)

simulate.simulate(as_of="2026-10-19", ops_offset=0)
cli.run_week("2026-10-19")

con = pipeline.connect()
df = A.load_actions(con)
for a in df[df.severity == "P1"].action_id[:4]:
    A.update_action(con, a, "In Progress", "Owner contacted supplier (simulated update)", "2026-10-22", "2026-10-22")
for a in df[df.exc_type == "DATA_QUALITY"].action_id[:5]:
    A.update_action(con, a, "Closed", "Extract fixed upstream (simulated update)", "2026-10-23", "2026-10-23")
con.close()

simulate.simulate(as_of="2026-10-26", ops_offset=1)
con = pipeline.connect()
n = A.import_meeting(con, C.ROOT / "docs" / "meeting_notes" / "2026-10-26_example.md", "2026-10-26", "2026-10-26")
print(f"imported {n} meeting actions")
con.close()
cli.run_week("2026-10-26")
