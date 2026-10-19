"""Four small native pipeline templates; installation never imports sample data."""
import copy
import json
import shutil
import uuid
from pathlib import Path

from app.services.data_library import LibraryError, _hash, _json_bytes, _now
from app.services.simple_training_operators import image_data


def candidate_schema(training_type):
    fields = ['question', 'answer'] if training_type == 'sft' else ['question', 'chosen', 'rejected']
    return {'type': 'object', 'additionalProperties': False, 'required': fields,
            'properties': {k: {'type': 'string', 'minLength': 1, 'pattern': r'\S'} for k in fields}}


def definitions():
    result = []
    for modality, label in [('text', '文本'), ('image_text', '图片')]:
        for training_type in ('sft', 'dpo'):
            key = f'simple-{modality}-{training_type}-v1'
            source = '以下材料：\n{text}' if modality == 'text' else '所附图片'
            task = ('生成一个能依据材料回答的问题和正确答案。仅返回 JSON 对象，字段 question、answer。'
                    if training_type == 'sft' else
                    '生成一个能依据材料回答的问题、正确答案 chosen，以及仅包含一个明显事实错误的较差答案 rejected。'
                    '不要交换优劣，不要生成危险内容。仅返回 JSON 对象，字段 question、chosen、rejected。')
            prompt = f'请依据{source}，用中文{task}不得借助材料以外的信息，不要输出解释或 Markdown。'
            generator = 'FormatStrPromptedGenerator' if modality == 'text' else 'APIImagePairGenerator'
            init = {'llm_serving': None, 'prompt_template': f'user_prompt:{key}'}
            run = {'output_key': 'candidate'}
            if modality == 'text':
                init['system_prompt'] = '依据材料生成训练样例。严格遵守用户要求的 JSON 字段。'
                run['input_keys'] = [{'name': 'text', 'value': 'text'}]
            else:
                run['input_image_key'] = 'source'
            def params(values):
                return [{'name': k, 'value': v} for k, v in values.items()]
            config = {'file_path': '', 'input_dataset': {'id': '', 'location': [30, 150]}, 'operators': [
                {'name': generator, 'location': [320, 150], 'params': {'init': params(init), 'run': params(run)}},
                {'name': 'TrainingPairFormatter', 'location': [640, 150], 'params': {
                    'init': params({'training_type': training_type, 'modality': modality, 'json_schema': f'schema_ref:{key}'}),
                    'run': params({'input_key': 'candidate', 'output_key': 'training_sample'})}},
            ], 'execution_options': {'simple_training': {'modality': modality, 'training_type': training_type},
                  'capture_responses': True, 'training_output': True, 'additional_retries': 0}}
            result.append(dict(id=key, name=f'最简{label} {training_type.upper()}', prompt=prompt,
                               generator=generator, schema=candidate_schema(training_type), config=config,
                               tags=['template', 'simple-training', modality, training_type]))
    return result


def install_templates(c):
    """Add missing versioned defaults; preserve user edits and existing records."""
    for definition in definitions():
        key, now = definition['id'], _now()
        usage = ('图文' if 'image_text' in key else '文本') + ' ' + definition['config']['execution_options']['simple_training']['training_type'].upper()
        data = c.pipeline_registry._read()
        if key not in data['pipelines']:
            # Seed resources only with a new template. Subsequent restarts must
            # respect edits/deletions made in the independent managers.
            with c.user_prompt_registry.store.writing() as records:
                if key not in records:
                    records[key] = dict(id=key, name=definition['name']+' · 生成提示词', template=definition['prompt'],
                        description='小样本流程验收；DPO 为合成偏好对，需要人工检查事实与优劣。',
                        allowed_operators=[definition['generator']], example_variables={}, usage=usage,
                        purpose='生成', created_at=now, updated_at=now)
            with c.json_schema_manager.store.writing() as records:
                if key not in records:
                    records[key] = dict(id=key, name=definition['name']+' · 候选结构', schema=json.dumps(definition['schema'], ensure_ascii=False),
                        description='仅检查结构；不证明答案事实正确。', example='', usage=usage, purpose='模型输出', created_at=now, updated_at=now)
            pipeline = {k: copy.deepcopy(definition[k]) for k in ('id', 'name', 'config', 'tags')}
            pipeline.update(created_at=now, updated_at=now, status='queued')
            # Templates intentionally have no dataset/service. Normal save/submit
            # still validates actual user-selected inputs and bindings.
            for op in pipeline['config']['operators']:
                op['params'] = c.pipeline_registry._parse_frontend_params(op['params'])
            data['pipelines'][key] = c.pipeline_registry._enrich_pipeline_operators_internal(pipeline)
            c.pipeline_registry._write(data)
        elif any('kind' not in p for op in data['pipelines'][key]['config']['operators']
                 for part in ('init', 'run') for p in op['params'][part]):
            # Enrich missing UI metadata without replacing user parameter values.
            record = data['pipelines'][key]
            for op in record['config']['operators']:
                op['params'] = c.pipeline_registry._parse_frontend_params(op['params'])
            data['pipelines'][key] = c.pipeline_registry._enrich_pipeline_operators_internal(record)
            c.pipeline_registry._write(data)


