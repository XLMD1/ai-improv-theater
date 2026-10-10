"""Local operator reconciliation for a dedicated evaluation database. No provider calls."""
import argparse
from decimal import Decimal
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'backend'))
from evals.run_stage1 import validate_database_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url-env',default='MIGRATION_DATABASE_URL')
    parser.add_argument('--session-id',required=True)
    parser.add_argument('--call-id',required=True)
    parser.add_argument('--source',choices=['user_reported_provider_console'],required=True)
    parser.add_argument('--actual-cost-cny',type=Decimal,required=True)
    parser.add_argument('--total-tokens',type=int,required=True)
    parser.add_argument('--input-tokens',type=int)
    parser.add_argument('--output-tokens',type=int)
    args = parser.parse_args()
    try:
        url = validate_database_url(os.environ.get(args.database_url_env,''))
    except ValueError:
        print('dedicated_test_database_required')
        return 2
    os.environ.update(DATABASE_URL=url.render_as_string(hide_password=False),
                      MIGRATION_DATABASE_URL=url.render_as_string(hide_password=False))
    from sqlalchemy.exc import SQLAlchemyError
    from app.db import SessionLocal
    from app.models import LLMCall
    from app.execution_traces import TaskRef, TraceRecorder, TraceStorageFailure
    try:
        with SessionLocal() as db:
            call = db.get(LLMCall,args.call_id)
            if call is None:
                raise ValueError('call_not_found')
            ref = TaskRef('action' if call.run_id else 'creation',call.run_id or call.creation_task_id,args.session_id)
        receipt = TraceRecorder(SessionLocal).reconcile_usage(ref,{
            'schema_version':'usage-reconciliation-1','call_id':args.call_id,'source':args.source,
            'actual_cost_cny':args.actual_cost_cny,'total_tokens':args.total_tokens,
            'input_tokens':args.input_tokens,'output_tokens':args.output_tokens})
    except (ValueError,SQLAlchemyError,TraceStorageFailure):
        print('reconciliation_rejected')
        return 2
    print(receipt.model_dump_json())
    return 0


if __name__=='__main__':
    raise SystemExit(main())
