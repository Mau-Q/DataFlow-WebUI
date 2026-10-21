"""Failure/competition regressions; no remote service, model or Ray cluster."""
import asyncio
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.services.serving_registry import ServingRegistry
from app.services.pipeline_registry import PipelineFileAnalyzer, PipelineRegistry
from app.services.task_registry import TaskRegistry
from app.services.dataflow_engine import DataFlowEngine
from app.services.ray_pipeline_executor import ray_executor
from app.core.container import container
from app.core.config import settings


def test_serving_competing_instances_preserve_all_mutations(tmp_path):
    path = str(tmp_path/'serving.yaml')
    registries = [ServingRegistry(path) for _ in range(4)]
    barrier = threading.Barrier(4)
    def create(i):
        barrier.wait()
        return registries[i]._set(str(i), 'APILLMServing_request', [])
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create, range(4)))
    assert set(registries[0]._get_all()) == set(ids)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: registries[i]._update(ids[i], name=f'edited-{i}'), range(4)))
    assert {v['name'] for v in registries[0]._get_all().values()} == {f'edited-{i}' for i in range(4)}
    # Readers always see a complete YAML after atomic replace.
    assert all(registries[0]._get(sid)['id'] == sid for sid in ids)


def test_pipeline_competing_updates_preserve_records(tmp_path):
    path = str(tmp_path/'pipelines.json')
    Path(path).write_text(json.dumps({'pipelines': {'seed': {'id':'seed','name':'Seed','config':{'operators':[]}}}}))
    with patch.object(PipelineRegistry, '_update_all_api_pipelines_operators'):
        registries = [PipelineRegistry(path) for _ in range(4)]
    for registry in registries:
        registry.validate_pipeline_config = lambda _: SimpleNamespace(valid=True)
    barrier = threading.Barrier(4)
    def create(i):
        barrier.wait()
        return registries[i].create_pipeline({'name':str(i), 'config':{'operators':[]}})['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create, range(4)))
    assert set(registries[0]._read()['pipelines']) == {'seed', *ids}
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: registries[i].update_pipeline(ids[i], {'name': f'edited-{i}'}), range(4)))
    assert {registries[0].get_pipeline(sid)['name'] for sid in ids} == {f'edited-{i}' for i in range(4)}


def test_same_operator_instances_and_repeated_run_keep_own_parameters(tmp_path):
    source = '''class Pipeline:
    def __init__(self):
        self.a = Op(threshold=1)
        self.b = Op(threshold=2)
    def forward(self):
        self.a.run(input_key='first')
        self.b.run(input_key='second')
        self.a.run(input_key='third')
'''
    file = tmp_path/'pipeline.py'; file.write_text(source)
    analyzer = PipelineFileAnalyzer.from_file(str(file))
    registry = PipelineRegistry.__new__(PipelineRegistry)
    details = {'parameter': {'init':[{'name':'threshold'}], 'run':[{'name':'input_key'}]}}
    with patch.object(container, 'operator_registry', SimpleNamespace(get_op_details=lambda _: details)):
        result = registry._enrich_pipeline_operators_internal({'config':{'file_path':str(file), 'operators':analyzer.operators()}})
    ops = result['config']['operators']
    assert [op['params']['init'][0]['value'] for op in ops] == [1,2,1]
    assert [op['params']['run'][0]['value'] for op in ops] == ['first','second','third']


@pytest.mark.parametrize('stage', ['decode', 'dispatch'])
def test_submission_failure_leaves_terminal_task(tmp_path, stage):
    registry = TaskRegistry(str(tmp_path/'tasks.json'))
    with patch.object(container, 'data_library', None), patch.object(DataFlowEngine, 'decode_hashed_arguments',
            side_effect=ValueError('secret') if stage=='decode' else None, return_value={}), \
            patch.object(ray_executor, 'submit_execution', new=AsyncMock(side_effect=RuntimeError('secret'))):
        with pytest.raises((ValueError, RuntimeError)):
            asyncio.run(registry.start_execution_async(config={'input_dataset':'fixture','operators':[]}))
    task = registry.list_executions()[0]
    assert task['status'] == 'failed'
    assert task['completed_at']
    assert 'secret' not in json.dumps(task)


