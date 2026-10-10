"""Local read-only debug inspection. Output may include private story facts."""
import argparse
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'backend'))
from evals.run_stage2 import inspect_trace
from app.db import SessionLocal

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--session-id',required=True)
parser.add_argument('--trace-id',required=True)
args = parser.parse_args()
try:
    print(json.dumps(inspect_trace(SessionLocal,args.session_id,args.trace_id),ensure_ascii=False,indent=2))
except ValueError:
    print('trace_not_found')
    raise SystemExit(1)
