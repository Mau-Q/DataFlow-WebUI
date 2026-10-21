from types import SimpleNamespace
from app.services.source_progress import SourceProgress,content_identity,freeze_source
from app.services.data_library import DataLibrary
from app.schemas.data_library import DraftCreate
from app.services.training_lifecycle import TrainingLifecycle


def test_multi_source_aggregation_and_content_change(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');p=tmp_path/'a.jsonl';p.write_text('{"text":"old"}\n')
    a={'id':'source-a','name':'A','root':str(p)};b=dict(a,id='source-b',name='B');registry=SimpleNamespace(list=lambda:[a,b],get=lambda rid:a if rid=='source-a' else b)
    identity=content_identity(a)
    tasks=[{'task_id':tid,'pipeline_config':{'input_dataset':'source-a'},'input_identity':identity,'status':status,'output':{'artifacts':artifacts}} for tid,status,artifacts in [('t1','completed',[{'id':'a','kind':'training','row_count':1}]),('t2','running',[]),('t3','completed',[{'id':'z','kind':'training','row_count':0}]),('t4','failed',[]),('t5','cancelled',[])]]
    tasks.append({'task_id':'unknown','status':'completed','pipeline_config':{'input_dataset':'source-b'}})
    for i in range(2):
        draft=lib.create_draft(DraftCreate(name=str(i),modality='text',training_type='sft'))
        with lib._writing():
            rec=lib._get('drafts',draft['id']);rec.update(rows=[{'instruction':'Q','output':'A'}],sample_ids=['s1'],sample_sources={'s1':[{'task_id':'t1'},{'task_id':'unknown'}]},collections=['t1:a'])
            lib.db.put('drafts',rec)
        if i==0:TrainingLifecycle(lib).publish(draft['id'])
    service=SourceProgress(registry,lib,SimpleNamespace(list_executions=lambda:tasks))
    r=service.page()['items'][0]
    assert len(r['datasets'])==2 and r['active']==['t2'] and len(r['releases'])==1 and r['zero_samples']==['t3'] and r['pending']==[]
    assert service.page()['items'][1]['unknown_source']==['unknown']
    p.write_text('{"text":"new"}\n')
    assert 't1' in service.page()['items'][0]['old_content']
    assert service.page()['items'][0]['coverage'] is None
    frozen=freeze_source({'input_dataset':'source-a'},registry,lib)
    assert frozen['identity']==content_identity(a)['identity']