@pytest.mark.parametrize('adapter_name', ['codex', 'claude'])
def test_agent_drains_large_stderr_and_reports_nonzero_exit(tmp_path, adapter_name):
    from app.services.agents.codex_adapter import CodexAdapter
    from app.services.agents.claude_adapter import ClaudeAdapter
    cli = tmp_path/'fixture-cli'
    cli.write_text('#!'+sys.executable+'\nimport sys\nsys.stderr.write("x" * (24 * 1024 * 1024) + "fixture failed")\nsys.exit(17)\n')
    cli.chmod(0o755)
    adapter = (CodexAdapter if adapter_name=='codex' else ClaudeAdapter)(cli_path=str(cli), webui_root=tmp_path,
                    mcp_config_path=tmp_path/'unused', system_prompt='fixture', allowed_tools='')
    async def collect():
        return [event async for event in adapter.chat_stream('fixture')]
    events = asyncio.run(asyncio.wait_for(collect(), timeout=5))
    assert any(event['type']=='error' and '17' in event['message'] and 'fixture failed' in event['message'] for event in events)
    assert events[-1]['type']=='done'
    assert not adapter.is_running


@pytest.mark.parametrize('engine', ['sync', 'ray_function'])
def test_failed_operator_does_not_change_process_cwd(tmp_path, engine):
    from dataflow.utils.registry import OPERATOR_REGISTRY
    original = Path.cwd()
    core=tmp_path/'core'; (core/'api_pipelines').mkdir(parents=True)
    input_file=tmp_path/'input.jsonl'; input_file.write_text('{"text":"fixture"}\n')
    class FailedOperator:
        def run(self, storage):
            assert Path.cwd() == original
            raise RuntimeError('fixture failure')
    with patch.object(settings,'DATAFLOW_CORE_DIR',str(core)), patch.object(settings,'CACHE_DIR',str(tmp_path/'cache')), \
            patch.object(container,'dataset_registry',SimpleNamespace(get=lambda _:dict(root=str(input_file)))), \
            patch.object(OPERATOR_REGISTRY,'_get_all',lambda:None), patch.object(OPERATOR_REGISTRY,'get',lambda _:FailedOperator):
        try:
            config={'input_dataset':'fixture','operators':[{'name':'FailedOperator','params':{'init':[],'run':[]}}]}
            if engine == 'sync':
                result=DataFlowEngine().run(config,'fixture')
            else:
                from app.services.ray_pipeline_executor import dataflow_pipeline_execute
                runtime={'storage':{'first_entry_file_name':str(input_file),'cache_path':str(tmp_path/'cache'),
                                    'file_name_prefix':'fixture','cache_type':'jsonl'}}
                with patch('app.services.ray_pipeline_executor.compile_check',return_value={'ok':True}):
                    result=dataflow_pipeline_execute(config,runtime,'fixture',None)
            assert result['status']=='failed'
            assert Path.cwd()==original
        finally:
            os.chdir(original)


def test_one_sample_edit_writes_only_changed_row_and_views_page_in_sql(tmp_path):
    from app.services.data_library import DataLibrary, _json_bytes
    from app.services.training_lifecycle import TrainingLifecycle
    from app.schemas.data_library import DraftCreate
    lib=DataLibrary(tmp_path/'data/library')
    did=lib.create_draft(DraftCreate(name='Rows'))['id']
    rows=[dict(instruction=f'q{i}',input='',output='a') for i in range(100)]
    lib.import_rows(did,'rows.jsonl',b''.join(_json_bytes(r)+b'\n' for r in rows),{})
    lifecycle=TrainingLifecycle(lib)
    sid=lifecycle.view(did)['sample_ids'][0]
    statements=[]; original=lib.db.connect
    def connect():
        con=original(); con.set_trace_callback(statements.append); return con
    with patch.object(lib.db,'connect',side_effect=connect):
        lifecycle.edit(did,sid,row=dict(instruction='edited',input='',output='a'))
    assert not any(s.startswith('DELETE FROM samples') for s in statements)
    assert sum(s.startswith('UPDATE samples SET payload=') for s in statements)==1
    assert not any(s.startswith('INSERT INTO samples') for s in statements)
    statements.clear()
    with patch.object(lib.db,'connect',side_effect=connect):
        page=lib.get_draft(did,40,7); catalog=lib.list_drafts()
    assert len(page['rows'])==7 and page['rows'][0]==rows[40]
    assert page['row_count']==catalog[0]['row_count']==100
    assert page['fields']==['input','instruction','output']
    assert any('LIMIT 7 OFFSET 40' in s for s in statements)
    assert not any(s.startswith('SELECT payload FROM samples') for s in statements)


