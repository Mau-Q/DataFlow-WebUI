"""Small native operators for API-only image generation and training formatting.

No DataFlow-MM import: its local GPU imports are unnecessary for an HTTP API.
Text generation continues to use FormatStrPromptedGenerator.
"""
import base64
import io
import json
import re
from pathlib import Path

from PIL import Image
from jsonschema import validators
from dataflow.core import OperatorABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage


def image_data(path):
    path = Path(path)
    content = path.read_bytes()
    if len(content) > 10 * 1024 * 1024:
        raise ValueError('示例图片最多 10 MiB')
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
        mime = Image.MIME.get(image.format)
    if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
        raise ValueError('API 示例仅接受 PNG、JPEG、WebP 图片')
    return f'data:{mime};base64,' + base64.b64encode(content).decode('ascii')


@OPERATOR_REGISTRY.register()
class APIImagePairGenerator(OperatorABC):
    WEBUI_CATEGORY = ('core_vision', 'generate')
    def __init__(self, llm_serving, prompt_template=None):
        super().__init__()
        self.llm_serving = llm_serving
        self.prompt_template = prompt_template

    @staticmethod
    def get_desc(lang='zh'):
        return '通过 OpenAI 兼容视觉 API 从图片生成训练候选 JSON；无需本地模型。' if lang == 'zh' else 'Generate training candidate JSON using an image API.'

    def run(self, storage: DataFlowStorage, input_image_key='source', output_key='candidate', input_context_key: str = None):
        frame = storage.read('dataframe')
        if input_image_key not in frame:
            raise ValueError(f'Missing {input_image_key}; available columns: {list(frame.columns)}')
        if self.prompt_template is None:
            raise ValueError('请选择图片生成 Prompt')
        if output_key in frame:
            raise ValueError('候选输出不能覆盖已有字段')
        if input_context_key and input_context_key not in frame:
            raise ValueError(f'Missing {input_context_key}; available columns: {list(frame.columns)}')
        prompt = self.prompt_template.build_prompt()
        conversations = []
        for _, row in frame.iterrows():
            context = row[input_context_key] if input_context_key else None
            if input_context_key:
                try:
                    context = parse_candidate(context)
                except (ValueError, TypeError):
                    raise ValueError('上游问题或候选不是有效 JSON 对象；未调用下一步视觉 API') from None
                if not isinstance(context.get('question'), str) or not context['question'].strip():
                    raise ValueError('上游问题或候选缺少 question；未调用下一步视觉 API')
            extra = '' if context is None else '\n待处理输入：\n' + (context if isinstance(context,str) else json.dumps(context,ensure_ascii=False,allow_nan=False))
            conversations.append([{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt + extra},
                {'type': 'image_url', 'image_url': {'url': image_data(row[input_image_key])}},
            ]}])
        if not conversations:
            frame[output_key] = []
            storage.write(frame)
            return [output_key]
        responses = self.llm_serving.generate_from_conversations(conversations)
        if len(responses) != len(frame):
            raise ValueError('视觉 API 返回条数与输入不一致')
        frame[output_key] = responses
        storage.write(frame)
        return [output_key]


def parse_candidate(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError('模型未返回 JSON 文本')
    value = value.strip()
    wrapped = re.fullmatch(r'<think>.*?</think>\s*<answer>(.*?)</answer>', value, re.S)
    if wrapped:
        value = wrapped.group(1).strip()
    # Accept common fenced JSON, but never extract a guessed object from prose.
    match = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', value, re.S)
    if match:
        value = match.group(1)
    result = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法 JSON 数值')))
    if not isinstance(result, dict):
        raise ValueError('候选必须是 JSON 对象')
    return result


@OPERATOR_REGISTRY.register()
class TrainingPairFormatter(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')
    def __init__(self, training_type='sft', modality='text', json_schema=None, allow_empty: bool = False):
        super().__init__()
        if training_type not in {'sft', 'dpo'} or modality not in {'text', 'image_text'}:
            raise ValueError('训练类型或模态无效')
        if json_schema is None:
            raise ValueError('请选择候选 JSON Schema')
        self.training_type, self.modality = training_type, modality
        self.allow_empty = allow_empty
        cls = validators.validator_for(json_schema)
        cls.check_schema(json_schema)
        self.validator = cls(json_schema)

    @staticmethod
    def get_desc(lang='zh'):
        return '校验候选 JSON 并整理为 SFT/DPO；错误样本使任务失败，原始响应保留在运行记录。' if lang == 'zh' else 'Validate candidates and format SFT/DPO training samples.'

    def run(self, storage: DataFlowStorage, input_key='candidate', output_key='training_sample'):
        from app.services.data_library import DataLibrary
        frame = storage.read('dataframe')
        if input_key not in frame:
            raise ValueError(f'Missing {input_key}; available columns: {list(frame.columns)}')
        rows = []
        for index, row in frame.iterrows():
            try:
                pair = parse_candidate(row[input_key])
                self.validator.validate(pair)
                required = ['question', 'answer'] if self.training_type == 'sft' else ['question', 'chosen', 'rejected']
                if any(not isinstance(pair.get(k), str) or not pair[k].strip() for k in required):
                    raise ValueError('候选缺少非空问题或回答')
                question = pair['question'].strip()
                if self.training_type == 'dpo':
                    sample = dict(prompt=question, chosen=pair['chosen'].strip(), rejected=pair['rejected'].strip())
                else:
                    sample = dict(instruction=question, input=row.get('text', ''), output=pair['answer'].strip())
                if self.modality == 'text' and self.training_type == 'dpo':
                    sample['prompt'] = f'依据以下材料：\n{row["text"]}\n问题：{question}'
                if self.modality == 'image_text':
                    ref = row.get('media_ref')
                    if not isinstance(ref, str) or not ref:
                        raise ValueError('缺少固定图片引用，请通过运行入口提交')
                    if self.training_type == 'sft':
                        sample = {'messages': [
                            {'role': 'user', 'content': [
                                {'type': 'image_url', 'image_url': {'url': ref}},
                                {'type': 'text', 'text': question}]},
                            {'role': 'assistant', 'content': pair['answer'].strip()}]}
                    sample['images'] = [ref]
                DataLibrary._validate_row(None, sample, self.modality, self.training_type)
                rows.append(sample)
            except Exception as exc:
                # Avoid echoing API bodies, model reasoning, or any credentials.
                raise ValueError(f'第 {len(rows)+1} 条候选不符合训练契约（{type(exc).__name__}）；请检查上一步候选和 Schema') from None
        if not rows and not self.allow_empty:
            raise ValueError('输入为空，不能生成空训练数据集')
        # Preserve intermediate columns for field-flow inspection; finalization
        # extracts the explicit training_sample rather than guessing columns.
        frame[output_key] = rows
        storage.write(frame)
        return [output_key]