def read_inputs(c, config):
    dataset_id = config.get('input_dataset')
    dataset_id = dataset_id.get('id') if isinstance(dataset_id, dict) else dataset_id
    dataset = c.dataset_registry.get(dataset_id) if dataset_id else None
    if not dataset or not Path(dataset['root']).is_file():
        raise LibraryError('请选择已经导入的本地输入数据集', 422)
    manifest = Path(dataset['root'])
    if manifest.suffix.lower() != '.jsonl':
        raise LibraryError('最简 pipeline 输入需要 JSONL；文本导入 text.jsonl，图片使用原始材料导入', 422)
    try:
        rows = [json.loads(line) for line in manifest.read_text('utf-8-sig').splitlines() if line.strip()]
    except (ValueError, UnicodeError) as exc:
        raise LibraryError('输入不是有效 JSONL', 422) from exc
    if not rows or len(rows) > 100:
        raise LibraryError('最简示例每次支持 1–100 条输入', 422)
    modality = config['execution_options']['simple_training']['modality']
    for row in rows:
        if not isinstance(row, dict):
            raise LibraryError('输入行必须是 JSON 对象', 422)
        if {'candidate', 'training_sample', 'media_ref'} & row.keys():
            raise LibraryError('输入不能包含候选、训练输出或固定媒体字段', 422)
        if modality == 'text':
            if not isinstance(row.get('text'), str) or not row['text'].strip():
                raise LibraryError('文本输入需要非空 text 字段', 422)
        else:
            if not row.get('material_id'):
                raise LibraryError('请通过原始数据集的图片材料入口导入图片', 422)
            path, material = c.data_library.material_file(row['material_id'])
            if material['kind'] != 'image':
                raise LibraryError('图片 pipeline 仅接受图片材料', 422)
            image_data(path)
    return dataset_id, rows


def freeze_inputs(c, config):
    dataset_id, rows = read_inputs(c, config)
    root = c.data_library.root / 'task_inputs' / uuid.uuid4().hex
    root.mkdir(parents=True)
    materials, bindings = [], {}
    try:
        if config['execution_options']['simple_training']['modality'] == 'image_text':
            for row in rows:
                source, material = c.data_library.material_file(row['material_id'])
                content = source.read_bytes()
                if _hash(content) != material['sha256']:
                    raise LibraryError('图片在提交期间发生变化', 409)
                ref = 'images/' + material['sha256'] + source.suffix.lower()
                target = root / ref
                c.data_library._atomic(target, content)
                row.update(source=str(target.resolve()), media_ref=ref)
                bindings[ref] = row['material_id']
                materials.append(dict(path=str(target.resolve()), sha256=_hash(content), material_id=row['material_id'], media_ref=ref))
        target = root / 'input.jsonl'
        content = b''.join(_json_bytes(row)+b'\n' for row in rows)
        c.data_library._atomic(target, content)
        return dict(path=str(target.resolve()), sha256=_hash(content), materials=materials, media_bindings=bindings, dataset_id=dataset_id)
    except Exception:
        shutil.rmtree(root)
        raise
