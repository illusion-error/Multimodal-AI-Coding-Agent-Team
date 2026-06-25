# 多模态 Agent 项目真实测试报告 (成员 D 记录)

**测试环境**：Windows 11 / Python 3.10 / SQLite / 本地沙盒
**测试日期**：2026-06-24

## 1. 沙盒安全与隔离测试 (Sandbox Tests)
| 测试用例 | 注入代码 | 期望行为 | 实际沙盒输出 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **目录逃逸测试** | `open('../.git/config').read()` | 静态拦截或执行报错 | 触发关键词拦截: 包含禁用字 `open` | ✅ 成功隔离 |
| **内存死循环测试** | `while True: pass` | 5秒后触发 Timeout | `执行超时（>5秒），已强制中断！` | ✅ 成功熔断 |
| **越权执行测试** | `import os; os.system('dir')` | 静态拦截 | 触发关键词拦截: 包含禁用字 `os.system` | ✅ 成功拦截 |

## 2. API 接口连通性测试 (API Tests)
| 接口路由 | 测试方法 | 参数/数据 | 实际返回状态码 | 连通性 |
| :--- | :--- | :--- | :--- | :--- |
| `GET /api/health` | Postman | 无 | HTTP 200 (status: ok) | ✅ 正常 |
| `POST /api/tasks/text` | 前端联调 | problem_text="两数之和" | HTTP 200 (返回 task_id) | ✅ 正常 |
| `POST /api/tasks/image` | 接口测试 | image_bytes | HTTP 405 (Method Not Allowed) | ❌ 待后端 B 补齐 |

# 多模态代码生成 Agent 第一阶段真实测试报告

**测试时间**：2026-06-25
**测试负责人**：成员 D (测试与部署)
**测试环境**：Windows 11 / Python 3.13 / 本地受限沙盒

## 1. 沙盒安全与隔离测试 (Sandbox Security)
| 注入代码 | 期望行为 | 实际沙盒输出 | 结论 |
| :--- | :--- | :--- | :--- |
| `print(open('../.git/config').read())` | AST 算法检测并拦截 | 禁用内置函数调用: open | ✅ 成功拦截 |
| `import os; os.system('dir')` | AST 算法检测并拦截 | 禁用导入模块: os | ✅ 成功拦截 |
| `while True: pass` | 5秒后强行熔断 | 执行超时（>5秒），已强制中断！ | ✅ 成功熔断 |

## 2. 自动化 Benchmark 评测机测试 (Benchmark Results)
| 题库文件 | 加载题数 | 评测执行方式 | 数据库指标写入状态 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| `benchmark_data.json` | 5 道算法题 | 真实读取、逐题拼接运行、汇总计算 | 成功向 `backend/tasks.db` 写入两项真实指标 | ✅ 通过 |