# Multimodal AI Coding Agent Team

一个面向编程题场景的多模态代码生成 Agent 系统。用户可以输入算法题文本，或上传题目截图并补充说明；系统会完成题意识别、RAG 模板检索、解题规划、测试生成、代码生成、自动执行、失败修复、Trace 记录和报告输出。

本项目不是简单调用大模型返回代码，而是把一次代码生成任务拆成可追踪、可测试、可复盘的工程流程，适合作为课程答辩和 Agent 项目面试展示。

## 功能概览

| 模块 | 已实现能力 |
| --- | --- |
| 多模态输入 | 支持文本题目和 PNG/JPEG/WebP 题目截图；图片会校验真实格式、尺寸和体积 |
| 5 Agent 工作流 | 题目识别、解题规划、测试生成、代码生成、执行调试 |
| RAG 模板库 | 生成代码前检索算法模板，覆盖哈希、二分、动态规划、图搜索、栈、滑动窗口等 |
| 自动测试 | 生成代码后按用例逐条执行，统计通过率、失败原因和耗时 |
| 失败修复 | 执行失败后进入调试修复循环，默认最多 3 轮 |
| 语义防漂移 | 锁定题目契约、函数签名、返回类型和测试来源，避免模型把题意改偏 |
| Trace 可观测 | 保存节点、工具调用、耗时、错误、缓存命中等过程数据 |
| 历史与报告 | 保存任务历史，支持 Markdown/JSON/Python 下载 |
| Benchmark | 支持 30 题跑批评测，输出对比报告 |
| Docker 部署 | 支持 Docker Compose 一键启动前后端 |

## 技术架构

```text
Vue3 + Element Plus 前端
        |
        v
FastAPI 后端接口
        |
        v
SQLite 任务库 / 队列 / Trace / 缓存
        |
        v
5 Agent 工作流
        |
        +--> RAG 算法模板检索
        +--> 百炼 OpenAI 兼容接口
        +--> 离线兜底算法模板
        |
        v
受限代码执行器 + 自动评测器
        |
        v
任务详情 / Agent Timeline / Trace / Benchmark / 报告下载
```

## 项目结构

```text
.
├── ai_coding_agent_bailian.py      # Agent/RAG/兜底代码生成核心逻辑
├── agent/                          # 状态机、工具注册表、RAG、Prompt、契约模块
├── backend/
│   ├── main.py                     # FastAPI 接口与任务入口
│   ├── database.py                 # SQLite 表结构、迁移、读写函数
│   ├── worker.py                   # SQLite 队列 worker
│   └── Dockerfile
├── frontend/                       # Vue3 + Element Plus 前端
├── sandbox/
│   ├── code_runner.py              # 受限执行器
│   ├── evaluator.py                # 逐用例评测器
│   └── benchmark_runner.py         # Benchmark 跑批
├── tests/                          # 后端与沙盒 pytest
├── benchmark_data.json             # 30 题 Benchmark 题库
├── docker-compose.yml
└── .env.example
```

## 快速运行

### 1. 准备环境

需要：

- Python 3.10+
- Node.js 20+
- Docker Desktop，可选但推荐

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

可选填写百炼 API Key：

```text
DASHSCOPE_API_KEY=你的百炼 API Key
```

没有 API Key 也能运行，系统会使用离线兜底算法模板完成演示。页面输入框填写的 API Key 只通过当前请求头传给后端，不会写入数据库、日志或报告。

### 2. 启动后端

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

### 3. 启动前端

```powershell
cd frontend
npm ci
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
$env:VITE_ENABLE_STAGE2="true"
npm run dev
```

页面地址：

```text
http://127.0.0.1:5173
```

## Docker Compose 一键启动

