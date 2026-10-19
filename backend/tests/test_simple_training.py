import asyncio
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from app.core.config import settings
from app.core.container import container
from app.services.data_library import DataLibrary, LibraryError, _hash
from app.services.json_schema_manager import JsonSchemaManager
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.task_registry import TaskRegistry
from app.services.operator_registry import OperatorRegistry
from app.services.pipeline_registry import PipelineRegistry
from app.services.simple_training import definitions, install_templates, freeze_inputs
from app.services.simple_training_operators import APIImagePairGenerator, TrainingPairFormatter, image_data
from app.services.text_generation import TextGeneration
from app.services.task_results import TaskResults
from app.services.task_store import patch_task


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'CACHE_DIR', str(tmp_path/'cache'))
    monkeypatch.setattr(settings, 'DATAFLOW_CORE_DIR', str(tmp_path/'empty-core'))
    (tmp_path/'empty-core'/'api_pipelines').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    library = DataLibrary(tmp_path/'data'/'library')
    monkeypatch.setattr(container, 'data_library', library)
    monkeypatch.setattr(container, 'operator_registry', OperatorRegistry())
    monkeypatch.setattr(container, 'user_prompt_registry', UserPromptRegistry(tmp_path/'prompts.json'))
    monkeypatch.setattr(container, 'json_schema_manager', JsonSchemaManager(tmp_path/'schemas.json'))
    registry_file = tmp_path/'pipelines.json'
    # Avoid discovering/rewriting the real preset pipelines in an isolated test.
    registry_file.write_text('{"pipelines":{"keep":{"id":"keep","name":"keep","config":{}}}}')
    monkeypatch.setattr(container, 'pipeline_registry', PipelineRegistry(str(registry_file)))
    monkeypatch.setattr(container, 'task_registry', TaskRegistry(str(tmp_path/'tasks.json')))
    text = tmp_path/'text.jsonl'
    text.write_text(json.dumps({'text':'白色背景上有一个红色正方形。'})+'\n')
    buffer = io.BytesIO(); Image.new('RGB', (32,32), 'red').save(buffer, 'PNG')
    material = library.add_material('red.png', buffer.getvalue(), {'name':'红色图片'})
    path, _ = library.material_file(material['id'])
    images = tmp_path/'images.jsonl'
    images.write_text(json.dumps({'source':str(path),'material_id':material['id']})+'\n')
    datasets = {'text':{'root':str(text)}, 'image_text':{'root':str(images)}}
    monkeypatch.setattr(container, 'dataset_registry', SimpleNamespace(
        get=lambda key: datasets.get(key), get_columns=lambda key: ['text'] if key=='text' else ['source','material_id']))
    info = dict(id='fixture-service', cls_name='APILLMServing_request', params=[
        {'name':k, 'value':v} for k,v in dict(api_url='https://offline.invalid/v1/chat/completions',
            model_name='offline-test', api_key='TEST_FIXTURE_ONLY', max_workers=1).items()])
    monkeypatch.setattr(container, 'serving_registry', SimpleNamespace(_get=lambda key:copy.deepcopy(info) if key=='fixture-service' else None))
    install_templates(container)
    return container, tmp_path, material, info


def ready_config(c, definition):
    config = copy.deepcopy(c.pipeline_registry.get_pipeline(definition['id'])['config'])
    mode = config['execution_options']['simple_training']['modality']
    config['input_dataset']['id'] = mode
    config['operators'][0]['params']['init'][0]['value'] = 'fixture-service'
    return config


def test_install_is_idempotent_without_importing_datasets(platform):
    c, root, *_ = platform
    assert len([p for p in c.pipeline_registry.list_templates() if 'simple-training' in p['tags']]) == 4
    before = c.pipeline_registry._read()
    prompts = c.user_prompt_registry.list_all()
    install_templates(c)
    assert c.pipeline_registry._read() == before
    assert c.user_prompt_registry.list_all() == prompts
    assert not c.data_library.list_drafts() and not c.task_registry.list_executions()


