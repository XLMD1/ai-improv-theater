import importlib.util
from uuid import UUID
from app.investigation import initial_investigation_state
from app.story_schema import Story
from app.state import apply_state_changes
from test_investigation_schema import sample_data


def test_public_options_are_opaque_and_do_not_mutate_parent():
    assert importlib.util.find_spec('app.investigation_generation'), 'public options missing'
    from app.investigation_generation import build_public_options
    story = Story.model_validate(sample_data())
    state = initial_investigation_state(story)
    options,mapping = build_public_options(story,state)
    assert options and len(options) == len(mapping)
    assert state == initial_investigation_state(story)
    for item in options:
        assert str(UUID(item['id'])) == item['id']
        assert set(item) == {'id','label'}
        assert apply_state_changes(state,story=story,action=mapping[item['id']]).status == 'accepted'
        assert mapping[item['id']]['type'] != 'decide'
