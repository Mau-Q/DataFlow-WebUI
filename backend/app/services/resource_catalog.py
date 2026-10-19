"""Read-only catalogs: saved references are distinct from operator compatibility."""
import copy
from app.core.container import container
from app.services.builtin_resources import builtin_schemas
from app.services.resource_store import ResourceStore
from app.services.user_prompt_registry import _extract_placeholders

TEXT_SFT = {'KnowledgeCleanerPrompt', 'Text2MultiHopQAGeneratorPrompt', 'Text2QAQuestionQualityPrompt',
            'Text2QAAnswerAlignmentPrompt', 'Text2QAAnswerVerifiabilityPrompt', 'Text2QADownstreamValuePrompt', 'AlpagasusPrompt'}


def _params(op):
    raw = op.get('params') or {}
    if isinstance(raw, list):
        return raw
    if 'init' in raw or 'run' in raw:
        result = []
        for values in (raw.get('init') or [], raw.get('run') or []):
            result.extend([{'name': k, 'value': v} for k, v in values.items()] if isinstance(values, dict) else values)
        return result
    return [{'name': k, 'value': v} for k, v in raw.items()]


def _reference(value):
    if isinstance(value, dict):
        return value.get('ref')
    return value if isinstance(value, str) and value.startswith(('user_prompt:', 'schema_ref:', 'builtin:')) else None


