# 四个代表性 API 数据生成流程

这组流程替换旧的四条「最简」连通性模板。输入、API 配置、输出目录和真实运行由你在 WebUI 操作。
本目录没有自动导入脚本，也不包含提前生成的训练成品；不需要下载本地大模型或使用 GPU。

## 输入材料

- `text-one.jsonl`：1 条技术说明，建议先用它试跑。
- `text.jsonl`：9 条输入，包括 6 份技术说明、1 条精确重复、1 条过短材料和 1 条空白材料。
- `images/`：6 张合成图片，包括实验室使用表、模型指标表、缓存延迟图、数据保留数量图、处理顺序图和失败重试图。
- `manual-reference.json`：人工核对依据，不导入 pipeline，避免把参考答案当作生成输入。

文本材料包含采样与存储量、LRU、训练验证测试划分、精确率召回率、数据版本和任务重试。图片中的数值是明确标注的模拟数据。

## WebUI 操作

1. 在服务管理中配置 `APILLMServing_request`。`api_url` 需要完整的 OpenAI 兼容 Chat Completions 地址，以 `/chat/completions` 结尾。图片流程需要支持图片内容块与 base64 data URL 的模型。
2. 在「原始数据集」的结构化文件入口导入 `text-one.jsonl` 或 `text.jsonl`。图片则通过 PDF/图片材料入口选择 `images/` 内的 PNG，生成拥有 `source/material_id` 的材料清单。
3. 进入「Pipeline → 模板」，选择对应的「代表性」模板；从画布选择刚导入的输入数据集。
4. 打开每个模型算子的参数详情，给所有 `llm_serving` 选择服务。可以共用一个多模态服务，也可以给生成与评价分别选择服务。不要只给第一个算子配置。
5. 保留默认 Prompt 引用、Schema 引用和字段绑定，先保存为自己的 pipeline。原模板初始没有绑定任何输入或 API。
6. 点击「Save & Run」，在运行确认弹窗选择本地输出文件夹，再由你提交运行。
7. 在运行记录检查各步骤条数、中间候选、评分、过滤结果和最终文件；核对后手动收录到生成数据集。

直接入口：

