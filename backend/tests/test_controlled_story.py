import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


IDENTITY = '00000000-0000-0000-0000-000000000001'


def template(story_id=IDENTITY):
    from app.story_content import load_blueprint_template
    return load_blueprint_template(story_id,'draft-1','古代河运','ancient')


def content_data(story):
    data = story.model_dump(mode='json') if hasattr(story,'model_dump') else story
    fields = {'characters':('name','goal','taboos','appearance'),
              'locations':('name','description'),'objects':('name','description'),
              'evidence':('description',),'endings':('title','consequence')}
    result = {key:data[key] for key in ('story_id','story_version','setting','era','title','public_intro','truth')}
    result.update(schema_version='investigation-content-1',blueprint_version='controlled-investigation-1')
    for group,names in fields.items():
        result[group] = {item['id']:{name:item[name] for name in names} for item in data[group]}
    for group,source,field in [('disclosures','disclosures','public_text'),('commitments','commitments','public_text'),
                               ('action_feedback','action_rules','feedback'),('event_feedback','events','feedback')]:
        result[group] = {item['id']:item[field] for item in data[source]}
    return result


def test_blueprint_has_frozen_reachable_structure():
    from app.story_validation import check_reachability
    story = template()
    assert (len(story.characters),len(story.locations),len(story.endings)) == (3,5,3)
    proof = check_reachability(story)
    assert proof.status == 'passed'
    assert proof.states_checked == 70
    assert sorted(map(len,proof.ending_paths.values())) == [21,21,21]


def test_every_reference_and_topic_is_scoped_to_its_story():
    first = template().model_dump(mode='json')
    second = template('00000000-0000-0000-0000-000000000002').model_dump(mode='json')
    def ids(value):
        if isinstance(value,dict):
            return [v for k,v in value.items() if k=='id' or k.endswith('_id')] + [i for k,v in value.items()
                    for i in (v if k.endswith('_ids') else ids(v))] + (list(value['facts']) if 'facts' in value else [])
        return [i for v in value for i in ids(v)] if isinstance(value,list) else []
    a,b = set(ids(first))-{first['story_id']},set(ids(second))-{second['story_id']}
    assert not a.intersection(b)
    assert all(i.startswith('i_00000000000000000000000000000001_') and len(i)<=64 for i in a)
    assert template().model_dump() == template().model_dump()


@pytest.mark.parametrize('identity',['bad','00000000-0000-0000-0000-00000000000A'])
def test_noncanonical_story_identity_rejected(identity):
    with pytest.raises(ValueError):
        template(identity)


@pytest.mark.parametrize('mutation',['missing','rules','nested_conditions','long_id','wrong_type','version'])
def test_content_protocol_rejects_untrusted_fields(mutation):
    from app.story_content import parse_story_content
    data = content_data(template())
    if mutation=='missing':
        del data['truth']
    elif mutation=='rules':
        data['action_rules'] = []
    elif mutation=='nested_conditions':
        next(iter(data['endings'].values()))['conditions'] = {'all':[]}
    elif mutation=='long_id':
        data['evidence']['a'*65] = {'description':'bad'}
    elif mutation=='wrong_type':
        next(iter(data['characters'].values()))['taboos'] = 'not a list'
    else:
        data['blueprint_version'] = 'controlled-investigation-999'
    with pytest.raises(ValueError):
        parse_story_content(json.dumps(data,ensure_ascii=False))


def test_duplicate_json_keys_rejected_before_tool_output_normalization():
    from app.story_content import ControlledStoryContent,parse_story_content
    raw = json.dumps(content_data(template()),ensure_ascii=False)
    raw = raw[:-1]+',"title":"silently overwritten"}'
    for parse in (parse_story_content,ControlledStoryContent.model_validate_json):
        with pytest.raises(ValueError,match='duplicate_content_key'):
            parse(raw)


@pytest.mark.parametrize('mutation',['hash','version','extra','duplicate_id'])
def test_changed_or_unknown_blueprint_is_not_loaded(tmp_path,mutation):
    import app.story_content as module
    data = json.loads(module.BLUEPRINT_PATH.read_bytes())
    if mutation=='version':
        data['blueprint_version'] = 'unknown'
    elif mutation=='extra':
        data['plugin'] = 'execute me'
    elif mutation=='duplicate_id':
        data['template']['characters'][1]['id'] = data['template']['characters'][0]['id']
    file = tmp_path/'blueprint.json'
    file.write_text(json.dumps(data),encoding='utf-8')
    digest = module.BLUEPRINT_SHA256 if mutation=='hash' else hashlib.sha256(file.read_bytes()).hexdigest()
    with patch.object(module,'BLUEPRINT_PATH',file),patch.object(module,'BLUEPRINT_SHA256',digest):
        with pytest.raises(ValueError):
            template()
