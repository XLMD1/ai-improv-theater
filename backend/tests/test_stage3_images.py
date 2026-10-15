import io
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from PIL import Image


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,chargeable',[(401,'unauthorized',False),(429,'rate_limited',False),(500,'outcome_unknown',True)])
async def test_image_provider_classifies_without_blind_retry(status,code,chargeable):
    from app.image_operations import call_image_provider, ImageGenerateInput
    value = ImageGenerateInput(prompt='公开场景',size='1344x768')
    with patch('httpx.AsyncClient.post',return_value=httpx.Response(status)):
        result = await call_image_provider(value,'fixture-key',20)
    assert result.error_code == code and result.chargeable == chargeable


@pytest.mark.asyncio
async def test_malformed_accepted_response_keeps_known_per_request_charge():
    from app.image_operations import call_image_provider, ImageGenerateInput
    with patch('httpx.AsyncClient.post',return_value=httpx.Response(200,json={'data':[]})):
        result = await call_image_provider(ImageGenerateInput(prompt='公开场景',size='1344x768'),'fixture-key',20)
    assert result.error_code == 'invalid_envelope' and result.image_count == 1


def test_download_url_disallows_private_hosts_credentials_and_wrong_provider():
    from app.image_operations import ImageDownloadInput
    for url in ['http://127.0.0.1/picture','https://evil.example/image','https://user:password@aigc-files.bigmodel.cn/image']:
        with pytest.raises(ValueError):
            ImageDownloadInput(url=url,asset_id=str(uuid4()),story_version_id=str(uuid4()),size='1344x768')


def test_saved_images_validate_dimensions_and_are_immutable(tmp_path):
    from app.image_operations import ImageDownloadInput, persist_image
    value = ImageDownloadInput(url='https://aigc-files.bigmodel.cn/image.png',asset_id=str(uuid4()),story_version_id=str(uuid4()),size='1344x768')
    blob=io.BytesIO(); Image.new('RGB',(1344,768),'teal').save(blob,format='PNG')
    first = persist_image(blob.getvalue(),value,tmp_path)
    second = persist_image(blob.getvalue(),value,tmp_path)
    assert first == second and (tmp_path/first.path).exists()
    wrong=io.BytesIO(); Image.new('RGB',(20,20)).save(wrong,format='PNG')
    with pytest.raises(ValueError,match='image_dimensions'):
        persist_image(wrong.getvalue(),value,tmp_path)


def test_observed_provider_cdn_is_exactly_allowed_without_wildcard_storage_access():
    from app.image_operations import ImageProposal
    host='maas-watermark-prod-new.cn-wlcb.ufileos.com'
    assert ImageProposal(url='https://'+host+'/file.png').url.endswith('/file.png')
    for url in ['http://'+host+'/file','https://evil.cn-wlcb.ufileos.com/file','https://'+host+'.evil.example/file','https://user:pass@'+host+'/file']:
        with pytest.raises(ValueError): ImageProposal(url=url)
