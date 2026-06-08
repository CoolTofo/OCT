# OCT Box 工程说明

这是 OCT Studio 的本地开发与分发工作区。当前目录同时包含源码、便携运行时、用户运行数据和已打包产物；开发时建议把它们按下面的边界理解。

## 快速启动

- Windows：双击 `OCT/启动服务.bat`
- macOS：进入 `OCT` 后运行 `mac-启动服务.command`
- 语法检查：`powershell -ExecutionPolicy Bypass -File tools/check-project.ps1`

## 目录边界

| 路径 | 用途 |
| --- | --- |
| `OCT/main.py` | FastAPI 主入口，保留兼容现有启动脚本 |
| `OCT/app/` | 后端支撑模块，新增代码优先放这里 |
| `OCT/static/` | 前端静态页面、样式和脚本 |
| `OCT/workflows/` | ComfyUI / RunningHub 工作流模板 |
| `OCT/data/` | 本地配置、画布、对话等运行数据 |
| `OCT/assets/`、`OCT/output/` | 用户输入素材和生成结果 |
| `OCT/python/`、`OCT/packages/` | 便携版内置运行时和离线依赖 |
| `tools/` | 清理、恢复、隧道等维护工具 |
| `dist/` | 发布包产物 |

## 开发约定

- 保持 `OCT/main.py` 作为兼容入口；新的基础设施代码放入 `OCT/app/`。
- 运行数据、日志、密钥、打包 zip 和内置 Python 不应提交到源码仓库。
- 大页面后续优先拆到 `OCT/static/js/` 和 `OCT/static/css/`，避免继续扩大单个 HTML。
- 如果要给他人分发，先运行 `tools/clean-runtime.ps1 -IncludeUserData` 清掉本机数据。
