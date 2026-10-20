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

import json, zipfile, io, subprocess, sys
from pathlib import Path
from app.services.training_bundles import export_bundle, safe_members, snapshot_source


def test_portable_bundle_hash_guard_and_no_fake_run(tmp_path,monkeypatch):
    src=tmp_path/'src';(src/'src/dataflex').mkdir(parents=True)
    (src/'src/dataflex/cli.py').write_text('print("fixture")')
    subprocess.run(['git','init',str(src)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(src),'add','src'],check=True)
    monkeypatch.setenv('DATAFLEX_SOURCE_DIR',str(src))
    subprocess.run(['git','-C',str(src),'-c','user.name=test','-c','user.email=test@example.invalid','commit','-m','fixture'],check=True,capture_output=True)
    data=tmp_path/'rows.jsonl';data.write_text('{"instruction":"q","output":"a"}\n')
    service=ModelTraining(tmp_path/'state')
    r=service.save_plan(TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':str(data)}]).model_dump())
    bundle=export_bundle(service,r['id'])
    members=safe_members(Path(bundle['path']).read_bytes());dest=tmp_path/'moved';dest.mkdir()
    for k,v in members.items():p=dest/k;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
    result=subprocess.run([sys.executable,str(dest/'runner.py'),'verify'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert service.list('runs')==[]
    (dest/'data/dataset_0.jsonl').write_text('changed')
    result=subprocess.run([sys.executable,str(dest/'runner.py'),'verify'],capture_output=True,text=True)
    assert result.returncode!=0
    data.write_text('{"instruction":"changed","output":"a"}\n')
    bundle2=export_bundle(service,r['id'])
    assert bundle2['manifest']['inputs'][0]['sha256']!=bundle['manifest']['inputs'][0]['sha256']
    (src/'src/dataflex/cli.py').write_text('print("changed")')
    bundle3=export_bundle(service,r['id'])
    assert bundle3['manifest']['source_sha256']!=bundle2['manifest']['source_sha256']


def test_zip_and_symlink_guards(tmp_path):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('../escape','no')
    with pytest.raises(TrainingError,match='不安全'):safe_members(out.getvalue())
    from app.services.training_bundles import safe_read
    (tmp_path/'file').write_text('x');(tmp_path/'link').symlink_to(tmp_path/'file')
    with pytest.raises(TrainingError,match='普通文件'):safe_read(tmp_path/'link')
