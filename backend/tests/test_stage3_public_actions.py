from datetime import datetime,timezone
from types import SimpleNamespace


def test_panel_targets_only_expose_saved_player_options_and_public_entity_ids():
    from app.investigation_jobs import public_investigation_node
    node=SimpleNamespace(id='node',session_id='session',parent_id=None,depth=0,scene_id='place',state_snapshot={},
        rendered_scene={'options':[{'id':'talk','label':'交流'},{'id':'present','label':'出示'},{'id':'decide','label':'选择'}]},
        canon_version='version',prompt_version='prompt',model_id='model',created_at=datetime.now(timezone.utc),
        investigation_options={'talk':{'type':'talk','character_id':'known-person','topic':'PRIVATE_TOPIC'},
            'present':{'type':'present','character_id':'known-person','evidence_id':'discovered'},
            'decide':{'type':'decide','ending_id':'HIDDEN_ENDING'},
            'hidden':{'type':'investigate','object_id':'HIDDEN_OBJECT'}})
    result=public_investigation_node(node)
    assert result['option_targets']=={'talk':{'character_id':'known-person'},'present':{'character_id':'known-person','evidence_id':'discovered'},'decide':{}}
    assert 'PRIVATE_TOPIC' not in str(result) and 'HIDDEN_ENDING' not in str(result) and 'HIDDEN_OBJECT' not in str(result)
