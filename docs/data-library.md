# 原始材料与训练数据集（M1）

侧栏提供「原始数据集」和「生成数据集」两个入口，分别对应 `/#/m/materials` 和 `/#/m/training-datasets`。旧 DataFlow Hub、输入数据集和 Pipeline 保留原有入口与注册语义。

## 原始材料

1. 点击原始数据集页「添加数据集」，或原画布「数据集 → 添加」，选择 PDF / 图片并填写名称。平台保存文件副本并生成兼容的输入清单。
2. 在全宽列表点击数据集名称进入详情，切换文件并预览 PDF / 图片。已有 JSON / JSONL / CSV / Parquet 也可通过同一表单单独添加。
3. 新上传文件的分组、来源、说明及解析产物关系在「编辑文件信息」中按需展开；后台仍保留本地路径登记 API。

第一批支持 PDF、PNG、JPEG、WebP、GIF、BMP；公式、表格通过这些原文件或解析后的图片管理。此阶段不运行解析、不新建公式或表格编辑器，不接受任意解析格式。PDF 需能解析且未加密；图片按实际格式检查，不能仅改扩展名。每份上限 100 MiB。

不同内容即使文件名相同也使用不同 ID 和存储路径。相同字节内容会提示已存在的材料，不静默覆盖。文件访问按 ID 查找并校验哈希，缺失或内容变化会报错。

## 训练数据集草稿

1. 创建草稿，分别选择模态（文本 / 图文）与训练类型（当前为 SFT）。
2. 选择 UTF-8 JSON 数组文件或逐行 JSONL 文件导入，上限 20 MiB。
3. 查看字段集合、每页 20 条的原始样本预览、图片预览和导入记录。

支持两种基本 SFT 形状，保留原始字段及额外字段，不自动映射或改写正文：

```json
[{"instruction": "问题", "input": "可选上下文", "output": "答案"}]
```

```json
[{"messages": [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "答案"}]}]
```

`instruction`、`output` 必须为非空字符串；`input` 存在时必须为字符串。`messages` 必须含 user 和 assistant 消息；支持 system、user、assistant、tool 角色，内容为非空文本或 text / image_url 内容块。这里只检查基本结构，不评价答案质量，不执行任意 JSON Schema。

图文样本必须包含图片引用，文本样本不能含图片引用。支持 `image` 字符串、`images` 字符串数组，或 messages 中的 `image_url` 内容块：

```json
[{"instruction": "图中是什么？", "output": "一张图表。", "images": ["images/chart.png"]}]
```

先通过原始数据集入口导入图片，再在生成数据集的导入对话框中为每个引用选择图片；高级入口仍支持明确的 JSON 映射（将示例 ID 换为实际图片 ID）：

```json
{"images/chart.png": "mat_0123456789abcdef0123456789abcdef"}
```

不会根据同名文件搜索路径，也不会下载远程 URL。即使引用写成 URL，也必须显式绑定已导入的图片。相同草稿内，同一引用不能重新绑定另一张图；已有映射可供后续批次复用。缺少映射、文件缺失、哈希改变、引用 PDF 而非图片都会阻止导入。

全批结构与媒体检查通过后一次写入；失败提示第几条样本，已有草稿不变。重复文件内容会拒绝；批次内或与已有样本完全相同的 JSON 对象会跳过，并报告数量。仅对象字段顺序不同仍视为重复；含不同额外字段则是不同样本。每次有效导入保存规范化内容哈希、原文件哈希、文件名与新增/跳过数量。

当前已提供创建、导入、预览、样本编辑、发布冻结和数据/媒体打包导出。编辑与发布步骤见 [任务与发布说明](text-generation-and-releases.md)。DPO 不显示为当前支持的训练类型。

## 存储、备份与 API

默认路径为 `backend/data/library/`，可随现有 `BASE_DIR` / `RESOURCE_DIR` 配置改变：

- `materials/<material_id>.json`：名称、分组、来源、关联材料、格式、哈希和存储文件名。
- `materials/<material_id>.<suffix>`：平台保存的原文件副本。
- `drafts/<dataset_id>.json`：模态、训练类型、草稿样本、媒体绑定和导入记录。
- `.lock`：线程和进程之间的写入锁（当前支持 macOS / Linux）。

写入通过临时文件、fsync 和原子替换完成；损坏的 JSON 元数据会报错，不会自动重建空库。备份时停止后端并复制完整 `library/`，不能只备份 JSON 而遗漏图片。M1 面向本地小批量数据，草稿按文件保存；分页只限制响应大小，不代表已具备大规模数据集数据库能力。

