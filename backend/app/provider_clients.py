"""The only boundary that sends prompts and API keys to model providers."""

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import httpx


class ProviderFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResult:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ProviderOutcome:
    text: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None
    request_sent: bool = False
    retry_after: float | None = None
    chargeable: bool = True


async def call_operation_provider(provider, model_id, api_key, prompt, max_tokens, timeout_seconds):
    if provider != 'deepseek' or not api_key:
        return ProviderOutcome(error_code='configuration_error', chargeable=False)
    payload = {'model': model_id, 'messages': [{'role': 'user', 'content': prompt}],
               'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}, 'max_tokens': max_tokens}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post('https://api.deepseek.com/chat/completions',
                                         headers={'Authorization': f'Bearer {api_key}'}, json=payload)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return ProviderOutcome(error_code='connect_failure', chargeable=False)
    except httpx.HTTPError:
        return ProviderOutcome(error_code='outcome_unknown', request_sent=True)
    if response.status_code in (401, 403):
        return ProviderOutcome(error_code='unauthorized', request_sent=True, chargeable=False)
    if response.status_code == 429:
        value = response.headers.get('Retry-After')
        delay = None
        if value:
            try:
                delay = max(0.0, float(value))
            except ValueError:
                try:
                    delay = max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        return ProviderOutcome(error_code='rate_limited', request_sent=True, retry_after=delay, chargeable=False)
    if response.status_code >= 500:
        return ProviderOutcome(error_code='outcome_unknown', request_sent=True)
    if response.status_code != 200:
        return ProviderOutcome(error_code='provider_rejected', request_sent=True, chargeable=False)
    input_tokens = output_tokens = None
    try:
        data = response.json()
        usage = data.get('usage', {})
        inp, out = usage.get('prompt_tokens'), usage.get('completion_tokens')
        if type(inp) is int and inp >= 0 and type(out) is int and out >= 0:
            input_tokens, output_tokens = inp, out
        content = data['choices'][0]['message']['content']
        if not isinstance(content, str) or input_tokens is None:
            raise ValueError('invalid_envelope')
        if data['choices'][0].get('finish_reason') == 'length':
            return ProviderOutcome(content, input_tokens, output_tokens, 'output_truncated', True)
        return ProviderOutcome(content, input_tokens, output_tokens, request_sent=True)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return ProviderOutcome(input_tokens=input_tokens, output_tokens=output_tokens,
                               error_code='invalid_envelope', request_sent=True)


async def call_provider(provider: str, model_id: str, api_key: str, prompt: str) -> ModelResult:
    if provider == "deepseek":
        url = "https://api.deepseek.com/chat/completions"
        payload = {
            "model": model_id, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}, "max_tokens": 900,
        }
    else:
        raise ProviderFailure("unsupported provider")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ProviderFailure("model request failed") from error

    try:
        usage = data["usage"]
        input_tokens = usage["prompt_tokens"]
        output_tokens = usage["completion_tokens"]
        if type(input_tokens) is not int or input_tokens <= 0 or type(output_tokens) is not int or output_tokens < 0:
            raise ProviderFailure("invalid model usage")
        text = data["choices"][0]["message"].get("content") or ""
        return ModelResult(text, input_tokens, output_tokens)
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ProviderFailure("invalid model response envelope") from error
