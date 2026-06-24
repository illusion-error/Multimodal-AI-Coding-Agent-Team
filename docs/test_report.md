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