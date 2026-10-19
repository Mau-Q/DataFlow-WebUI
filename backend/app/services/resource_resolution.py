"""Shared resource resolution for validation, task freezing and both executors.

Only FormatStrPromptedGenerator has the verified arbitrary-field template
contract. Built-in prompt classes and inline values retain their old behavior.
"""
import copy
import hashlib
import json
from app.core.container import container
from app.services.json_schema_manager import validate_schema
from app.services.user_prompt_registry import _extract_placeholders, render_template

SCHEMA_PARAMS = {'schema', 'json_schema', 'output_schema', 'response_schema',
                 'structured_output_schema', 'response_format_schema'}


class ResourceReferenceError(ValueError):
    pass


def content_hash(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _ref(value):
    candidate = value.get('ref') if isinstance(value, dict) else value
    return candidate if isinstance(candidate, str) and candidate.startswith(('user_prompt:', 'schema_ref:')) else None


def _items(params):
    if isinstance(params, dict):
        return [{'name': k, 'value': v} for k, v in params.items()]
    return copy.deepcopy(params or [])


def _sections(op):
    raw = op.get('params') or {}
    details = container.operator_registry.get_op_details(op['name']) or {}
    definitions = details.get('parameter', {})
    init_names = {p['name'] for p in definitions.get('init', [])}
    if isinstance(raw, dict) and ('init' in raw or 'run' in raw):
        sections = {section: _items(raw.get(section)) for section in ('init', 'run')}
    else:
        sections = {'init': [], 'run': []}
        for item in _items(raw):
            sections['init' if item['name'] in init_names else 'run'].append(item)
    for section, items in sections.items():
        kinds = {p['name']: p.get('kind') for p in definitions.get(section, [])}
        for item in items:
            if kinds.get(item['name']):
                item.setdefault('kind', kinds[item['name']])
    return sections


def _bindings(run):
    mapping = {}
    for item in run:
        if item['name'] in ('storage', 'output_key'):
            continue
        value = item.get('value')
        if item['name'] == 'input_keys' or item.get('kind') == 'VAR_KEYWORD':
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise ResourceReferenceError('模板字段绑定必须是 JSON 对象或键值列表')
            for pair in _items(value):
                key = pair.get('name') or pair.get('key')
                if not isinstance(key, str) or not key or key in mapping:
                    raise ResourceReferenceError('模板字段绑定名称为空或重复')
                mapping[key] = pair.get('value')
        else:
            mapping[item['name']] = value
    return mapping


def resolve_pipeline_resources(config):
    """Return a detached executable config and frozen content+hash records.

    Resolve every resource once per submission; repeated references share the
    same captured record. Never write resolved text into the Pipeline registry.
    """
    result = copy.deepcopy(config)
    snapshots, captured = [], {}
    for index, op in enumerate(result.get('operators', [])):
        # Avoid normalizing legacy configs that contain no resource references.
        raw = op.get('params') or {}
        candidates = _items(raw.get('init')) + _items(raw.get('run')) if isinstance(raw, dict) and ('init' in raw or 'run' in raw) else _items(raw)
        has_schema = any(p.get('name') in SCHEMA_PARAMS and p.get('value') not in (None, '') for p in candidates)
        if not any(_ref(p.get('value')) for p in candidates) and not has_schema:
            continue
        sections = _sections(op)
        details = container.operator_registry.get_op_details(op['name']) or {}
        declared = {section: {p['name'] for p in details.get('parameter', {}).get(section, [])}
                    for section in ('init', 'run')}
        for section, params in sections.items():
            for item in params:
                value = item.get('value')
                ref = _ref(value)
                if not ref:
                    if item['name'] in SCHEMA_PARAMS and value is not None and value != '':
                        try:
                            validate_schema(value)
                        except ValueError as exc:
                            raise ResourceReferenceError(f"{op['name']}.{item['name']}: {exc}") from exc
                    continue
                name = item['name']
                if name not in declared[section]:
                    raise ResourceReferenceError(f"{op['name']}.{name}: 算子没有此参数契约")
                prefix, resource_id = ref.split(':', 1)
                if ref not in captured:
                    manager = container.user_prompt_registry if prefix == 'user_prompt' else container.json_schema_manager
                    record = manager.get(resource_id) if manager and resource_id else None
                    if record is None:
                        raise ResourceReferenceError(f'资源引用不存在: {ref}')
                    captured[ref] = copy.deepcopy(record)
                record = captured[ref]
                if prefix == 'user_prompt':
                    if op['name'] != 'FormatStrPromptedGenerator' or name != 'prompt_template' or section != 'init':
                        raise ResourceReferenceError(f"{op['name']}.{name}: 不支持自定义模板；保留内置 Prompt，或使用 FormatStrPromptedGenerator")
                    allowed = record.get('allowed_operators') or []
                    if allowed and op['name'] not in allowed:
                        raise ResourceReferenceError(f"模板未允许算子 {op['name']}")
                    if isinstance(value, dict) and 'bindings' in value:
                        binding = value['bindings']
                        if not isinstance(binding, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in binding.items()):
                            raise ResourceReferenceError('模板绑定必须是 变量名 → 非空数据列名')
                        if any(k in ('storage', 'output_key', 'input_keys') for k in binding):
                            raise ResourceReferenceError('模板变量不能使用 storage、output_key 或 input_keys')
                        sections['run'] = [p for p in sections['run'] if p['name'] != 'input_keys']
                        sections['run'].append({'name': 'input_keys', 'kind': 'VAR_KEYWORD', 'value': _items(binding)})
                    binding = _bindings(sections['run'])
                    required = _extract_placeholders(record['template'])
                    missing = [p for p in required if not isinstance(binding.get(p), str) or not binding[p].strip()]
                    if missing:
                        raise ResourceReferenceError('模板缺少变量绑定: ' + ', '.join(missing))
                    # Do not allow arbitrary kwargs to shadow named run parameters.
                    if any(k in ('storage', 'output_key', 'input_keys') for k in binding):
                        raise ResourceReferenceError('模板变量不能使用 storage、output_key 或 input_keys')
                    if not record['template'].strip():
                        raise ResourceReferenceError('模板内容不能为空')
                    content = {'template': record['template']}
                    item['value'] = {'cls_name': 'FormatStrPrompt', 'resource_template': record['template']}
                else:
                    if name not in SCHEMA_PARAMS and not name.endswith('_schema'):
                        raise ResourceReferenceError(f'{name}: 不是声明结构输出的 Schema 参数')
                    try:
                        content = validate_schema(record['schema'])
                    except ValueError as exc:
                        raise ResourceReferenceError(f'{ref}: {exc}') from exc
                    item['value'] = content
                snapshots.append({'operator_index': index, 'operator_name': op['name'],
                                  'section': section, 'param_name': name, 'ref': ref,
                                  'name': record['name'], 'updated_at': record.get('updated_at'),
                                  'content': copy.deepcopy(content), 'sha256': content_hash(content)})
        op['params'] = sections
    return result, snapshots


def instantiate_prompt(value):
    """Common constructor, preserving built-in registry semantics."""
    from dataflow.utils.registry import PROMPT_REGISTRY
    if isinstance(value, dict) and 'resource_template' in value:
        from dataflow.core.prompt import DIYPromptABC
        class ResourceTemplatePrompt(DIYPromptABC):
            def build_prompt(self, need_fields, **kwargs):
                rendered = render_template(value['resource_template'], kwargs)
                if rendered['missing']:
                    raise ResourceReferenceError('模板缺少变量: ' + ', '.join(rendered['missing']))
                return rendered['rendered']
        return ResourceTemplatePrompt()
    if isinstance(value, dict):
        cls_name = value.get('cls_name', 'FormatStrPrompt')
        kwargs = {p['name']: p.get('value') if p.get('value') is not None else p.get('default_value')
                  for p in value['params']} if 'params' in value else {k: v for k, v in value.items() if k != 'cls_name'}
    else:
        cls_name, kwargs = value, {}
    if isinstance(cls_name, str) and "<class '" in cls_name:
        cls_name = cls_name.split("'")[1].split('.')[-1]
    cls = PROMPT_REGISTRY.get(cls_name)
    if not cls:
        raise ResourceReferenceError(f'Prompt class not found: {cls_name}')
    return cls(**kwargs)
