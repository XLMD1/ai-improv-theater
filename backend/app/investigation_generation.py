"""Player options are fixed by the server, not proposed by a model."""
from uuid import uuid4

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
