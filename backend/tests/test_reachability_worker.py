import asyncio
import importlib.util
import time
from unittest.mock import patch

import pytest
from app.story_schema import Story
from app.story_validation import check_reachability
from test_investigation_schema import sample_data


@pytest.mark.asyncio
async def test_worker_matches_frozen_paths():
    assert importlib.util.find_spec('app.reachability_worker'), 'bounded worker missing'
    from app.reachability_worker import validate_reachability
    story = Story.model_validate(sample_data())
    result = await validate_reachability(story,time.monotonic()+10)
    assert result == check_reachability(story)


@pytest.mark.asyncio
async def test_worker_timeout_exits_process():
    assert importlib.util.find_spec('app.reachability_worker'), 'bounded worker missing'
    from app.reachability_worker import validate_reachability
    original = asyncio.create_subprocess_exec
    processes = []
    async def capture(*args,**kwargs):
        child = await original(*args,**kwargs)
        processes.append(child)
        return child
    with patch('asyncio.create_subprocess_exec',side_effect=capture):
        with pytest.raises(TimeoutError):
            await validate_reachability(Story.model_validate(sample_data()),time.monotonic()+.01)
    assert processes and all(child.returncode is not None for child in processes)