- [代表性文本 SFT](http://127.0.0.1:8000/#/m?pipeline=representative-text-sft-v1)
- [代表性文本 DPO](http://127.0.0.1:8000/#/m?pipeline=representative-text-dpo-v1)
- [代表性图片 SFT](http://127.0.0.1:8000/#/m?pipeline=representative-image_text-sft-v1)
- [代表性图片 DPO](http://127.0.0.1:8000/#/m?pipeline=representative-image_text-dpo-v1)

旧的 M5「图片 VQA」配置草稿入口仍独立保留；本次实际 API 验收使用上述新模板。

## 四条实际算子链

### 文本 SFT：10 步，2 个模型算子

```text
GeneralFilter → HashDeduplicateFilter → PandasOperator → RemoveExtraSpacesRefiner
→ Text2MultiHopQAGenerator → TrainingQAExpander
→ Text2QASampleEvaluator → GeneralFilter
→ HashDeduplicateFilter → TrainingPairFormatter
```

先按长度和句子数筛选输入，再精确去重；复制原文后用本地规则规范空白，保留事实和数字，不额外调用模型。多跳 QA 算子关联相邻事实，最多为每份材料保留一个 QA。
`TrainingQAExpander` 展开嵌套 `qa_pairs`，保留原文及证据。原生四维评分分别检查问题质量、回答对齐、可验证性和学习价值，其中可验证性使用原始 `text`，而非清洗稿。
默认要求问题/学习价值至少 3 分，对齐/可验证性至少 4 分，之后按来源与候选去重并整理为 `instruction/input/output`。

### 文本 DPO：13 步，3 个模型算子

```text
GeneralFilter → HashDeduplicateFilter → PandasOperator → RemoveExtraSpacesRefiner
→ Text2MultiHopQAGenerator → TrainingQAExpander
→ FormatStrPromptedGenerator（独立回答 B）
→ TrainingPreferenceBuilder
→ FormatStrPromptedGenerator（原文评价）
→ TrainingReviewParser → GeneralFilter
→ HashDeduplicateFilter → TrainingPairFormatter
```

多跳 QA 提供问题和回答 A；回答 B 使用原问题与原文独立生成，不读取回答 A，也不被要求故意答错。
之后单独评价两个回答，输出各自分数和来源支持判断。程序根据分数排序得到 `chosen/rejected`，而非默认 A 更好。
优选回答必须有来源支持、至少 4 分，且分差至少 1 分；同分、分差不足、相同回答、无效评价均不收录。
最终为 `prompt/chosen/rejected`，prompt 含原始材料和问题。

### 图片 SFT：8 步，3 个模型算子

```text
HashDeduplicateFilter
→ APIImagePairGenerator（问题）
→ APIImagePairGenerator（回答）
→ APIImagePairGenerator（独立看图评价）
→ TrainingReviewParser → GeneralFilter
→ HashDeduplicateFilter → TrainingPairFormatter
```

三个模型调用分别看同一张固定图片。回答必须保留原问题，评价再次看图核对答案的事实、数字、单位和条件。
至少 4 分且有图片依据才通过，输出 `messages/images`。源图片与材料关联随任务固定，输出目录包含可读取的图片副本。

### 图片 DPO：10 步，4 个模型算子

```text
HashDeduplicateFilter
→ APIImagePairGenerator（问题）
→ APIImagePairGenerator（回答 A）
→ APIImagePairGenerator（独立回答 B）
→ TrainingPreferenceBuilder
→ APIImagePairGenerator（独立看图评价 A/B）
→ TrainingReviewParser → GeneralFilter
→ HashDeduplicateFilter → TrainingPairFormatter
```

两个回答采用完整解释、简洁作答的不同要求，但都要求正确且有图片依据；不预先指定哪一个更好。
评价调用同时读取图片与两个候选，使用与文本 DPO 相同的准入边界，输出 `prompt/chosen/rejected/images`。

## 哪些复用、哪些新增

复用现有的 `GeneralFilter`、`HashDeduplicateFilter`、`PandasOperator`、`RemoveExtraSpacesRefiner`、`Text2MultiHopQAGenerator`、`Text2QASampleEvaluator` 和 `FormatStrPromptedGenerator`。
图片继续复用已有 API 适配 `APIImagePairGenerator`，增加可绑定上游问题/候选的输入；格式整理继续复用 `TrainingPairFormatter`。
新增三个不调用模型的协议适配算子：展开嵌套 QA、组合同题 A/B、解释评价及准入。没有引入新执行器，也没有安装完整 GPU 多模态依赖。

## 预期条数与验收重点

- `text-one.jsonl`：输入 1 条，最多输出 1 条。
- `text.jsonl`：输入 9 条，长度/句子过滤后 7 条，来源去重后 6 条；最多生成 6 条，评分后可能进一步减少。
- 6 张图片：最多输出 6 条，实际数量取决于生成和评价结果。
- **全部被过滤也应成功完成**，保存空的 `final.jsonl` 和中间证据；界面应显示 0 条且不能收录为空数据集。
- 查看 DPO 的原始 A/B、独立评价、`accepted` 和 `admission_reason`；优选可以来自 A，也可以来自 B。禁止为凑数量强造偏好对。
- 查看文本清洗是否改动了数字或条件，并按 `manual-reference.json` 抽查最终回答。结构正确和模型高分都不保证事实正确。

建议先分别运行单条文本和一张图片，再运行完整输入。完整输入在不发生请求重试的情况下：文本 SFT 最多约 30 次请求，文本 DPO 约 18 次，图片 SFT 18 次，图片 DPO 24 次；具体取决于前面阶段保留的条数。四维评分本身包含四类评价调用。

## 输出、资源与历史

输出目录每次运行有独立子目录，包含 `final.jsonl`、`manifest.json`、日志、每步中间结果与模型响应；图片任务还包含 `images/`。
收录仍由你手动选择新建或追加，保留来源、图片关联和去重；编辑生成数据集不会反向改变历史任务文件。

Prompt 与 Schema 均在各自管理器中独立保存。提交时固定内容及哈希；后续编辑只影响新任务。删除被引用资源会阻止新提交，不会被重启静默重建。
旧四条「最简」模板和旧样例已替换；旧模板配置和资源先备份再移除，用户自己的副本、任务、数据和 API 服务不受迁移影响。

独立评价指分开的调用和评价提示词，可以选择同一模型或不同服务，不能据此声称具备人工标注质量或训练收益。
本地隔离测试替换模型响应，验证算子执行、快照、过滤、平局、空结果、落盘、收录和迁移；真实 API 兼容性与质量由你运行验收。

图片与文本可用 `generate_samples.py` 在本地重新生成；脚本需要本地中文字体，不联网、不导入数据库。
