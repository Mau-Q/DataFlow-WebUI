# 四个最简 API 生成流程的本地验收

这份目录只提供原始输入，不会导入数据库，不会创建任务，不包含模型生成的成品数据。
无需下载本地模型或使用 GPU。API、导入、输出目录及真实运行由你在 WebUI 操作。

## 1. 配置 API

在 WebUI 服务管理中创建 `APILLMServing_request` 服务，填写模型名、密钥和完整的
OpenAI 兼容 Chat Completions 地址（通常以 `/v1/chat/completions` 结尾，不能只填域名）。
图片两条需要支持 `image_url` 内容块和 base64 data URL 的视觉模型。
文本和图片可以共用一个支持两种输入的模型，也可以分别配置服务。
密钥只在服务管理中填写，不写进 pipeline 或样例文件。

## 2. 自己导入两组原始输入

- 文本：在「原始数据集」的结构化文件导入入口，选择本目录的 `text.jsonl`，命名如「最简验收·文本」。它有 3 行，每行包含 `id` 和 `text`。
- 图片：在「原始数据集」的 PDF/图片材料导入入口，同时选择 `images/` 内的 3 张 PNG，命名如「最简验收·图片」。系统会保存图片材料及带 `source/material_id` 的输入清单。

不要将整个本目录作为混合文件夹导入，也不要把 PNG 作为训练成品导入「生成数据集」。
两条文本流程共用文本输入；两条图片流程共用图片输入。

## 3. 选择模板并保存自己的 pipeline

打开画布顶部「Pipeline → 模板」，选择以下四条之一：

| 模板 | 两步顺序 | 输入 | 最终格式 |
| --- | --- | --- | --- |
| 最简文本 SFT | FormatStrPromptedGenerator → TrainingPairFormatter | text.jsonl | instruction/input/output |
| 最简文本 DPO | FormatStrPromptedGenerator → TrainingPairFormatter | text.jsonl | prompt/chosen/rejected |
| 最简图片 SFT | APIImagePairGenerator → TrainingPairFormatter | 已导入的图片材料清单 | messages/images |
| 最简图片 DPO | APIImagePairGenerator → TrainingPairFormatter | 已导入的图片材料清单 | prompt/chosen/rejected/images |

也可以直接打开：

- [最简文本 SFT](http://127.0.0.1:8000/#/m?pipeline=simple-text-sft-v1)
- [最简文本 DPO](http://127.0.0.1:8000/#/m?pipeline=simple-text-dpo-v1)
- [最简图片 SFT](http://127.0.0.1:8000/#/m?pipeline=simple-image_text-sft-v1)
- [最简图片 DPO](http://127.0.0.1:8000/#/m?pipeline=simple-image_text-dpo-v1)

模板初始没有输入数据集和服务。提示尚未选择输入是正常状态：

1. 从画布「原始数据集」选择刚导入的对应数据集。
2. 点击第一步算子的「参数详情」，为 `llm_serving` 选择 API 服务。
3. 保留已选的 Prompt、第二步的 Schema 及字段绑定。文本绑定为 `text → text`；图片输入字段为 `source`。
4. 点击「保存」，为自己的 pipeline 命名。模板本身不会被覆盖。
5. 点击「Save & Run」，在运行确认弹窗选择本地输出文件夹，再提交。

旧「自定义 Pipeline → 图片 VQA」仍保留为 M5 配置草稿入口；本次真实 API 验收使用上面的两个「最简图片」模板。

每行输入生成一个样本，因此全部成功时每条 pipeline 应有 3 条结果。
如果一条候选不是合法 JSON、缺少字段或 DPO 两个回答相同，第二步会明确失败，不会静默补答案或把中间候选当训练成品。

## 4. 检查结果、收录和导出

运行记录 → 最终结果应显示条数、预览、本地文件位置、SHA-256 和下载入口。
所选输出根目录下每次运行有独立子目录：

```text
本次任务目录/
  final.jsonl             # 仅训练字段
  manifest.json          # 文件清单与校验值
  logs.json
  artifacts/             # 原始模型响应、候选、训练产物
  intermediate/          # 两个步骤的输出
  images/                # 图片任务才有；final.jsonl 使用相对引用
```

检查后手动点击「收录到生成数据集」的新建或追加。图片默认关联本次任务实际使用的已导入材料，仍可在收录界面核对。
再点一次收录应复用已有结果，不增加重复样本。刷新后检查分类、条数、来源任务和图片预览。
生成数据集是独立草稿，收录后的编辑不会反写历史任务的 `final.jsonl`；后续导出使用数据集发布功能。

## 5. 人工核对事实

| 文件 | 事实 |
| --- | --- |
| 01-shapes.png | 左边红色正方形，中间蓝色圆形，右边绿色三角形，共 3 个图形 |
| 02-count.png | 上方两个蓝色圆形，下方一个红色正方形，没有三角形 |
| 03-position.png | 左上绿色三角形，右上红色正方形，下方中央蓝色圆形 |

`text.jsonl` 与三张图分别描述同一场景。SFT 答案应有依据；DPO 的 chosen 应正确，rejected 应含明确可核对的错误。
DPO 是用于流程验收的合成偏好对，结构校验不能证明偏好质量。请逐条检查后再用于训练。

## Prompt / Schema 解耦验收

四份生成提示词和四份候选 Schema 会独立出现在 Prompt、Schema 管理中，名称与模板对应。
pipeline 保存资源 ID；提交任务时固定内容和哈希。编辑资源影响下一次新任务，不改变已有任务快照。
文本 Prompt 保留 `{text}` 和对应绑定；图片 Prompt 不使用变量，图片由程序附加。
更换 Schema 不能解除必填训练字段、图片关联或 chosen/rejected 不同的程序约束。

## 已验证与待验证边界

自动测试在临时数据库、注册表和目录中替换模型调用，检查真实算子执行、API 图片消息结构、输入快照、输出落盘、收录和去重。
没有调用你的真实 API，没有替你导入原始数据、选择输出目录或点击运行。
具体提供商的兼容性、模型事实正确性和实际运行耗时，需要你配置 API 后验收。

图片可通过 `generate_samples.py` 重新生成，脚本只使用 Pillow，不访问网络。
