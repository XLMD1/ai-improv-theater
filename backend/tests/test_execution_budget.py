from decimal import Decimal
import pytest

from test_execution_records import records, cleanup_records, outcome


@pytest.fixture(autouse=True)
def clean():
    yield
    cleanup_records()


@pytest.mark.parametrize('cost,expected', [('80','warning'),('100','blocked')])
def test_budget_thresholds(cost,expected):
    from app.costs import budget_status, check_execution_budget
    recorder, task, factory = records()
    attempt = recorder.begin_attempt(task,'test','v1',1,{})
    data = outcome()
    data['estimated_cost_cny'] = cost
    recorder.finish_attempt(attempt,data,None)
    with factory() as db:
        assert budget_status(db)['status'] == expected
        if expected == 'blocked':
            with pytest.raises(ValueError, match='budget_exhausted'):
                check_execution_budget(db)


def test_estimated_next_call_cannot_cross_limit():
    from app.costs import check_execution_budget
    _, _, factory = records()
    with factory() as db:
        with pytest.raises(ValueError, match='budget_exhausted'):
            check_execution_budget(db, estimated_cost=Decimal('100'))


def test_unknown_usage_blocks_next_call():
    from app.costs import check_execution_budget
    recorder, task, factory = records()
    attempt = recorder.begin_attempt(task,'test','v1',1,{})
    data = outcome()
    data.update(input_tokens=None,output_tokens=None,estimated_cost_cny=None)
    recorder.finish_attempt(attempt,data,'outcome_unknown')
    with factory() as db:
        with pytest.raises(ValueError,match='cost_unconfirmed'):
            check_execution_budget(db)


def test_unfinished_audit_blocks_next_call():
    from app.costs import check_execution_budget
    recorder, task, factory = records()
    recorder.begin_attempt(task,'test','v1',1,{})
    with factory() as db:
        with pytest.raises(ValueError,match='audit_incomplete'):
            check_execution_budget(db)
