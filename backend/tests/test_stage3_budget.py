from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from test_execution_records import records, cleanup_records, outcome


@pytest.fixture(autouse=True)
def clean():
    yield
    cleanup_records()


def reservation(cost):
    return dict(estimate=str(cost), provider='deepseek', model_id='deepseek-flash', price_version='test')


def test_atomic_parallel_reservations_cannot_cross_limit():
    first, a, factory = records()
    second, b, _ = records()
    def reserve(item):
        recorder, task = item
        try:
            recorder.begin_attempt(task, 'test', 'v1', 1, {}, reservation(60))
            return 'reserved'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, [(first, a), (second, b)]))
    assert sorted(results) == ['budget_exhausted', 'reserved']
    from app.costs import budget_status
    with factory() as db:
        assert budget_status(db)['reserved_cny'] == 60


def test_settlement_releases_reservation_but_counts_incurred_usage():
    recorder, task, factory = records()
    from app.costs import budget_status
    with factory() as db:
        before = budget_status(db)['estimated_spend_cny']
    attempt = recorder.begin_attempt(task, 'test', 'v1', 1, {}, reservation(2))
    recorder.finish_attempt(attempt, {**outcome(), 'estimated_cost_cny':'0.4'}, None)
    from app.costs import budget_status
    with factory() as db:
        status = budget_status(db)
        assert status['reserved_cny'] == 0
        assert status['estimated_spend_cny'] == pytest.approx(before + .4)


def test_unknown_charge_preserves_reservation_and_stops_new_call():
    recorder, task, factory = records()
    attempt = recorder.begin_attempt(task, 'test', 'v1', 1, {}, reservation(2))
    recorder.finish_attempt(attempt, {**outcome(), 'input_tokens':None, 'output_tokens':None,
                            'estimated_cost_cny':None}, 'outcome_unknown')
    from app.costs import budget_status, check_execution_budget
    with factory() as db:
        assert budget_status(db)['reserved_cny'] == 2
        with pytest.raises(ValueError, match='cost_unconfirmed'):
            check_execution_budget(db, Decimal('.06'))


def test_unreserved_legacy_unknown_usage_is_also_visible_in_budget_status():
    recorder,task,factory=records()
    attempt=recorder.begin_attempt(task,'test','v1',1,{})
    recorder.finish_attempt(attempt,{**outcome(),'input_tokens':None,'output_tokens':None,'estimated_cost_cny':None},'outcome_unknown')
    from app.costs import budget_status
    with factory() as db:
        assert budget_status(db)['cost_unconfirmed']


def test_non_chargeable_failure_releases_full_reservation():
    recorder, task, factory = records()
    from app.costs import budget_status
    with factory() as db:
        before = budget_status(db)['estimated_spend_cny']
    attempt = recorder.begin_attempt(task, 'test', 'v1', 1, {}, reservation(2))
    recorder.finish_attempt(attempt, {**outcome(), 'chargeable':False}, 'unauthorized')
    from app.costs import budget_status
    with factory() as db:
        assert budget_status(db)['reserved_cny'] == 0
        assert budget_status(db)['estimated_spend_cny'] == before


def test_legacy_provider_request_has_shared_reservation_before_it_is_sent():
    import json
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.models import CostReservation
    from app.provider_clients import ModelResult
    from sqlalchemy import select
    from test_stage3_context import _turn
    async def provider(_provider,_model,_key,prompt):
        with SessionLocal() as db:
            assert db.scalar(select(CostReservation).where(CostReservation.status == 'reserved')) is not None
        context=json.loads(prompt.split('背景资料：',1)[1])
        return ModelResult(json.dumps({'narration':'保留旧叙事路径','dialogue':[
            {'character_id':person,'text':'继续调查','emotion':'neutral'} for person in context['allowed_speakers']],
            'state_changes':[]}),100,50)
    with TestClient(app) as c:
        c.put('/local-settings/keys/deepseek',json={'api_key':'legacy-fixture-key'})
        created=c.post('/sessions',json={'provider':'deepseek'}).json()
        try:
            with patch('app.generation.call_provider',side_effect=provider):
                _turn(c,created['token'],created['root'],'search')
        finally:
            c.delete('/local-settings/keys/deepseek')


@pytest.mark.asyncio
async def test_legacy_authentication_rejection_does_not_create_an_unknown_charge():
    import httpx
    from unittest.mock import patch
    from test_execution import setup
    from app.generation import registered_legacy_call
    from app.provider_clients import ProviderFailure
    _,context=setup(lambda *args: None)
    response=httpx.Response(401,request=httpx.Request('POST','https://api.deepseek.com/chat/completions'))
    with patch('httpx.AsyncClient.post',return_value=response),pytest.raises(ProviderFailure):
        await registered_legacy_call('prompt','deepseek','deepseek-flash','fixture-key',context)
    assert not context.recorder.results[0][1]['chargeable']


def test_restart_of_a_free_download_does_not_invent_an_unknown_model_bill():
    recorder,task,factory=records()
    recorder.begin_attempt(task,'image.download','v1',1,{},dict(reservation(0),chargeable=False))
    from app.execution_traces import interrupt_reservations
    from app.costs import budget_status
    interrupt_reservations(factory)
    with factory() as db:
        assert not budget_status(db)['cost_unconfirmed']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['timeout','cancelled','exception'])
async def test_free_download_outer_failure_is_not_billable(failure):
    import asyncio
    from dataclasses import replace
    from test_execution import setup
    from app.execution import execute
    async def handler(*args):
        if failure=='timeout': await asyncio.sleep(1)
        if failure=='cancelled': raise asyncio.CancelledError()
        raise RuntimeError('download failed')
    registry,context=setup(handler)
    registry.specs[('test','v1')]=replace(registry.specs[('test','v1')],chargeable=False,timeout_seconds=.001)
    if failure=='cancelled':
        with pytest.raises(asyncio.CancelledError): await execute(registry,'test','v1',{'value':1},context)
    else:
        await execute(registry,'test','v1',{'value':1},context)
    assert context.recorder.results[0][1]['chargeable'] is False


@pytest.mark.asyncio
async def test_read_only_timeout_retries_safely_without_model_charges():
    import asyncio
    from dataclasses import replace
    from test_execution import setup
    from app.execution import execute,ToolSuccess
    from app.provider_clients import ProviderOutcome
    attempts=[]
    async def handler(*args):
        attempts.append(1)
        if len(attempts)<3: await asyncio.sleep(1)
        return ProviderOutcome(text='{"value":1}',request_sent=True)
    async def no_wait(*args): pass
    registry,context=setup(handler,sleep=no_wait,jitter=lambda:0)
    registry.specs[('test','v1')]=replace(registry.specs[('test','v1')],chargeable=False,side_effect_policy='read_only',timeout_seconds=.001)
    result=await execute(registry,'test','v1',{'value':1},context)
    assert isinstance(result,ToolSuccess) and len(attempts)==3
    assert all(not item[1]['chargeable'] for item in context.recorder.results)
