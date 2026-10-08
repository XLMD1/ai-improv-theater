"""The only boundary that sends prompts and API keys to model providers."""

from dataclasses import dataclass

import httpx


class ProviderFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResult:
    text: str
    input_tokens: int
    output_tokens: int


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
