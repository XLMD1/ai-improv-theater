"""Exhaustive finite-state reachability using the same server update entry."""
from collections import deque
from typing import Literal

from app.investigation import available_actions, initial_investigation_state
from app.state import StoryValidationError, apply_state_changes
from app.story_schema import Story, StrictModel


class ReachabilityReport(StrictModel):
    status: Literal["passed", "unreachable", "invalid_rules", "reachability_inconclusive"]
    states_checked: int
    locations: list[str]
    evidence: list[str]
    ending_paths: dict[str, list[dict]]
    missing_locations: list[str]
    missing_evidence: list[str]
    missing_endings: list[str]
    error_code: str | None = None


def state_key(state: dict) -> tuple:
    return (state["location_id"], tuple(state["discovered_evidence"]), tuple(state["disclosures"]),
            tuple(state["commitments"]), tuple(sorted(state["trust"].items())),
            tuple(state["applied_once_rules"]), tuple(state["fired_events"]), state["ending_id"])


def check_reachability(story: Story, max_states: int = 50_000) -> ReachabilityReport:
    if type(max_states) is not int or max_states < 1:
        raise ValueError("max_states must be a positive integer")
    story = Story.model_validate(story.model_dump())
    initial = initial_investigation_state(story)
    key = state_key(initial)
    queue = deque([initial])
    # predecessor links avoid copying a whole witness for every queued state
    predecessors = {key: None}
    locations, evidence, paths = set(), set(), {}

    def path(target):
        actions = []
        while predecessors[target] is not None:
            target, action = predecessors[target]
            actions.append(action)
        return list(reversed(actions))

    def report(status, error=None):
        return ReachabilityReport(
            status=status, states_checked=len(predecessors),
            locations=sorted(locations), evidence=sorted(evidence), ending_paths=paths,
            missing_locations=sorted({l.id for l in story.locations} - locations),
            missing_evidence=sorted({e.id for e in story.evidence} - evidence),
            missing_endings=sorted({e.id for e in story.endings} - paths.keys()), error_code=error,
        )

    while queue:
        state = queue.popleft()
        locations.add(state["location_id"])
        evidence.update(state["discovered_evidence"])
        current_key = state_key(state)
        if state["ending_id"]:
            paths.setdefault(state["ending_id"], path(current_key))
            continue
        for action in available_actions(story, state):
            try:
                result = apply_state_changes(state, story=story, action=action)
            except StoryValidationError as exc:
                return report("invalid_rules", str(exc))
            if result.status != "accepted":
                continue
            successor_key = state_key(result.state)
            if successor_key in predecessors:
                continue
            if len(predecessors) >= max_states:
                return report("reachability_inconclusive", "state_limit")
            predecessors[successor_key] = (current_key, action)
            queue.append(result.state)
    result = report("passed")
    if result.missing_locations or result.missing_evidence or result.missing_endings:
        return report("unreachable")
    return result
