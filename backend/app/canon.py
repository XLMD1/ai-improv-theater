import json
from functools import lru_cache
from pathlib import Path


@lru_cache
def get_canon() -> dict:
    return json.loads(Path(__file__).with_name("canon.json").read_text(encoding="utf-8"))


def initial_state() -> dict:
    return {
        "schema_version": 1,
        "scene_id": "s1",
        "turn": 0,
        "flags": {},
        "relations": {"c1:c2": 0, "c1:c3": 0, "c2:c3": 0},
        "ending_id": None,
    }
