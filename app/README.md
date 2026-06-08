# 后端模块说明

`OCT/app` 用来承接从 `main.py` 中逐步抽离出来的稳定支撑代码。当前拆分保持低风险，不改变原有启动方式。

| 模块 | 说明 |
| --- | --- |
| `paths.py` | 统一管理应用根目录、静态资源、运行数据、工作流等路径 |
| `logging_config.py` | 配置 uvicorn 访问日志过滤，减少轮询接口噪音 |
| `realtime.py` | WebSocket 连接管理和广播 |

后续建议继续拆分：

- `schemas.py`：请求/响应模型
- `services/`：图片生成、视频生成、文件存储、外部 API 调用
- `routes/`：按页面或业务域拆 FastAPI 路由

