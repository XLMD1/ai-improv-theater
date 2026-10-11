"""Bound deterministic search in a killable process, never in the event loop."""
import asyncio
import json
from pathlib import Path
import sys
import time

from app.story_schema import Story
from app.story_validation import ReachabilityReport, check_reachability


async def validate_reachability(story,deadline):
    if deadline <= time.monotonic():
        raise TimeoutError('rule_check_timeout')
    process = await asyncio.create_subprocess_exec(sys.executable,'-m','app.reachability_worker',
                cwd=str(Path(__file__).resolve().parent.parent),stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    try:
        async with asyncio.timeout(max(0,deadline-time.monotonic())):
            stdout,_ = await process.communicate(story.model_dump_json().encode('utf-8'))
        if process.returncode != 0:
            raise ValueError('rule_check_failure')
        return ReachabilityReport.model_validate_json(stdout)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__ == '__main__':
    try:
        story = Story.model_validate_json(sys.stdin.buffer.read(256_001))
        result = check_reachability(story,max_states=50_000)
        sys.stdout.buffer.write(result.model_dump_json().encode('utf-8'))
    except Exception:
        sys.exit(2)