def test_restart_preserves_resource_edits_and_deletions(platform):
    c, *_ = platform
    c.user_prompt_registry.update('simple-text-sft-v1', template='新要求 {text}')
    c.user_prompt_registry.delete('simple-image_text-dpo-v1')
    c.json_schema_manager.delete('simple-image_text-dpo-v1')
    install_templates(c)
    assert c.user_prompt_registry.get('simple-text-sft-v1')['template'] == '新要求 {text}'
    assert c.user_prompt_registry.get('simple-image_text-dpo-v1') is None
    assert c.json_schema_manager.get('simple-image_text-dpo-v1') is None


def test_templates_are_valid_api_responses_and_operator_details_bypass_stale_cache(platform):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints import pipelines, operators, prompts, json_schemas
    app = FastAPI()
    app.include_router(pipelines.router, prefix='/pipelines')
    app.include_router(operators.router, prefix='/operators')
    app.include_router(prompts.router, prefix='/prompts')
    app.include_router(json_schemas.router, prefix='/json_schemas')
    client = TestClient(app)
    response = client.get('/pipelines/templates')
    assert response.status_code == 200
    assert len(response.json()['data']) == 4
    response = client.get('/prompts/user')
    assert response.status_code == 200
    assert len(response.json()['data']) == 4
    response = client.get('/json_schemas')
    assert response.status_code == 200
    assert len(response.json()['data']) == 4
    for name in ('APIImagePairGenerator', 'TrainingPairFormatter'):
        response = client.get('/operators/details/'+name)
        assert response.status_code == 200
        assert response.json()['data']['type']['level_1'] != 'Unknown'


def test_real_api_serving_encodes_image_without_network(platform, monkeypatch):
    import pandas as pd
    import requests
    from dataflow.serving import APILLMServing_request
    from app.services.resource_resolution import resolve_pipeline_resources, instantiate_prompt
    from app.services.simple_training_operators import parse_candidate
    c, root, material, _ = platform
    config, _ = resolve_pipeline_resources(ready_config(c, definitions()[2]))
    prompt = next(p['value'] for p in config['operators'][0]['params']['init'] if p['name']=='prompt_template')
    path, _ = c.data_library.material_file(material['id'])
    payloads = []
    def post(session, url, **kwargs):
        payload = json.loads(kwargs['data'])
        payloads.append(payload)
        assert payload['model'] == 'fixture-vision'
        image_url = payload['messages'][0]['content'][1]['image_url']['url']
        assert image_url == image_data(path)
        return SimpleNamespace(status_code=200, json=lambda:{'choices':[{'message':{'content':'{"question":"颜色？","answer":"红色"}'}}]})
    monkeypatch.setattr(requests.Session, 'post', post)
    monkeypatch.setenv('SIMPLE_TRAINING_TEST_KEY', 'TEST_ONLY')
    serving = APILLMServing_request(api_url='https://offline.invalid/v1/chat/completions', model_name='fixture-vision',
        key_name_of_api_key='SIMPLE_TRAINING_TEST_KEY', max_workers=1, max_retries=1)
    written = []
    storage = SimpleNamespace(read=lambda _:pd.DataFrame([{'source':str(path)}]),write=lambda frame:written.append(frame))
    APIImagePairGenerator(serving, instantiate_prompt(prompt)).run(storage)
    assert len(payloads) == 1 and parse_candidate(written[0]['candidate'][0])['answer'] == '红色'
    assert parse_candidate('<think>reasoning</think><answer>```json\n{"question":"q","answer":"a"}\n```</answer>')['answer'] == 'a'