旧 `DatasetRegistry` 不扫描材料目录；通过原始数据集导入表单添加 PDF / 图片时，由薄适配登记输入清单。已有注册记录保留，不做全量迁移。

API 前缀为 `/api/v1/library`，使用现有 ApiResponse 封装。业务失败在应用中通常仍返回 HTTP 200，调用方需检查 `success` 及 `meta.http_status`：

| 操作 | 路径 |
| --- | --- |
| 材料列表 | GET `/materials` |
| 上传材料（file + metadata JSON 字符串） | POST `/materials/upload` |
| 登记本地路径（JSON body） | POST `/materials/register` |
| 材料详情 / 完整更新元数据 | GET / PUT `/materials/{id}` |
| 原文件 / 浏览器预览 | GET `/materials/{id}/file` |
| 草稿列表 / 创建 | GET / POST `/drafts` |
| 草稿详情与分页 | GET `/drafts/{id}?offset=0&limit=20` |
| 导入训练文件（file + media_bindings JSON 字符串） | POST `/drafts/{id}/import` |

开发验证：从 backend 执行 `python -m pytest tests/test_data_library.py -q`；前端执行 `npm run build`。工作区完整回归入口为 `./scripts/test-local.sh`。

## 数据集入口与精简视图（2026-10-19 更新）

当前侧栏名称为「原始数据集」和「生成数据集」，路径保持不变。

- 原画布「数据集 → 添加」与原始数据集页右上角「添加数据集」共用导入表单。名称可自动填写；PDF / 图片可多选，JSON / JSONL / CSV / Parquet 每次添加一份。
- PDF / 图片保存为材料副本，并生成含 `source` / `source_name` / `material_id` 的 JSONL 输入清单，登记到兼容的 DatasetRegistry。可以在原画布中选择；这不代表对应 Pipeline 已经运行，也不保证任意算子接受所有模态。
- 原始数据集页默认只显示全宽列表；点击名称或「查看」进入详情，PDF / 图片可逐份切换。新上传文件的名称、分组、来源、关联关系等编辑入口折叠在「编辑文件信息」中；旧注册文件保持原有输入信息。后台材料管理 API 仍保留，包括本地路径登记。
- 生成数据集页默认只显示全宽列表；进入详情后以摘要列表展示样本，点击样本展开问题、回答、上下文和图片；新建与导入使用按需打开的对话框。图文文件会提取图片引用，通过下拉框选择材料，手动 JSON 映射作为高级入口保留。
- ID、哈希、完整路径、字段列表和导入记录收在「数据集详情」里；原始 JSON 收在每条样本的「查看原始数据」里。信息和数据没有被删除。

显示偏好保存在 `backend/data/dataset_visibility.json`（沿用 BASE_DIR / RESOURCE_DIR），结构为 `hidden_dataset_ids` 与 `hidden_draft_ids` 两个 ID 数组。仅隐藏指定记录；后来新增的记录默认可见。清除对应数组中的 ID 可以恢复显示。该文件是本地运行配置，不提交到源码仓库。

`GET /datasets/` 仍返回全部记录，并增加 `is_visible` 和 `type` 字段；`?visible_only=true` 返回可见子集。画布的数据选择列表与原始数据集页使用相同偏好，但加载历史 Pipeline 仍能解析完整数据列表。`GET /library/drafts?visible_only=true` 对生成数据集应用相同规则，按 ID 读取不受隐藏影响。

新增桥接接口：

- POST `/api/v1/library/inputs/upload`：`files` 多文件 + `name`；单份最多 100 MiB，一批最多 100 份 / 200 MiB。重复整批或同批重复内容明确报错。
- GET `/api/v1/library/inputs/{id}/preview?offset=0&limit=20`：分页预览原始输入；读取失败明确报错。
- GET `/api/v1/library/inputs/{id}/file?row=0`：只从已登记的数据集记录定位 PDF / 图片原件；新材料校验保存时的哈希。

旧的结构化文件上传也改用独立目录，同名上传不再覆盖已有文件。

两个入口均通过 `?dataset=<id>` 打开数据集详情，支持直接访问、刷新和浏览器前进后退；顶部面包屑返回列表，同一页面会保留搜索词及列表滚动位置。进入列表不自动选中或预览第一个数据集。导入、文件预览、样本编辑与发布继续复用已有组件。
