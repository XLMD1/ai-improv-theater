"""Versioned CogView generation and bounded image retrieval through execute()."""
from decimal import Decimal
import hashlib
import io
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from typing import Annotated, Literal

import httpx
from PIL import Image
from pydantic import Field, field_validator
from app.config import get_settings
from app.execution import ToolSpec
from app.local_settings import get_key
from app.provider_clients import ProviderOutcome
from app.story_schema import StrictModel

IMAGE_PRICE_VERSION = 'cogview4-2026-10-14-cny'
IMAGE_PRICE_CNY = Decimal('.06')
IMAGE_PROMPT_VERSION = 'cinematic-public-2'
MAX_IMAGE_BYTES = 12 * 1024 * 1024
Size = Literal['1344x768', '768x1344']


def asset_root():
    return (get_settings().runtime_dir or Path(__file__).resolve().parents[2] / 'runtime') / 'generated-images'


def check_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443)
        or not (host=='maas-watermark-prod-new.cn-wlcb.ufileos.com'
                or any(host == domain or host.endswith('.'+domain) for domain in ('bigmodel.cn','zhipuai.cn')))):
        raise ValueError('image_url_not_allowed')
    return url


class ImageGenerateInput(StrictModel):
    model: Literal['cogview-4'] = 'cogview-4'
    quality: Literal['standard'] = 'standard'
    prompt: Annotated[str, Field(min_length=1,max_length=8000)]
    size: Size
    asset_id: Annotated[str | None, Field(pattern=r'^[0-9a-f-]{36}$')] = None


class ImageProposal(StrictModel):
    url: Annotated[str, Field(max_length=4000)]
    _url = field_validator('url')(check_url)


class ImageDownloadInput(ImageProposal):
    asset_id: Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]
    story_version_id: Annotated[str, Field(pattern=r'^[0-9a-f-]{36}$')]
    size: Size
    expected_sha256: Annotated[str | None, Field(pattern=r'^[a-f0-9]{64}$')] = None


class ImageFile(StrictModel):
    path: str
    sha256: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    width: int
    height: int


async def call_image_provider(value, key, timeout):
    if not key:
        return ProviderOutcome(error_code='key_not_configured',chargeable=False)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post('https://open.bigmodel.cn/api/paas/v4/images/generations',
                headers={'Authorization':f'Bearer {key}'},json={**value.model_dump(exclude={'asset_id'}),'watermark_enabled':True})
    except (httpx.ConnectError,httpx.ConnectTimeout):
        return ProviderOutcome(error_code='connect_failure',chargeable=False)
    except httpx.HTTPError:
        return ProviderOutcome(error_code='outcome_unknown',request_sent=True)
    if response.status_code in (401,403):
        return ProviderOutcome(error_code='unauthorized',request_sent=True,chargeable=False)
    if response.status_code == 429:
        try:
            delay = max(0,float(response.headers.get('Retry-After','0')))
        except ValueError:
            delay = 0
        return ProviderOutcome(error_code='rate_limited',request_sent=True,chargeable=False,retry_after=delay)
    if response.status_code >= 500:
        return ProviderOutcome(error_code='outcome_unknown',request_sent=True)
    if response.status_code != 200:
        return ProviderOutcome(error_code='provider_rejected',request_sent=True,chargeable=False)
    # Official billing is per accepted request, including invalid envelopes.
    try:
        data = response.json()['data']
        if not isinstance(data,list) or len(data) != 1 or not isinstance(data[0]['url'],str):
            raise ValueError('invalid_envelope')
        return ProviderOutcome(text=json.dumps({'url':data[0]['url']}),request_sent=True,image_count=1)
    except (ValueError,KeyError,IndexError,TypeError):
        return ProviderOutcome(error_code='invalid_envelope',request_sent=True,image_count=1)


def persist_image(blob,value,root):
    if len(blob) > MAX_IMAGE_BYTES:
        raise ValueError('image_too_large')
    with Image.open(io.BytesIO(blob)) as image:
        width,height = map(int,value.size.split('x'))
        if image.size != (width,height):
            raise ValueError('image_dimensions')
        if image.format not in ('PNG','JPEG','WEBP'):
            raise ValueError('image_format')
        image.load()
        encoded = io.BytesIO()
        image.convert('RGB').save(encoded,format='PNG')
    content = encoded.getvalue()
    relative = f'{value.story_version_id}/{value.asset_id}.png'
    destination = root / relative
    digest = hashlib.sha256(content).hexdigest()
    if value.expected_sha256 and digest!=value.expected_sha256:
        raise ValueError('asset_immutable')
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            if not value.expected_sha256: raise ValueError('asset_immutable')
    if not destination.exists() or hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
        destination.parent.mkdir(parents=True,exist_ok=True)
        temporary = destination.with_suffix('.part')
        temporary.write_bytes(content)
        temporary.replace(destination)
    return ImageFile(path=relative,sha256=digest,width=width,height=height)


async def download_image(value,context):
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
            async with client.stream('GET',value.url) as response:
                if response.status_code >= 500:
                    return ProviderOutcome(error_code='connect_failure',request_sent=True,chargeable=False)
                if response.status_code != 200:
                    return ProviderOutcome(error_code='download_rejected',request_sent=True,chargeable=False)
                blob=bytearray()
                async for chunk in response.aiter_bytes():
                    blob.extend(chunk)
                    if len(blob)>MAX_IMAGE_BYTES:
                        return ProviderOutcome(error_code='image_too_large',request_sent=True,chargeable=False)
        result = persist_image(bytes(blob),value,asset_root())
        return ProviderOutcome(text=result.model_dump_json(),request_sent=True,chargeable=False)
    except httpx.HTTPError:
        return ProviderOutcome(error_code='connect_failure',request_sent=True,chargeable=False)
    except (ValueError,OSError,Image.DecompressionBombError):
        return ProviderOutcome(error_code='invalid_image',request_sent=True,chargeable=False)


def register_image_operations(registry):
    async def generate(value,context):
        return await call_image_provider(value,get_key('cogview'),min(120,context.deadline-time.monotonic()))
    registry.register(ToolSpec('image.generate','v1',ImageGenerateInput,ImageProposal,generate,120,3,
        frozenset({'rate_limited','connect_failure'}),'non_idempotent_external',lambda _:IMAGE_PRICE_CNY))
    registry.register(ToolSpec('image.download','v1',ImageDownloadInput,ImageFile,download_image,20,3,
        frozenset({'connect_failure'}),'read_only',lambda _:Decimal(0),chargeable=False))
