"""Player options are fixed by the server, not proposed by a model."""
from uuid import uuid4
from app.execution import ToolFailure,execute
from app.investigation import public_projection
from app.operation_schemas import validate_semantic_report

from app.investigation import available_actions
from app.state import apply_state_changes


def build_public_options(story,state):
    options,mapping = [],{}
    topics = {}
    for action in available_actions(story,state):
        decision = apply_state_changes(state,story=story,action=action)
        if decision.status != 'accepted':
            continue
        kind = action['type']
        if kind == 'investigate':
            label = '调查' + next(o.name for o in story.objects if o.id == action['object_id'])
        elif kind == 'move':
            label = '前往' + next(l.name for l in story.locations if l.id == action['location_id'])
        elif kind == 'decide':
            label = next(e.title for e in story.endings if e.id == action['ending_id'])
        else:
            character = next(c.name for c in story.characters if c.id == action['character_id'])
            if kind == 'talk':
                topics[character] = topics.get(character,0)+1
                label = f'与{character}交流（话题{topics[character]}）'
            else:
                evidence = next(e.description for e in story.evidence if e.id == action['evidence_id'])
                label = f'向{character}出示：{evidence[:60]}'
        key = str(uuid4())
        options.append({'id':key,'label':label})
        mapping[key] = action
    return options,mapping


class GenerationError(ValueError):
    pass


async def interpret_action(story,state,mapping,action,recent_turns,registry,context):
    if action.type == 'option':
        if action.value not in mapping:
            raise GenerationError('invalid_option')
        return mapping[action.value]
    result = await execute(registry,'action.interpret','v1',
                           {'public_world':public_projection(story,state),'text':action.value,
                            'available_actions':list(mapping.values()),'recent_turns':recent_turns},context)
    if isinstance(result,ToolFailure):
        raise GenerationError(result.error_code)
    if result.output.result.status == 'unrecognized':
        return None
    return result.output.result.action.model_dump()


async def render_investigation_scene(story,state,action,feedback,recent_turns,registry,context):
    public_world = public_projection(story,state)
    rendered = await execute(registry,'scene.render','v1',
                             {'public_world':public_world,'action':action,'adjudication_feedback':feedback,
                              'recent_turns':recent_turns},context)
    if isinstance(rendered,ToolFailure):
        raise GenerationError(rendered.error_code)
    candidate = rendered.output
    speakers = {c['id'] for c in public_world['characters']} - {story.protagonist_id}
    ids = [line.character_id for line in candidate.dialogue]
    if not set(ids).issubset(speakers) or len(ids) != len(set(ids)):
        raise GenerationError('invalid_scene_speaker')
    checked = await execute(registry,'scene.semantic_check','v1',
                            {'story':story.model_dump(),'public_world':public_world,
                             'adjudication_feedback':feedback,'candidate':candidate.model_dump()},context)
    if isinstance(checked,ToolFailure):
        raise GenerationError(checked.error_code)
    try:
        report = validate_semantic_report(checked.output,story)
    except ValueError as error:
        raise GenerationError('invalid_semantic_reference') from error
    context.recorder.event(context.task,'scene_semantic_result',report.model_dump())
    if not report.passed:
        raise GenerationError('scene_semantic_rejected')
    return candidate.model_dump()
