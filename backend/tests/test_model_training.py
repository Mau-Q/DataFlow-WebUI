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
