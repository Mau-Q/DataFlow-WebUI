# 原始材料与训练数据集（M1）

侧栏新增「原始材料」和「训练数据集」两个入口，分别对应 `/#/m/materials` 和 `/#/m/training-datasets`。旧 DataFlow Hub、输入数据集和 Pipeline 保留原有入口与注册语义。

## 原始材料

1. 上传文件，或输入运行后端的机器上的本地路径。两种方式都会保存平台持有的文件副本，原路径后续修改不会改变材料。
2. 填写名称、分组、来源与说明；可关联已有原始材料，并标记为 PDF 页面图、解析图片、表格产物或公式产物。
3. 在列表中搜索或按分组筛选。详情可修改元数据、打开原文件、预览 PDF / 图片、跳转关联产物。

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

先在材料库导入图片，再在导入面板填入明确映射（将示例 ID 换为实际图片 ID）：

```json
{"images/chart.png": "mat_0123456789abcdef0123456789abcdef"}
```

不会根据同名文件搜索路径，也不会下载远程 URL。即使引用写成 URL，也必须显式绑定已导入的图片。相同草稿内，同一引用不能重新绑定另一张图；已有映射可供后续批次复用。缺少映射、文件缺失、哈希改变、引用 PDF 而非图片都会阻止导入。

全批结构与媒体检查通过后一次写入；失败提示第几条样本，已有草稿不变。重复文件内容会拒绝；批次内或与已有样本完全相同的 JSON 对象会跳过，并报告数量。仅对象字段顺序不同仍视为重复；含不同额外字段则是不同样本。每次有效导入保存规范化内容哈希、原文件哈希、文件名与新增/跳过数量。

M1 提供创建、导入与预览。样本编辑、发布冻结、数据和媒体打包导出由后续 M4 实现。DPO 不显示为当前支持的训练类型。

## 存储、备份与 API

默认路径为 `backend/data/library/`，可随现有 `BASE_DIR` / `RESOURCE_DIR` 配置改变：

- `materials/<material_id>.json`：名称、分组、来源、关联材料、格式、哈希和存储文件名。
- `materials/<material_id>.<suffix>`：平台保存的原文件副本。
- `drafts/<dataset_id>.json`：模态、训练类型、草稿样本、媒体绑定和导入记录。
- `.lock`：线程和进程之间的写入锁（当前支持 macOS / Linux）。

写入通过临时文件、fsync 和原子替换完成；损坏的 JSON 元数据会报错，不会自动重建空库。备份时停止后端并复制完整 `library/`，不能只备份 JSON 而遗漏图片。M1 面向本地小批量数据，草稿按文件保存；分页只限制响应大小，不代表已具备大规模数据集数据库能力。

旧 `DatasetRegistry` 不扫描这个新目录，不迁移或重注册已有记录。

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