def test_backup_scope_and_recovery_keep_runtime_and_config(tmp_path):
    from app.services.data_library import DataLibrary
    from app.schemas.data_library import DraftCreate
    from app.services.dataset_backups import DatasetBackups
    from app.services.dataset_persistence import register_backups
    root=tmp_path/'data'; lib=DataLibrary(root/'library')
    lib.create_draft(DraftCreate(name='Original'))
    runtime=root/'dataflow_core/example_data/unchanged.txt';runtime.parent.mkdir(parents=True);runtime.write_text('runtime')
    config=root/'serving_registry.yaml';config.write_text('user-controlled')
    manager=DatasetBackups(root,tmp_path/'backups'); register_backups(root,manager)
    for i in range(3):lib.create_draft(DraftCreate(name=str(i)))
    assert not manager.archives()
    manager.flush_pending()
    assert len(manager.archives())==1
    archive=manager.archives()[0];manifest=manager.verify(archive)
    assert not any('dataflow_core' in name or 'serving_registry' in name for name in manifest['files'])
    manager.restore(archive,tmp_path/'restored')
    manager.recover_if_needed(archive)
    assert runtime.read_text()=='runtime' and config.read_text()=='user-controlled'
    assert len(lib.list_drafts())==4


@pytest.mark.parametrize('adapter_name', ['codex', 'claude'])
def test_agent_cancellation_reaps_child_without_success_event(tmp_path, adapter_name):
    from app.services.agents.codex_adapter import CodexAdapter
    from app.services.agents.claude_adapter import ClaudeAdapter
    cli=tmp_path/'fixture-cli'
    cli.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(30)\n');cli.chmod(0o755)
    adapter=(CodexAdapter if adapter_name=='codex' else ClaudeAdapter)(cli_path=str(cli),webui_root=tmp_path,
              mcp_config_path=tmp_path/'unused',system_prompt='fixture',allowed_tools='')
    async def exercise():
        events=[]
        async def consume():
            async for event in adapter.chat_stream('fixture'): events.append(event)
        consumer=asyncio.create_task(consume())
        async def wait_for_child():
            while adapter._process is None: await asyncio.sleep(.01)
        await asyncio.wait_for(wait_for_child(),5)
        process=adapter._process
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError): await consumer
        assert process.returncode is not None
        assert not adapter.is_running
        assert not any(event['type']=='done' for event in events)
    asyncio.run(exercise())


