
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from validate_r4 import FIXTURE_CODES, validate_fixture_signal
rows=[]
for fixture_id, expected in FIXTURE_CODES.items():
    actual=validate_fixture_signal(fixture_id)
    rows.append({"fixture_id":fixture_id,"expected_code":expected,"actual_code":actual,"status":"PASS" if actual==expected else "FAIL"})
out={"schema":"mephc.r4.negative_fixtures.v1","status":"PASS" if all(x["status"]=="PASS" for x in rows) else "FAIL","fixture_count":len(rows),"fixtures":rows,"created_at":datetime.now(timezone.utc).isoformat()}
(ROOT/"negative_fixture_results.json").write_text(json.dumps(out,indent=2)+"\n")
(ROOT/"logs"/"r4_negative_fixtures.log").write_text("\n".join(f"{x['fixture_id']} {x['status']} {x['actual_code']}" for x in rows)+"\n")
print("R4 negative fixtures",out["status"],out["fixture_count"])
if out["status"]!="PASS": raise SystemExit(1)
