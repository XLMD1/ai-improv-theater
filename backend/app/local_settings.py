from typing import Literal

from pydantic import SecretStr


Provider = Literal["openai", "deepseek"]
MODELS: dict[str, str] = {"openai": "gpt-6-luna", "deepseek": "deepseek-flash"}
_keys: dict[str, SecretStr] = {}


def configured(provider: Provider) -> bool:
    return provider in _keys


def get_key(provider: Provider) -> str | None:
    key = _keys.get(provider)
    return key.get_secret_value() if key else None


def put_key(provider: Provider, key: SecretStr) -> None:
    _keys[provider] = key


def clear_key(provider: Provider) -> None:
    _keys.pop(provider, None)


def public_status() -> dict:
    return {"providers": {
        provider: {"model_id": model_id, "configured": configured(provider), "available": provider == "deepseek"}
        for provider, model_id in MODELS.items()
    }}
