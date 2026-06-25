# 多模态代码生成 Agent 测试报告

测试日期：2026-06-25
测试环境：Windows 11、Python 3.14、本地 SQLite、Node.js/Vite

## 自动化测试

执行命令：

```text
pytest
```

结果：

```text
15 passed
```

覆盖范围：

| 模块 | 验证内容 | 结果 |
| --- | --- | --- |
| Agent 契约 | 5 个 Agent、RAG、测试用例、执行报告、离线兜底 | 通过 |
| 数据库 | 更新任务后步骤、测试和修复日志不丢失 | 通过 |
| 文本 API | 创建、轮询、详情、步骤、测试、报告、重跑、指标 | 通过 |
| 图片 API | 格式校验、空文件、图片任务和 5 Agent 流程 | 通过 |
| API Key | 请求级 Key 正确传递且不进入数据库和历史结果 | 通过 |
| Runner | 正常执行、超时、危险文件访问拦截 | 通过 |
| Evaluator | 逐用例执行、实际值、失败原因和通过率统计 | 通过 |
| 自动修复 | 无 Key 时坏代码由本地算法模板修复并重新评测 | 通过 |
| 中文完整性 | 正常中文原样保存；大量问号的损坏输入被拒绝 | 通过 |
| 语义契约 | 两数之和固定返回下标列表，模型布尔测试无法覆盖权威用例 | 通过 |
| Benchmark | 5 道题真实执行并写入统一数据库 | 通过 |

## Benchmark

离线兜底环境下真实运行 5 道题：

```text
总题目：5
通过题目：5
通过率：100%
```

结果由 Agent 生成代码后交给 Evaluator 执行，不再使用固定通过率或固定耗时。

## 前端构建

第一阶段与第二阶段开关均完成构建验证：

```text
VITE_ENABLE_STAGE2=false  构建通过
VITE_ENABLE_STAGE2=true   构建通过
```

## Docker

`docker compose config` 已通过。

本机 WSL、VirtualMachinePlatform 和固件虚拟化均已启用，但 Windows
存在 `CBSRebootPending` 和待处理文件重命名，WSL 2 引擎要求完成系统重启。
因此当前无法在本机执行真实镜像构建。`docker compose config` 已通过；
GitHub Actions 配置了 `docker compose build`，由 CI 完成真实容器构建验收。

## 本地端到端联调

使用真实 Uvicorn 和 Vite 进程完成 HTTP 验证：

```text
后端健康状态：ok
任务状态：completed
Agent 步骤：5
逐用例测试：3/3
Markdown 报告：HTTP 200
前端页面：HTTP 200
```

额外验证：

```text
伪装图片：HTTP 400
无 Key 且无补充文字的图片：HTTP 400
有效 PNG + 补充文字：任务完成
请求级 API Key：传递成功且结果中不含 Key
坏代码自动修复：1 轮修复成功，3/3 测试通过
```

## 真实百炼语义回归

使用请求级百炼 API Key 提交中文“两数之和返回下标”题：

```text
中文题意：完整保存，无问号乱码
语义契约：solution(nums, target) -> list[int]
Agent：5/5 completed
API 调用：true
离线兜底：false
权威测试：4/4
期望值：[0,1]、[1,2]、[0,1]、[]
实际值：[0,1]、[1,2]、[0,1]、[]
最终状态：completed
```

## 安全边界

第一阶段 Runner 是受限子进程，不宣称为操作系统级沙盒。已经实现 AST 检查、隔离模式 Python、最小环境、临时目录、超时和输出限制。第二阶段仍需 Docker/E2B 实现强隔离。
