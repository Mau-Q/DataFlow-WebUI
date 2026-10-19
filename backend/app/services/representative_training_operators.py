"""Protocol adapters around reused generation, evaluation and filtering operators."""
import json
import math
import pandas as pd
from jsonschema import validators
from dataflow.core import OperatorABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage
from app.services.simple_training_operators import parse_candidate


def required_columns(frame, *columns):
    missing = [key for key in columns if key and key not in frame]
    if missing:
        raise ValueError(f'Missing {missing}; available columns: {list(frame.columns)}')


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


@OPERATOR_REGISTRY.register()
class TrainingQAExpander(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    @staticmethod
    def get_desc(lang='zh'):
        return '展开多跳 QA 列表，保留来源和生成证据，将问题和回答绑定为独立字段。' if lang == 'zh' else 'Expand QA lists while preserving source evidence.'

    def run(self, storage: DataFlowStorage, input_key='qa_pairs', output_key='candidate', output_question_key='question', output_answer_key='answer'):
        frame = storage.read('dataframe')
        if not frame.empty:
            required_columns(frame, input_key)
        rows = []
        for _, row in frame.iterrows():
            pairs = row[input_key]
            if not isinstance(pairs, list):
                raise ValueError('多跳 QA 输出必须为列表')
            for pair in pairs:
                if not isinstance(pair, dict) or not all(nonempty(pair.get(k)) for k in ('question', 'answer')):
                    raise ValueError('多跳 QA 含无效问题或回答；请检查上一步输出')
                rec = row.to_dict()
                rec.update({output_key: {'question': pair['question'], 'answer': pair['answer']},
                            output_question_key: pair['question'], output_answer_key: pair['answer']})
                rows.append(rec)
        columns = list(dict.fromkeys([*frame.columns, output_key, output_question_key, output_answer_key]))
        storage.write(pd.DataFrame(rows, columns=columns))
        return [output_key, output_question_key, output_answer_key]


@OPERATOR_REGISTRY.register()
class TrainingPreferenceBuilder(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    @staticmethod
    def get_desc(lang='zh'):
        return '组合独立生成的 A/B 回答，检查问题一致性；不预先指定优选回答。' if lang == 'zh' else 'Combine independently generated answers without preassigning preference.'

    def run(self, storage: DataFlowStorage, input_key='candidate_a', input_alternative_key='candidate_b', output_key='alternatives'):
        frame = storage.read('dataframe')
        required_columns(frame, input_key, input_alternative_key)
        values = []
        for index, (_, row) in enumerate(frame.iterrows(), 1):
            try:
                a, b = parse_candidate(row[input_key]), parse_candidate(row[input_alternative_key])
                if not all(nonempty(p.get(k)) for p in (a, b) for k in ('question', 'answer')):
                    raise ValueError('缺少问题或回答')
                if a['question'].strip() != b['question'].strip():
                    raise ValueError('候选回答使用了不同问题')
                values.append(dict(question=a['question'].strip(), answer_a=a['answer'].strip(), answer_b=b['answer'].strip()))
            except (ValueError, TypeError, KeyError):
                raise ValueError(f'第 {index} 条候选回答无法组成同题偏好对；请检查候选 A/B') from None
        frame[output_key] = values
        storage.write(frame)
        return [output_key]


@OPERATOR_REGISTRY.register()
class TrainingReviewParser(OperatorABC):
    WEBUI_CATEGORY = ('core_text', 'refine')

    def __init__(self, training_type='sft', json_schema=None, min_score: float = 4, min_gap: float = 1):
        super().__init__()
        if training_type not in {'sft', 'dpo'}:
            raise ValueError('训练类型无效')
        if not (isinstance(min_score, (int, float)) and not isinstance(min_score, bool) and math.isfinite(min_score) and 1 <= min_score <= 5):
            raise ValueError('min_score 必须在 1–5 之间')
        if not (isinstance(min_gap, (int, float)) and not isinstance(min_gap, bool) and math.isfinite(min_gap) and 0 < min_gap <= 4):
            raise ValueError('min_gap 必须大于 0 且不超过 4')
        if not isinstance(json_schema, dict):
            raise ValueError('请选择评价结果 Schema')
        cls = validators.validator_for(json_schema)
        cls.check_schema(json_schema)
        self.validator = cls(json_schema)
        self.training_type, self.min_score, self.min_gap = training_type, min_score, min_gap

    @staticmethod
    def get_desc(lang='zh'):
        return '解析独立评价；检查图片问题一致性，按分数和来源依据决定是否准入；平局、无效评价不生成 DPO。' if lang == 'zh' else 'Parse reviews and admit only grounded, decisive preferences.'

    def run(self, storage: DataFlowStorage, input_key='review', input_candidate_key='candidate', input_question_key=None,
            output_key='accepted', output_candidate_key='candidate', output_reason_key='admission_reason'):
        frame = storage.read('dataframe')
        required_columns(frame, input_key, input_candidate_key, input_question_key)
        decisions, candidates, reasons = [], [], []
        for _, row in frame.iterrows():
            accepted, candidate, reason = False, {}, 'invalid_review'
            try:
                review = parse_candidate(row[input_key])
                self.validator.validate(review)
                source = parse_candidate(row[input_candidate_key])
                if not nonempty(source.get('question')):
                    raise ValueError('问题为空')
                if input_question_key:
                    question = parse_candidate(row[input_question_key]).get('question')
                    if not nonempty(question) or question.strip() != source['question'].strip():
                        raise ValueError('生成回答时问题发生变化')
                if self.training_type == 'sft':
                    if not nonempty(source.get('answer')):
                        raise ValueError('回答为空')
                    score = review['score']
                    if type(score) not in (int, float) or not math.isfinite(score) or not 1 <= score <= 5 or type(review['grounded']) is not bool:
                        raise ValueError('评价字段类型无效')
                    candidate = source
                    accepted = score >= self.min_score and review['grounded']
                    reason = 'accepted' if accepted else 'low_score_or_ungrounded'
                else:
                    a, b = source['answer_a'], source['answer_b']
                    scores = [review['score_a'], review['score_b']]
                    grounded = [review['grounded_a'], review['grounded_b']]
                    if not all(nonempty(v) for v in (a,b)) or any(type(s) not in (int,float) or not math.isfinite(s) or not 1 <= s <= 5 for s in scores) or any(type(g) is not bool for g in grounded):
                        raise ValueError('候选或评价字段类型无效')
                    winner = 0 if scores[0] > scores[1] else 1
                    accepted = (a.strip() != b.strip() and abs(scores[0]-scores[1]) >= self.min_gap
                                and scores[winner] >= self.min_score and grounded[winner])
                    candidate = dict(question=source['question'], chosen=(a,b)[winner], rejected=(a,b)[1-winner]) if accepted else {}
                    reason = 'accepted' if accepted else 'tie_small_gap_identical_or_ungrounded'
            except Exception:
                # Invalid reviews are explicit rejections, never inferred scores.
                pass
            decisions.append(accepted); candidates.append(candidate); reasons.append(reason)
        frame[output_key], frame[output_candidate_key], frame[output_reason_key] = decisions, candidates, reasons
        storage.write(frame)
        return [output_key, output_candidate_key, output_reason_key]
