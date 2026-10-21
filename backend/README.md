# DataFlow WebUI backend

FastAPI REST API、算子注册表、受管数据与训练生命周期。产品中的 Agent 聊天、CLI Agent 子进程、WebSocket 同步与 MCP 服务已移除；仓库开发技能仍可用于维护源码。

局域网共享使用集成仓库 `scripts/start-lan.sh`，管理员在主机初始化；认证网关为 `app.team_gateway:app`，项目工作进程仅监听私有 Unix socket。完整部署、权限、迁移和恢复说明见集成仓库 `docs/lan-usage.md`。

独立本地调试可运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。此入口不提供团队身份边界，不应直接共享。前端构建由 FastAPI 同源提供。API 路由位于 `app/api/v1/`，服务通过 `app/core/container.py` 初始化；项目数据库使用 SQLite 短事务与受管文件。

```sh
python -m pytest tests -q
python -m pytest platform_tests -q
```

真实模型 API、SSH、GPU 或模型下载需单独明确配置和执行。人工评测、发布和导出不会自动执行这些任务。
