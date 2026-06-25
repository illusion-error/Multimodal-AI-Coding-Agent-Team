# Multimodal AI Coding Agent Team

多模态代码生成 Agent 工程。系统支持文本题目和题目截图，使用阿里云百炼模型完成题意识别、RAG 检索、解题规划、测试生成、代码生成、执行调试和报告输出。

## 核心能力

- 5 个 Agent：题目识别、解题规划、测试生成、代码生成、执行调试。
- 轻量 RAG：生成代码前检索算法模板。
- 失败修复：执行失败后最多自动修复 3 轮。
- Vue 3 前端、FastAPI 后端和 SQLite 历史记录。
- 文本及图片任务、状态轮询、Agent Timeline、测试记录和报告下载。
- 浏览器请求级百炼 API Key，不写入任务历史、报告或数据库。
- 图片真实格式、尺寸和体积校验，拒绝伪装图片。
- 统一受限执行器与逐用例自动评测器。
- 模型不可用时使用本地算法模板完成确定性修复。
- 可在题目框粘贴待调试的 Python 代码，页面提供稳定自动修复示例。
- 5 道真实 Benchmark 跑批及结果持久化。
- Docker Compose 部署和 GitHub Actions 自动测试。
- 无 API Key 时使用离线兜底，仍能完整演示流程。

## 项目结构

```text
.
├── ai_coding_agent_bailian.py   # 唯一 Agent/RAG 业务实现
├── backend/
│   ├── main.py                  # FastAPI 接口
│   ├── database.py              # SQLite 数据访问
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # Vue 3 + Element Plus
├── sandbox/
│   ├── code_runner.py           # 第一阶段受限子进程执行器
│   ├── evaluator.py             # 结构化测试评测
│   └── benchmark_runner.py      # 真实 Benchmark 跑批
├── tests/                       # pytest 自动化测试
├── benchmark_data.json
├── docker-compose.yml
└── .env.example
```

## 环境要求

- Python 3.10+
- Node.js 20+
- Docker Desktop，可选

## 配置

复制环境模板：

```powershell
Copy-Item .env.example .env
```

在本地 `.env` 中填写：

```text
DASHSCOPE_API_KEY=你的百炼APIKey
```

不要提交 `.env`。没有 API Key 时系统会自动使用离线兜底。

也可以直接在 Vue 首页的“百炼 API Key”输入框中填写。页面填写的 Key
只通过当前任务请求头传给后端，刷新页面后清空，不会写入数据库和日志。
上传截图并要求视觉识别时必须提供 Key；没有 Key 时需要同时填写题目补充说明。

## 本地运行

### 后端

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

### 前端

```powershell
cd frontend
npm ci
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
$env:VITE_ENABLE_STAGE2="false"
npm run dev
```

页面地址：

```text
http://127.0.0.1:5173
```

### Streamlit 单文件版

```powershell
python -m pip install -r requirements.txt
streamlit run ai_coding_agent_bailian.py
```

## 第一阶段接口

```text
GET  /api/health
POST /api/tasks/text
POST /api/tasks/image
GET  /api/tasks
GET  /api/tasks/{id}
GET  /api/tasks/{id}/steps
GET  /api/tasks/{id}/tests
GET  /api/tasks/{id}/repairs
GET  /api/tasks/{id}/report
POST /api/tasks/{id}/rerun
GET  /api/metrics/summary
```

`POST /api/tasks/text`、`POST /api/tasks/image` 和重跑接口支持请求头：

```text
X-DashScope-API-Key: 你的百炼 API Key
```

图片接口只接受真实 PNG、JPEG、WebP 文件，最大 10MB、最大 2500 万像素。

第二阶段已提供 Benchmark 数据接口：

```text
GET /api/benchmark/results
```

Prompt 版本和 Trace 后端尚未启用，因此第一阶段默认设置：

```text
VITE_ENABLE_STAGE2=false
```

## Benchmark

执行真实题库跑批：

```powershell
python -m sandbox.benchmark_runner
```

只运行、不写入数据库：

```powershell
python -m sandbox.benchmark_runner --no-persist
```

跑批会逐题调用 Agent、逐用例执行代码，并将摘要和明细写入统一 SQLite 数据库。

## 自动测试

```powershell
python -m pip install -r requirements-dev.txt
pytest
```

前端构建：

```powershell
cd frontend
npm ci
npm run build
```

## Docker Compose

```powershell
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

访问：

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:8000
```

停止：

```powershell
docker compose down
```

SQLite 数据通过 `backend_data` 卷持久化。

## 安全说明

第一阶段执行器使用 AST 检查、临时目录、隔离模式 Python、最小环境变量、超时和输出限制。它适合课程项目和受控算法代码，但不等同于操作系统级安全边界。

任务只有在生成代码退出码为 0 且结构化测试用例全部通过时才会标记为
`completed`。测试失败会标记为 `failed`，页面仍会展示代码、Agent 步骤、
失败用例和修复记录。

第二阶段面向不可信代码时，应切换到 Docker Sandbox 或 E2B，并限制网络、CPU、内存、进程数和文件系统权限。