@pytest.mark.parametrize('kind', ['serving', 'pipeline'])
def test_registry_processes_share_transaction_lock(tmp_path, kind):
    import subprocess
    path=tmp_path/('registry.yaml' if kind=='serving' else 'registry.json')
    path.write_text('{}\n' if kind=='serving' else json.dumps({'pipelines':{'seed':{'id':'seed','config':{'operators':[]}}}}))
    script=tmp_path/'worker.py'
    script.write_text('''import sys,time
from types import SimpleNamespace
from app.services.serving_registry import ServingRegistry
from app.services.pipeline_registry import PipelineRegistry
kind,path,prefix=sys.argv[1:]
if kind=='serving':
    registry=ServingRegistry(path)
    original=registry._get_all
    def read():
        data=original(); time.sleep(.02); return data
    registry._get_all=read
    for i in range(5): registry._set(prefix+str(i),'APILLMServing_request',[])
else:
    PipelineRegistry._update_all_api_pipelines_operators=lambda self:None
    registry=PipelineRegistry(path)
    registry.validate_pipeline_config=lambda _:SimpleNamespace(valid=True)
    original=registry._read
    def read():
        data=original(); time.sleep(.02); return data
    registry._read=read
    for i in range(5): registry.create_pipeline({'name':prefix+str(i),'config':{'operators':[]}})
''')
    processes=[subprocess.Popen([sys.executable,str(script),kind,str(path),str(i)],
                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for i in range(3)]
    try:
        assert all(process.wait(timeout=20)==0 for process in processes)
    finally:
        for process in processes:
            if process.poll() is None: process.kill()
            process.wait()
    if kind=='serving': assert len(ServingRegistry(str(path))._get_all())==15
    else: assert len(json.loads(path.read_text())['pipelines'])==16


def test_serving_unicode_roundtrip_on_non_utf8_system_locale(tmp_path, monkeypatch):
    import builtins
    registry=ServingRegistry(str(tmp_path/'serving.yaml'))
    sid=registry._set('中文模型', 'APILLMServing_request', [])
    original=builtins.open
    def locale_open(file, mode='r', *args, **kwargs):
        if 'b' not in mode and not args and 'encoding' not in kwargs:
            kwargs['encoding']='cp1252'
        return original(file,mode,*args,**kwargs)
    monkeypatch.setattr(builtins,'open',locale_open)
    assert registry._get(sid)['name']=='中文模型'


def test_scoped_recovery_preserves_runtime_symlinks_and_empty_directories(tmp_path):
    from app.services.data_library import DataLibrary
    from app.services.dataset_backups import DatasetBackups
    from app.schemas.data_library import DraftCreate
    root=tmp_path/'data';lib=DataLibrary(root/'library')
    lib.create_draft(DraftCreate(name='Protected'))
    target=tmp_path/'runtime-target';target.mkdir();(target/'template.txt').write_text('runtime')
    runtime=root/'dataflow_core'
    try: runtime.symlink_to(target,target_is_directory=True)
    except OSError: pytest.skip('Directory symlinks are unavailable on this platform')
    (root/'empty-runtime-cache').mkdir()
    (root/'broken-runtime-link').symlink_to('absent-runtime-file')
    manager=DatasetBackups(root,tmp_path/'backups');archive=manager.snapshot()
    manager.recover_if_needed(archive)
    assert runtime.is_symlink() and runtime.resolve()==target
    assert (runtime/'template.txt').read_text()=='runtime'
    assert (root/'empty-runtime-cache').is_dir()
    assert (root/'broken-runtime-link').is_symlink()
    assert (target/'template.txt').read_text()=='runtime'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX inherited-pipe process-group regression')
@pytest.mark.parametrize('adapter_name', ['codex', 'claude'])
@pytest.mark.parametrize('kill_before_cancel', [False, True])
def test_agent_cancel_with_descendant_holding_pipes_finishes(tmp_path, adapter_name, kill_before_cancel):
    import signal
    from app.services.agents.codex_adapter import CodexAdapter
    from app.services.agents.claude_adapter import ClaudeAdapter
    pid_file=tmp_path/'child.pid';cli=tmp_path/'fixture-cli'
    cli.write_text('#!'+sys.executable+'\nimport subprocess,sys,time,pathlib\n'
                   'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
                   f'pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n'
                   'time.sleep(30)\n');cli.chmod(0o755)
    adapter=(CodexAdapter if adapter_name=='codex' else ClaudeAdapter)(cli_path=str(cli),webui_root=tmp_path,
                mcp_config_path=tmp_path/'unused',system_prompt='fixture',allowed_tools='')
    async def exercise():
        async def consume():
            return [event async for event in adapter.chat_stream('fixture')]
        consumer=asyncio.create_task(consume())
        try:
            async def ready():
                while not pid_file.exists(): await asyncio.sleep(.01)
            await asyncio.wait_for(ready(),5)
            if kill_before_cancel:
                adapter.kill()
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(consumer),2)
        finally:
            if pid_file.exists():
                try: os.kill(int(pid_file.read_text()),signal.SIGKILL)
                except ProcessLookupError: pass
            if not consumer.done():
                try: await asyncio.wait_for(consumer,5)
                except (asyncio.CancelledError, asyncio.TimeoutError): pass
    asyncio.run(exercise())


@pytest.mark.skipif(os.name != 'posix', reason='POSIX background-child lifetime check')
@pytest.mark.parametrize('adapter_name', ['codex', 'claude'])
def test_successful_agent_turn_preserves_detached_output_background_child(tmp_path, adapter_name):
    import signal
    from app.services.agents.codex_adapter import CodexAdapter
    from app.services.agents.claude_adapter import ClaudeAdapter
    pid_file=tmp_path/'background.pid';cli=tmp_path/'fixture-cli'
    cli.write_text('#!'+sys.executable+'\nimport subprocess,sys,pathlib\n'
                   'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],'
                   'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n'
                   f'pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n')
    cli.chmod(0o755)
    adapter=(CodexAdapter if adapter_name=='codex' else ClaudeAdapter)(cli_path=str(cli),webui_root=tmp_path,
                mcp_config_path=tmp_path/'unused',system_prompt='fixture',allowed_tools='')
    async def collect(): return [event async for event in adapter.chat_stream('fixture')]
    try:
        events=asyncio.run(asyncio.wait_for(collect(),5))
        assert events==[{'type':'done'}]
        os.kill(int(pid_file.read_text()),0)
    finally:
        if pid_file.exists():
            try: os.kill(int(pid_file.read_text()),signal.SIGKILL)
            except ProcessLookupError: pass