@pytest.mark.parametrize('definition', definitions(), ids=lambda d:d['id'])
def test_native_executor_to_storage_and_collection(platform, monkeypatch, definition):
    c, root, material, info = platform
    from app.services import ray_pipeline_executor as executor
    from app.services.dataflow_engine import DataFlowEngine
    config = ready_config(c, definition)
    # Exercise native validation and save/reopen enrichment, not just operators.
    assert c.pipeline_registry.validate_pipeline_config(config).valid
    saved = c.pipeline_registry.create_pipeline(dict(name=definition['name'], config=config, tags=['simple-training']))
    config = c.pipeline_registry.get_pipeline(saved['id'])['config']
    assert TextGeneration().preflight(config)['ready']
    calls = []
    class FixtureServing:
        def __init__(self, **kwargs): pass
        def generate_from_input(self, user_inputs, **kwargs):
            calls.extend(user_inputs)
            return [response] * len(user_inputs)
        def generate_from_conversations(self, conversations):
            calls.extend(conversations)
            assert conversations[0][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
            return [response] * len(conversations)
        def cleanup(self): pass
    pair = dict(question='图形是什么颜色？', answer='红色。') if definition['id'].split('-')[-2]=='sft' else dict(question='图形是什么颜色？', chosen='红色。', rejected='蓝色。')
    response = json.dumps(pair, ensure_ascii=False)
    monkeypatch.setattr(executor, 'APILLMServing_request', FixtureServing)
    # Run the actual worker function in-process with only model calls replaced.
    async def execute(frozen, runtime, tid, *args):
        result = executor.dataflow_pipeline_execute(frozen, runtime, tid, c.task_registry.path)
        patch_task(c.task_registry.path, tid, result)
    monkeypatch.setattr(executor.ray_executor, 'submit_execution', execute)
    submitted = asyncio.run(TextGeneration().submit(pipeline_id=saved['id'], output_root=str(root/'results')))
    task = c.task_registry.get(submitted['task_id'])
    assert task['status'] == 'completed', task
    assert len(calls) == 1
    assert 'TEST_FIXTURE_ONLY' not in json.dumps(task)
    results = TaskResults(c)
    detail = results.detail(submitted['task_id'])
    assert detail['available'] and detail['collectable'], detail
    assert detail['modality'] == definition['config']['execution_options']['simple_training']['modality']
    final = Path(detail['artifact']['path'])
    assert final.name == 'final.jsonl' and final.is_file()
    record = json.loads(final.read_text())
    assert 'candidate' not in record and 'training_sample' not in record
    if detail['modality'] == 'image_text':
        assert (final.parent/record['images'][0]).is_file()
        assert detail['artifact']['media_bindings'][record['images'][0]] == material['id']
    collected = results.collect(submitted['task_id'], detail['artifact']['sha256'], name='人工收录测试')
    assert collected['added'] == 1
    repeated = results.collect(submitted['task_id'], detail['artifact']['sha256'], name='人工收录测试')
    assert repeated['reused'] and repeated['row_count'] == 1
    if detail['modality'] == 'image_text':
        assert collected['media_bindings'][record['images'][0]] == material['id']


def test_unconfigured_service_never_submits(platform, monkeypatch):
    c, root, *_ = platform
    from app.services.ray_pipeline_executor import ray_executor
    async def forbidden(*args): raise AssertionError('No API or worker may start')
    monkeypatch.setattr(ray_executor, 'submit_execution', forbidden)
    for definition in definitions():
        config = ready_config(c, definition)
        next(p for p in config['operators'][0]['params']['init'] if p['name']=='llm_serving')['value'] = None
        data = c.pipeline_registry._read()
        data['pipelines']['unready'] = dict(id='unready', name='未配置', config=config)
        c.pipeline_registry._write(data)
        with pytest.raises(LibraryError, match='未配置文本服务'):
            asyncio.run(TextGeneration().submit(pipeline_id='unready', output_root=str(root/'results')))
    assert not c.task_registry.list_executions() and not (root/'results').exists()


def test_snapshot_survives_original_changes_and_rejects_corruption(platform):
    c, root, material, _ = platform
    config = ready_config(c, definitions()[2])
    frozen = freeze_inputs(c, config)
    source, _ = c.data_library.material_file(material['id'])
    source.write_bytes(b'changed')
    config['execution_options']['input_snapshot'] = frozen
    assert TextGeneration()._freeze_input(config) == frozen
    Path(frozen['materials'][0]['path']).write_bytes(b'corrupted')
    with pytest.raises(LibraryError, match='固定的输入'):
        TextGeneration()._freeze_input(config)


@pytest.mark.parametrize('candidate', [None, 'not JSON', '{"question":"q","chosen":"same","rejected":"same"}', '{"question":"q","chosen":"","rejected":"x"}'])
def test_bad_candidates_fail_explicitly(platform, candidate):
    import pandas as pd
    from app.services.simple_training import candidate_schema
    storage = SimpleNamespace(read=lambda _:pd.DataFrame([{'text':'source','candidate':candidate}]), write=lambda _:pytest.fail('invalid output must not be written'))
    formatter = TrainingPairFormatter('dpo', 'text', candidate_schema('dpo'))
    with pytest.raises(ValueError, match='第 1 条候选'):
        formatter.run(storage)
