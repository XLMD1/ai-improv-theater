import importlib.util
from unittest.mock import patch

import httpx
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code',[(401,'unauthorized'),(403,'unauthorized'),(429,'rate_limited'),(500,'outcome_unknown')])
async def test_provider_classifies_status(status, code):
    import app.provider_clients as providers
    assert hasattr(providers,'call_operation_provider'), 'operation provider is missing'
    response = httpx.Response(status, headers={'Retry-After':'2'},request=httpx.Request('POST','https://api.deepseek.com/chat/completions'))
    with patch('httpx.AsyncClient.post',return_value=response):
        result = await providers.call_operation_provider('deepseek','deepseek-flash','test-key','prompt',300,20)
    assert result.error_code == code
    if status == 429:
        assert result.retry_after == 2 and not result.chargeable


@pytest.mark.asyncio
async def test_provider_extracts_usage_before_candidate_json_validation():
    import app.provider_clients as providers
    assert hasattr(providers,'call_operation_provider'), 'operation provider is missing'
    response = httpx.Response(200,json={'choices':[{'message':{'content':'malformed'}}],
                                      'usage':{'prompt_tokens':12,'completion_tokens':8}})
    with patch('httpx.AsyncClient.post',return_value=response):
        result = await providers.call_operation_provider('deepseek','deepseek-flash','test-key','prompt',300,20)
    assert result.input_tokens == 12 and result.text == 'malformed'
