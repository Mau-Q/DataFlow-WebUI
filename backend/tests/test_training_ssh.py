"""Isolated transport/process checks. Never connect to a real SSH host."""
import json,subprocess,sys,time,os,signal
from pathlib import Path
import pytest
from app.services.model_training import ModelTraining,TrainingError
from app.services.training_ssh import validate_host,save_host,start,sync,SSHTransport,MKDIR,PUBLISH,PREFLIGHT,START,STATUS,STOP

HOST={'alias':'fixture-only','workdir':'/tmp/fixture-training','python':'/usr/bin/python3','gpus':'0'}


def test_command_and_host_guards(monkeypatch):
    for key,value in [('alias','-oProxyCommand=bad'),('workdir','/tmp/a;bad'),('python','python3;bad'),('gpus','0;bad')]:
        with pytest.raises(TrainingError):validate_host(dict(HOST,**{key:value}))
    observed=[]
    def run(argv,**kwargs):
        observed.append((argv,kwargs));return subprocess.CompletedProcess(argv,0,'{}','')
    monkeypatch.setattr(subprocess,'run',run)
    t=SSHTransport(HOST);t.execute('print(1)','a; echo bad')
    assert 'StrictHostKeyChecking=yes' in observed[0][0]
    assert "'a; echo bad'" in observed[0][0][-1]
    assert not observed[0][1].get('shell',False)


class Transport:
    calls=[];result=None;disconnect=False;bad_hash=False
    def __init__(self,host):pass
    def upload(self,path,remote):self.calls.append('upload')
    def execute(self,code,*args):
        self.calls.append(code)
        if self.disconnect:raise TrainingError('isolated disconnect',503)
        if code==PUBLISH and self.bad_hash:raise TrainingError('hash mismatch',409)
        if code==STATUS:return {'process':{'pid':123},'result':self.result}
        return {}


def setup_service(tmp_path):
    from app.services.model_training import digest
    from app.schemas.model_training import TrainingPlan
    s=ModelTraining(tmp_path);save_host(s,HOST)
    p=tmp_path/'input.zip';p.write_bytes(b'isolated bundle')
    s.put('bundles',{'path':str(p),'archive_sha256':digest(p.read_bytes()),'manifest_sha256':'a'*64,'manifest':{'external_references':[],'source':{'commit':'fixture','dirty':False}},'plan_snapshot':TrainingPlan().model_dump()},'bundle')
    Transport.calls=[];Transport.result=None;Transport.disconnect=False;Transport.bad_hash=False
    return s


def test_start_idempotency_disconnect_reconnect_and_restart(tmp_path):
    s=setup_service(tmp_path)
    c=start(s,'bundle','request-123',Transport)
    assert c['phase']=='starting'
    assert start(s,'bundle','request-123',Transport)['idempotent']
    assert Transport.calls.count(START)==1
    with pytest.raises(TrainingError,match='已有'):start(s,'bundle','request-456',Transport)
    Transport.disconnect=True
    disconnected=sync(s,c['id'],factory=Transport)
    assert disconnected['phase']=='starting' and disconnected['connection']=='disconnected'
    Transport.disconnect=False
    Transport.result={'schema_version':1,'run_id':c['run_id'],'attempt_id':c['id'],'input_manifest_sha256':'a'*64,'sequence':1,'synthetic':False,'status':'stopped','metrics':[],'artifacts':[],'actual_config':{},'environment':{}}
    # Reopen metadata to simulate backend restart. Sync uses the persisted host/attempt identity.
    s=ModelTraining(tmp_path);r=sync(s,c['id'],stop=True,factory=Transport)
    assert r['phase']=='stopped' and r['connection']=='connected'
    assert s.get('runs',c['id'])['status']=='stopped'


def test_upload_failure_never_starts(tmp_path):
    s=setup_service(tmp_path);Transport.bad_hash=True
    r=start(s,'bundle','request-123',Transport)
    assert r['phase']=='unknown' and START not in Transport.calls


def test_local_runner_stops_child_group_and_rejects_identity(tmp_path):
    """Real local subprocess group, synthetic child; no training dependencies or GPU."""
    import hashlib
    runtime=Path(__file__).parents[1]/'app/services/training_runtime/runner.py'
    root=tmp_path/'run';root.mkdir()
    (root/'manifest.json').write_text('{"files":{},"external_references":[]}')
    (root/'train.yaml').write_text('fixture: true')
    child=root/'child.py';child.write_text('import subprocess,sys,time\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"])\nopen("grandchild.pid","w").write(str(p.pid))\ntime.sleep(120)\n')
    wrapper=root/'test_runner.py'
    wrapper.write_text(f'''import importlib.util,subprocess,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',{str(runtime)!r});m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.preflight=lambda root:{{'synthetic':True}}
real=m.subprocess.Popen
m.subprocess.Popen=lambda argv,**kwargs:real([sys.executable,{str(child)!r}] if argv[0]==sys.executable else argv,**kwargs)
m.run(Path({str(root)!r}),'attempt1','run1',{hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()!r})
''')
    process=subprocess.Popen([sys.executable,str(wrapper)],start_new_session=True)
    try:
        for _ in range(100):
            if (root/'grandchild.pid').exists() and (root/'result.json').exists():break
            time.sleep(.05)
        from app.services.training_runtime.runner import stop
        assert (root/'grandchild.pid').exists()
        rec=json.loads((root/'process.json').read_text());bad=dict(rec,identity={'wrong':True});(root/'process.json').write_text(json.dumps(bad))
        with pytest.raises(ValueError,match='identity'):stop(root,'attempt1')
        (root/'process.json').write_text(json.dumps(rec))
        result=stop(root,'attempt1');assert result['status']=='stopped'
        process.wait(timeout=5)
        pid=int((root/'grandchild.pid').read_text())
        # macOS may briefly retain a zombie; it must not be running.
        observed=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
        assert not observed or observed.startswith('Z')
    finally:
        if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