```powershell
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

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| POST | `/api/tasks/text` | 提交文本题目 |
| POST | `/api/tasks/image` | 提交题目截图 |
| GET | `/api/tasks` | 查询任务历史 |
| GET | `/api/tasks/{task_id}` | 查询任务详情 |
| GET | `/api/tasks/{task_id}/steps` | 查询 5 Agent 输出 |
| GET | `/api/tasks/{task_id}/tests` | 查询自动测试结果 |
| GET | `/api/tasks/{task_id}/repairs` | 查询修复记录 |
| GET | `/api/tasks/{task_id}/trace` | 查询 Trace 节点和工具调用 |
| GET | `/api/tasks/{task_id}/report` | 下载 Markdown 报告 |
| POST | `/api/tasks/{task_id}/rerun` | 重跑任务 |
| POST | `/api/tasks/{task_id}/cancel` | 取消任务 |
| GET | `/api/prompt/versions` | 查询 Prompt 版本 |
| POST | `/api/prompt/version` | 切换指定 Agent Prompt 版本 |
| POST | `/api/benchmark/runs` | 启动 Benchmark 跑批 |
| GET | `/api/benchmark/runs/{run_id}` | 查询 Benchmark 状态 |
| GET | `/api/benchmark/results` | 查询最近 Benchmark 结果 |

提交文本题目示例：

```json
{
  "problem_text": "给定整数数组 nums 和目标值 target，请返回两数之和的下标。"
}
```

如需按请求临时使用百炼 Key，可在请求头中加入：

```text
X-DashScope-API-Key: 你的百炼 API Key
```

## 测试与验收

后端和沙盒测试：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

前端测试与构建：

```powershell
cd frontend
npm ci
npm test -- --run
npm run build
npm audit --omit=dev
```

当前验收结果：

| 类型 | 当前结果 |
| --- | --- |
| 后端/沙盒 pytest | 47 passed |
| 前端 Vitest | 3 passed |
| 前端生产构建 | 通过 |
| 生产依赖 audit | 0 漏洞 |
| 30 题 Benchmark | Offline_Fallback 100.0%，Online_Bailian 100.0% |
| Docker Compose | 前后端容器 healthy |
| 容器内任务执行 | 文本任务 completed，生成 code 与 trace |

说明：全量 `npm audit` 可能提示 Vite/esbuild 的开发服务器相关漏洞，该依赖不进入生产 Nginx 静态镜像；如需严格审计，可升级 Vite 主版本后重新验证。

## Benchmark

运行 30 题 Benchmark：

```powershell
python -m sandbox.benchmark_runner
```

只跑批、不写入数据库：

```powershell
python -m sandbox.benchmark_runner --no-persist
```

Benchmark 会逐题调用 Agent、执行代码、统计通过率，并生成：

```text
docs/benchmark_comparison.md
```

当前离线兜底模板已覆盖 30 道 Benchmark 题，本地最近一次跑批结果为 Offline_Fallback 100.0%、Online_Bailian 100.0%。无 API Key 时也能展示完整跑批链路；接入有效百炼 Key 后，可继续对比模型生成与离线模板的效果、耗时和成本。

## 演示建议

答辩时建议按下面顺序演示：

1. 首页输入 two sum 文本题，展示生成代码、测试通过率和报告下载。
2. 上传题目截图，补充题意说明，展示图片任务链路。
3. 打开 Agent Timeline，说明 5 个 Agent 的输入输出。
4. 打开 Trace 详情，说明节点耗时、工具调用和错误记录。
5. 打开 Benchmark 页面，说明 30 题跑批、通过率和工程指标。
6. 展示 Docker Compose 启动结果，说明部署方式。

## 项目亮点

- 从单文件 Demo 升级为前后端分离系统。
- 从“模型直接给代码”升级为 5 Agent 可追踪工作流。
- 从普通 Prompt 生成升级为 RAG 模板增强生成。
- 从“程序能跑”升级为逐用例自动评测、失败修复和报告输出。
- 从黑盒执行升级为 Trace、工具调用、缓存、Prompt 版本和 Benchmark 可观测。
- 在没有 API Key 或接口失败时，仍能用离线兜底模板完成稳定演示。

## 安全说明

本项目执行器包含 AST 检查、临时目录、超时、输出截断、危险调用拦截等保护，适合课程项目和受控算法代码执行。若要运行不可信用户代码，建议启用 Docker Sandbox 或 E2B，并继续限制网络、CPU、内存、进程数和文件系统权限。

## 旧版 Streamlit 单文件运行

仓库仍保留单文件版本，便于快速演示或对比：

```powershell
python -m pip install -r requirements.txt
streamlit run ai_coding_agent_bailian.py
```