class ResourceCatalog:
    def __init__(self, app_container=None):
        self.c = app_container or container

    def _pipelines(self):
        from app.services.text_generation import template as text_template
        from app.services.multimodal_templates import template as mm_template
        records = []
        if self.c.pipeline_registry:
            records = [dict(p, source='builtin' if self.c.pipeline_registry._is_preset_pipeline(p) else 'user', catalog_id='pipeline:' + p['id'], route={'path': '/m/', 'query': {'pipeline': p['id']}})
                       for p in self.c.pipeline_registry.list_pipelines()]
        text = text_template()
        records.append(dict(text, source='builtin', id='text-sft-template', catalog_id='template:text-sft', route={'path': '/m/generation'}))
        mm = mm_template()
        records.append(dict(mm, source='builtin', id='image-sft-template', catalog_id='template:image-sft', route={'path': '/m/multimodal'}))
        if self.c.data_library:
            path = self.c.data_library.root / 'multimodal_configs.json'
            # Reading the catalog never creates a config file.
            if path.is_file():
                for p in ResourceStore(path).list_all():
                    records.append(dict(p, source='user', catalog_id='multimodal:' + p['id'], route={'path': '/m/multimodal', 'query': {'config': p['id']}}))
        return records

    def _finish(self, resources):
        pipelines = self._pipelines()
        by_ref = {r['ref']: r for r in resources}
        mm_schema = by_ref.get('schema_ref:builtin-mm-qa-v1')
        if mm_schema:
            by_ref['builtin:mm-qa-schema-v1'] = mm_schema
        from app.services.resource_resolution import SCHEMA_PARAMS
        options = []
        for pipeline in pipelines:
            config = pipeline.get('config') or {}
            operators = config.get('operators') or []
            steps = config.get('steps') or []
            op_names = [op['name'] for op in operators] + [s['kind'].split(':')[-1] for s in steps]
            schema_ops = []
            for op in operators:
                declared = [p['name'] for p in _params(op)]
                if self.c.operator_registry:
                    details = self.c.operator_registry.get_op_details(op['name']) or {}
                    declared += [p['name'] for section in ('init', 'run') for p in details.get('parameter', {}).get(section, [])]
                if any(name in SCHEMA_PARAMS or name.endswith('_schema') for name in declared):
                    schema_ops.append(op['name'])
            if any(s['id'] == 'validate' for s in steps):
                schema_ops.append('platform:validate')
            options.append({'source': pipeline['source'], 'schema_operators': schema_ops, 'id': pipeline['catalog_id'], 'name': pipeline['name'], 'operators': op_names, 'route': pipeline['route']})
            def attach(ref, step, field, bindings=None):
                target = by_ref.get(ref)
                if target is None:
                    return
                usage = {'pipeline_id': pipeline['catalog_id'], 'pipeline_name': pipeline['name'], 'step': step,
                         'field': field, 'bindings': bindings or {}, 'route': pipeline['route']}
                if usage not in target['references']:
                    target['references'].append(usage)
            for index, op in enumerate(operators):
                for param in _params(op):
                    value = param.get('value')
                    ref = _reference(value)
                    if ref:
                        attach(ref, f"{index + 1}. {op['name']}", param['name'], value.get('bindings') if isinstance(value, dict) else None)
                    elif param.get('name') == 'prompt_template':
                        cls = value.get('cls_name') if isinstance(value, dict) else value
                        if isinstance(cls, str):
                            if "<class '" in cls:
                                cls = cls.split("'")[1].split('.')[-1]
                            attach('builtin_prompt:' + cls, f"{index + 1}. {op['name']}", 'prompt_template')
            for step in steps:
                attach(step.get('resource_ref'), step['id'], 'resource_ref', step.get('bindings'))
        return {'resources': resources, 'pipelines': options,
                'reference_scope': '引用来自已保存配置及内置流程的显式资源参数；不推断源码中的内联文本或未保存的默认参数。'}

    def prompts(self):
        records = []
        for item in self.c.user_prompt_registry.list_all():
            operators = ['FormatStrPromptedGenerator', 'PromptedVQAGenerator']
            allowed = item.get('allowed_operators') or []
            if allowed:
                operators = [op for op in operators if op in allowed]
            records.append(dict(copy.deepcopy(item), source='user', readonly=False, kind='text', ref='user_prompt:' + item['id'],
                                usages=[item.get('usage', '通用')], purpose=item.get('purpose', '通用'), operators=operators,
                                variables=_extract_placeholders(item['template']), references=[]))
        info = self.c.prompt_registry.list_prompt_info().model_dump()['prompts'] if self.c.prompt_registry else {}
        for name, item in info.items():
            usage = '文本 SFT' if name in TEXT_SFT or item['primary_type'] == 'text_sft' else '通用'
            records.append({'id': name, 'name': name, 'source': 'builtin', 'readonly': True, 'kind': 'python',
                            'ref': 'builtin_prompt:' + name, 'description': item['description'], 'usages': [usage],
                            'purpose': '清洗' if name == 'KnowledgeCleanerPrompt' else '评分' if name in TEXT_SFT - {'KnowledgeCleanerPrompt', 'Text2MultiHopQAGeneratorPrompt'} else '生成' if name == 'Text2MultiHopQAGeneratorPrompt' else '通用',
                            'operators': item['operator'], 'variables': [p['name'] for p in item['parameter']['build_prompt']],
                            'parameters': item['parameter'], 'class_path': item['class_str'], 'references': []})
        from app.services.multimodal_templates import QUESTION, ANSWER
        for key, name, text in [('mm-question-v1', '图片 SFT · 生成问题', QUESTION), ('mm-answer-v1', '图片 SFT · 回答问题', ANSWER)]:
            records.append({'id': key, 'name': name, 'source': 'builtin', 'readonly': True, 'kind': 'text', 'ref': 'builtin:' + key,
                            'description': '图片 VQA 流程的内置文本 Prompt；复制后可在图片流程中绑定自己的模板。',
                            'usages': ['图文 SFT'], 'purpose': '生成', 'operators': ['PromptedVQAGenerator'],
                            'template': text, 'variables': _extract_placeholders(text), 'references': [], 'version': 'v1'})
        return self._finish(records)

    def schemas(self):
        records = []
        for item in self.c.json_schema_manager.list_all() + builtin_schemas():
            own = item.get('source') != 'builtin'
            records.append(dict(copy.deepcopy(item), source='user' if own else 'builtin', readonly=not own,
                                ref='schema_ref:' + item['id'], resource_kind='schema', usages=[item.get('usage', '通用')],
                                purpose=item.get('purpose', '通用'), operators=[], references=[]))
        return self._finish(records)
