import sqlite3
import pytest
from app.schemas.model_training import TrainingPlan
from app.services.model_training import ModelTraining, TrainingError


def test_plan_reopen_conflict_copy_and_missing_storage(tmp_path):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(name='independent').model_dump()
    r=s.save_plan(p)
    assert r['plan']['group_id'] is None
    assert ModelTraining(tmp_path).get('plans',r['id'])==r
    r2=s.save_plan(dict(p,model='remote/model'),r['id'],r['version'])
    with pytest.raises(TrainingError,match='已更新'): s.save_plan(p,r['id'],r['version'])
    assert s.get('plans',r['id'])==r2
    assert s.check(p)['compatibility']=='failed'
    backup=s.backup()
    with sqlite3.connect(backup) as db: assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    s.path.unlink()
    with pytest.raises(TrainingError,match='缺失'): ModelTraining(tmp_path)


def test_corrupt_database_is_not_reset(tmp_path):
    p=tmp_path/'training.sqlite3';p.write_bytes(b'broken')
    with pytest.raises(TrainingError,match='损坏'): ModelTraining(tmp_path)
    assert p.read_bytes()==b'broken'

from app.services.training_compiler import catalog, compile_plan, save_descriptor

@pytest.mark.parametrize('family,name',[('selection','random'),('mixture','odm'),('reweighting','loss'),('reorder','dynamic_folding'),('lego','select_only')])
def test_families_compile_without_importing_training_packages(tmp_path,family,name):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':'a.jsonl'},{'kind':'file','ref':'b.jsonl','domain':'second'}],strategy={'family':family,'component':name,'params':{}}).model_dump()
    r=compile_plan(s,p)
    assert not r['checks']['errors'],r['checks']
    assert r['train']['packing'] is False
    assert r['train']['report_to']=='none'
    assert r['train']['train_type'].startswith('dynamic_')


def test_compatibility_and_custom_description(tmp_path):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(model='m',data=[{'kind':'file','ref':'a'}],strategy={'family':'reweighting','component':'adapt','params':{}}).model_dump()
    assert any('参考集' in e for e in compile_plan(s,p)['checks']['errors'])
    p['strategy']={'family':'mixture','component':'static','params':{'proportions':[1,1]}}
    assert any('总和' in e for e in compile_plan(s,p)['checks']['errors'])
    descriptor={'family':'selection','name':'user_alg','fields':{'k':{'type':'integer','default':3,'minimum':1}},'tasks':['sft'],'modalities':['text']}
    save_descriptor(s,descriptor)
    p['strategy']={'family':'selection','component':'user_alg','params':{'k':0}}
    assert any('最小值' in e for e in compile_plan(s,p)['checks']['errors'])
    p['strategy']['params']['k']=4
    assert compile_plan(s,p)['components']['selectors']['user_alg']['params']['k']==4
    p['task']='dpo'
    assert any('DPO' in e for e in compile_plan(s,p)['checks']['errors'])
