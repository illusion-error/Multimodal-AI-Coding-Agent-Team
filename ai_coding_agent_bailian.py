"""
多模态代码生成 Agent（阿里云百炼版）

运行方式：
1. 安装 Streamlit：
   pip install streamlit
2. 启动页面：
   streamlit run ai_coding_agent_bailian.py
3. 配置环境变量（可选）：
   Windows PowerShell: $env:DASHSCOPE_API_KEY="你的百炼API Key"

如果没有配置 API Key，系统会自动走离线兜底逻辑，确保页面始终有输出。
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TEXT_MODEL = "qwen-plus"
DEFAULT_VISION_MODEL = "qwen3-vl-plus"


@dataclass
class AgentConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    text_model: str = DEFAULT_TEXT_MODEL
    vision_model: str = DEFAULT_VISION_MODEL
    request_timeout: int = 60
    execution_timeout: int = 8
    enable_local_execution: bool = True
    enable_offline_fallback: bool = True


@dataclass
class AgentResult:
    problem: str
    solution_markdown: str
    code: str
    execution_report: str
    project_document: str
    metrics: Dict[str, Any]
    api_used: bool
    fallback_used: bool
    error: str = ""


def now_ms() -> int:
    return int(time.time() * 1000)


def clean_base_url(base_url: str) -> str:
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.endswith("/v1"):
        return base_url
    return base_url


def image_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def call_bailian_chat(
    config: AgentConfig,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
) -> str:
    if not config.api_key.strip():
        raise RuntimeError("未填写阿里云百炼 API Key。")

    url = f"{clean_base_url(config.base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {config.api_key.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"百炼接口返回 HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接百炼接口: {exc}") from exc

    try:
        result = json.loads(body)
        return result["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"百炼响应解析失败: {body[:1000]}") from exc


def extract_problem_from_image(
    config: AgentConfig,
    image_bytes: bytes,
    mime_type: str,
    extra_text: str = "",
) -> Tuple[str, bool]:
    prompt = """
你是编程题截图识别 Agent。请从图片中提取完整题意，并整理为结构化文本。

请尽量包含：
1. 题目名称
2. 题目描述
3. 输入格式
4. 输出格式
5. 示例输入输出
6. 数据范围或约束
7. 需要实现的函数签名（如果图片中出现）

如果图片不清晰，也要给出你能确认的内容，并明确标注不确定部分。
"""
    if extra_text.strip():
        prompt += f"\n\n用户补充说明：\n{extra_text.strip()}"

    data_url = image_to_data_url(image_bytes, mime_type)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt.strip()},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    return call_bailian_chat(config, config.vision_model, messages), True


def generate_solution_with_bailian(config: AgentConfig, problem: str) -> Tuple[str, bool]:
    system_prompt = """
你是一个严谨的多 Agent 编程助手，负责把编程题转成可运行 Python 解法。

输出必须使用 Markdown，且必须包含这些小节：
## 题意理解
## 解题思路
## 复杂度分析
## Python 代码
## 自测用例

代码要求：
1. 必须放在一个 ```python 代码块中。
2. 必须是单文件可运行代码。
3. 尽量包含 solve 函数或核心函数。
4. 必须包含 _run_tests()，并在 __main__ 中调用，让代码直接运行时一定有输出。
5. 如果题目没有明确样例，请自己构造 2 到 4 个合理测试用例。
6. 代码要避免依赖第三方库。
7. 输出中文说明，但代码注释可以简洁。
"""
    user_prompt = f"请解决下面的编程题，并生成可直接运行的 Python 代码：\n\n{problem.strip()}"
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt},
    ]
    return call_bailian_chat(config, config.text_model, messages), True


def extract_code(markdown: str) -> str:
    patterns = [
        r"```python\s*(.*?)```",
        r"```py\s*(.*?)```",
        r"```\s*(.*?)```",
    ]
    for pattern in patterns:
        match = re.search(pattern, markdown, flags=re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1).strip()
            if code:
                return code
    return ""


def offline_solution(problem: str, reason: str = "") -> str:
    normalized = problem.lower()

    if "two sum" in normalized or "两数之和" in problem:
        code = r'''
from typing import List


def two_sum(nums: List[int], target: int) -> List[int]:
    seen = {}
    for i, value in enumerate(nums):
        need = target - value
        if need in seen:
            return [seen[need], i]
        seen[value] = i
    return []


def _run_tests() -> None:
    tests = [
        (([2, 7, 11, 15], 9), [0, 1]),
        (([3, 2, 4], 6), [1, 2]),
        (([3, 3], 6), [0, 1]),
    ]
    for args, expected in tests:
        result = two_sum(*args)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：two_sum")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "两数之和"
        idea = "使用哈希表记录已经遍历过的数字及其下标，每次查找 target - 当前值 是否已经出现。"
        complexity = "时间复杂度 O(n)，空间复杂度 O(n)。"
    elif "palindrome" in normalized or "回文" in problem:
        code = r'''
def is_palindrome(text: str) -> bool:
    filtered = [ch.lower() for ch in text if ch.isalnum()]
    return filtered == filtered[::-1]


def _run_tests() -> None:
    tests = [
        ("A man, a plan, a canal: Panama", True),
        ("race a car", False),
        ("", True),
    ]
    for value, expected in tests:
        result = is_palindrome(value)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：is_palindrome")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "回文判断"
        idea = "先过滤非字母数字字符并统一大小写，再用双端等价判断。"
        complexity = "时间复杂度 O(n)，空间复杂度 O(n)。"
    elif "fibonacci" in normalized or "斐波那契" in problem:
        code = r'''
def fibonacci(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _run_tests() -> None:
    tests = [(0, 0), (1, 1), (2, 1), (10, 55)]
    for value, expected in tests:
        result = fibonacci(value)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：fibonacci")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "斐波那契数"
        idea = "用两个变量滚动保存前两项，避免递归带来的重复计算。"
        complexity = "时间复杂度 O(n)，空间复杂度 O(1)。"
    elif "sentiment" in normalized or "情感" in problem:
        code = r'''
POSITIVE_WORDS = {"好", "优秀", "喜欢", "满意", "开心", "推荐", "love", "great", "good", "excellent"}
NEGATIVE_WORDS = {"差", "糟糕", "讨厌", "失望", "难过", "不好", "bad", "poor", "terrible", "hate"}


def analyze_sentiment(text: str) -> str:
    lower_text = text.lower()
    positive = sum(1 for word in POSITIVE_WORDS if word in lower_text)
    negative = sum(1 for word in NEGATIVE_WORDS if word in lower_text)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _run_tests() -> None:
    tests = [
        ("这个产品很好，我非常满意", "positive"),
        ("体验糟糕，不推荐", "negative"),
        ("今天是星期二", "neutral"),
    ]
    for text, expected in tests:
        result = analyze_sentiment(text)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：analyze_sentiment")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "文本情感分析"
        idea = "离线兜底版本使用轻量词典规则，真实项目中可替换为模型分类或大模型判断。"
        complexity = "时间复杂度 O(k)，k 为词典大小；空间复杂度 O(1)。"
    else:
        code = r'''
from typing import Any


def solve(*args: Any) -> str:
    """
    通用兜底解法。
    当 API Key 未配置、欠费或模型调用失败时，系统仍会生成可运行代码，避免页面无输出。
    请根据具体题目把这里替换为真实算法逻辑。
    """
    return "已生成兜底代码：请根据题目补充核心算法逻辑。"


def _run_tests() -> None:
    result = solve()
    assert isinstance(result, str)
    print(result)
    print("兜底自测通过：程序可以正常运行并产生输出。")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "通用兜底题目"
        idea = "由于当前无法可靠识别具体题意，先生成一个可运行的工程兜底模板，保证系统链路有输出。"
        complexity = "兜底模板本身为 O(1)，真实复杂度取决于后续补充的算法。"

    fallback_note = f"\n\n> 兜底原因：{reason}" if reason else ""
    return f"""
## 题意理解
当前识别为：{title}。{fallback_note}

## 解题思路
{idea}

## 复杂度分析
{complexity}

## Python 代码
```python
{code}
```

## 自测用例
代码内置 `_run_tests()`，直接运行会输出自测结果。
""".strip()


def ensure_code(markdown: str, problem: str) -> Tuple[str, bool]:
    code = extract_code(markdown)
    if code:
        return code, False
    fallback = offline_solution(problem, "模型没有返回可提取的 Python 代码块。")
    return extract_code(fallback), True


def looks_dangerous(code: str) -> List[str]:
    risky_patterns = [
        "os.system",
        "subprocess.",
        "shutil.rmtree",
        "socket.",
        "requests.",
        "urllib.request",
        "eval(",
        "exec(",
        "open(",
        "__import__",
    ]
    return [pattern for pattern in risky_patterns if pattern in code]


def run_python_code(code: str, timeout_seconds: int) -> str:
    risky = looks_dangerous(code)
    if risky:
        return (
            "安全检查：检测到潜在高风险调用，已跳过本地执行。\n"
            f"命中关键词：{', '.join(risky)}\n"
            "你仍然可以查看生成代码和项目文档。"
        )

    with tempfile.TemporaryDirectory(prefix="bailian_agent_") as temp_dir:
        script_path = os.path.join(temp_dir, "solution.py")
        with open(script_path, "w", encoding="utf-8") as file:
            file.write(code)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            completed = subprocess.run(
                [sys.executable, script_path],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"执行超时：代码运行超过 {timeout_seconds} 秒，已停止。"
        except Exception:
            return "执行异常：\n" + traceback.format_exc()

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    pieces = [
        f"退出码：{completed.returncode}",
        f"标准输出：\n{stdout or '(无)'}",
    ]
    if stderr:
        pieces.append(f"错误输出：\n{stderr}")
    return "\n\n".join(pieces)


def build_project_document(
    problem: str,
    solution_markdown: str,
    code: str,
    execution_report: str,
    metrics: Dict[str, Any],
    api_used: bool,
    fallback_used: bool,
) -> str:
    api_state = "已调用阿里云百炼 API" if api_used else "未调用 API"
    fallback_state = "启用兜底输出" if fallback_used else "未启用兜底"
    code_preview = code if len(code) < 5000 else code[:5000] + "\n# ... 代码过长，已截断展示"

    return f"""
# 多模态代码生成 Agent 项目说明与测试报告

## 1. 项目概述

本项目是一个面向编程题场景的多模态代码生成 Agent。系统支持输入编程题文本或上传题目截图，通过阿里云百炼大模型完成题意理解、解题规划、Python 代码生成，并在本地执行环境中进行自测验证。

## 2. 技术方案

- 前端界面：Streamlit 单文件页面
- 大模型接口：阿里云百炼 OpenAI 兼容接口
- 文本模型：{metrics.get("text_model", DEFAULT_TEXT_MODEL)}
- 视觉模型：{metrics.get("vision_model", DEFAULT_VISION_MODEL)}
- 代码执行：Python 本地子进程，带超时控制
- 稳定性策略：API 异常时自动切换离线兜底输出

## 3. Agent 流程

1. 输入接收：用户上传题目截图或输入题目文本。
2. 多模态识别：截图由视觉模型结构化为题目文本。
3. 解题生成：文本模型生成题意理解、算法思路、复杂度和代码。
4. 代码提取：系统从 Markdown 中提取 Python 代码块。
5. 沙盒式执行：在临时目录中运行代码，记录退出码、输出和错误。
6. 文档生成：自动生成项目说明、接口说明和测试报告。

## 4. 本次运行状态

- API 状态：{api_state}
- 兜底状态：{fallback_state}
- 总耗时：{metrics.get("total_ms", 0)} ms
- 题目来源：{metrics.get("input_type", "text")}
- 代码长度：{len(code)} 字符

## 5. 题目内容

{problem.strip()}

## 6. 生成结果

{solution_markdown.strip()}

## 7. 执行报告

```text
{execution_report.strip()}
```

## 8. 接口文档

### 8.1 百炼 Chat Completions

- 请求地址：`{DEFAULT_BASE_URL}/chat/completions`
- 请求方法：`POST`
- 鉴权方式：`Authorization: Bearer <DASHSCOPE_API_KEY>`
- 输入：messages、model、temperature
- 输出：choices[0].message.content

### 8.2 本地执行接口

- 输入：Python 代码字符串
- 处理：写入临时目录并调用当前 Python 解释器执行
- 约束：默认超时时间 {metrics.get("execution_timeout", 8)} 秒
- 输出：退出码、标准输出、错误输出

## 9. 测试报告

| 测试项 | 结果 |
|---|---|
| 页面是否有输出 | 通过 |
| 是否生成 Python 代码 | {'通过' if bool(code.strip()) else '未通过'} |
| 是否生成执行报告 | {'通过' if bool(execution_report.strip()) else '未通过'} |
| API 失败兜底 | {'通过' if fallback_used else '未触发'} |
| 文档生成 | 通过 |

## 10. 可交付代码

```python
{code_preview}
```
""".strip()


def solve_problem(
    config: AgentConfig,
    text_problem: str,
    image_bytes: Optional[bytes] = None,
    image_mime: str = "image/png",
) -> AgentResult:
    started = now_ms()
    api_used = False
    fallback_used = False
    errors: List[str] = []

    input_type = "text"
    problem = (text_problem or "").strip()

    if image_bytes:
        input_type = "image" if not problem else "image+text"
        try:
            problem, used = extract_problem_from_image(config, image_bytes, image_mime, problem)
            api_used = api_used or used
        except Exception as exc:
            errors.append(str(exc))
            if problem:
                problem = (
                    "图片识别失败，系统改用用户输入的文本继续生成。\n\n"
                    f"用户输入：\n{problem}"
                )
            else:
                problem = (
                    "图片识别失败，且未提供文本题目。"
                    "系统将生成一个兜底示例，保证页面、代码和文档都有输出。"
                )
            fallback_used = True

    if not problem:
        problem = "给定一个整数数组 nums 和目标值 target，请返回两个数的下标，使它们的和等于 target。"
        fallback_used = True

    try:
        solution_markdown, used = generate_solution_with_bailian(config, problem)
        api_used = api_used or used
    except Exception as exc:
        errors.append(str(exc))
        if not config.enable_offline_fallback:
            solution_markdown = f"## 生成失败\n\n{exc}"
        else:
            solution_markdown = offline_solution(problem, str(exc))
            fallback_used = True

    code, code_fallback = ensure_code(solution_markdown, problem)
    fallback_used = fallback_used or code_fallback

    if config.enable_local_execution and code:
        execution_report = run_python_code(code, config.execution_timeout)
    elif code:
        execution_report = "本地执行未开启：已生成代码，但未运行。"
    else:
        execution_report = "未提取到可执行代码。"

    metrics = {
        "input_type": input_type,
        "text_model": config.text_model,
        "vision_model": config.vision_model,
        "execution_timeout": config.execution_timeout,
        "total_ms": now_ms() - started,
        "api_used": api_used,
        "fallback_used": fallback_used,
        "error_count": len(errors),
    }
    document = build_project_document(
        problem=problem,
        solution_markdown=solution_markdown,
        code=code,
        execution_report=execution_report,
        metrics=metrics,
        api_used=api_used,
        fallback_used=fallback_used,
    )
    return AgentResult(
        problem=problem,
        solution_markdown=solution_markdown,
        code=code,
        execution_report=execution_report,
        project_document=document,
        metrics=metrics,
        api_used=api_used,
        fallback_used=fallback_used,
        error="\n".join(errors),
    )


def streamlit_app() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="多模态代码生成 Agent - 百炼版",
        page_icon="AI",
        layout="wide",
    )

    st.title("多模态代码生成 Agent（阿里云百炼版）")
    st.caption("支持题目截图 / 文本输入，自动生成 Python 解法、运行结果和项目文档。")

    with st.sidebar:
        st.header("百炼 API 配置")
        api_key = st.text_input(
            "阿里云百炼 API Key",
            value=os.getenv("DASHSCOPE_API_KEY", "") or os.getenv("BAILIAN_API_KEY", ""),
            type="password",
            help="可在阿里云百炼控制台创建 API Key。未填写时会自动使用离线兜底输出。",
        )
        base_url = st.text_input("接口地址", value=DEFAULT_BASE_URL)
        text_model = st.text_input("文本模型", value=DEFAULT_TEXT_MODEL)
        vision_model = st.text_input("视觉模型", value=DEFAULT_VISION_MODEL)
        request_timeout = st.slider("模型请求超时（秒）", min_value=10, max_value=180, value=60, step=5)
        execution_timeout = st.slider("代码执行超时（秒）", min_value=2, max_value=30, value=8, step=1)
        enable_local_execution = st.checkbox("生成后自动执行 Python 代码", value=True)
        enable_offline_fallback = st.checkbox("API 失败时启用兜底输出", value=True)

        st.divider()
        st.info(
            "建议先用文本题目测试链路；如果要上传截图，请使用视觉模型，例如 qwen3-vl-plus。"
        )

    config = AgentConfig(
        api_key=api_key,
        base_url=base_url,
        text_model=text_model,
        vision_model=vision_model,
        request_timeout=request_timeout,
        execution_timeout=execution_timeout,
        enable_local_execution=enable_local_execution,
        enable_offline_fallback=enable_offline_fallback,
    )

    left, right = st.columns([0.95, 1.05])
    with left:
        st.subheader("输入")
        uploaded_file = st.file_uploader(
            "上传编程题截图（可选）",
            type=["png", "jpg", "jpeg", "webp"],
        )
        text_problem = st.text_area(
            "请输入编程题文本，或补充截图中的关键信息",
            placeholder=(
                "示例：给定一个整数数组 nums 和目标值 target，"
                "请返回两个数的下标，使它们的和等于 target。"
            ),
            height=220,
        )
        run_button = st.button("生成解法、执行代码并生成文档", type="primary", use_container_width=True)

        if uploaded_file is not None:
            st.image(uploaded_file, caption="已上传的题目截图", use_container_width=True)

    with right:
        st.subheader("输出")
        st.write("点击左侧按钮后，这里会显示题意识别、代码、执行结果和可下载文档。")

    if not run_button:
        return

    image_bytes = uploaded_file.getvalue() if uploaded_file is not None else None
    image_mime = uploaded_file.type if uploaded_file is not None else "image/png"

    with st.spinner("Agent 正在处理，请稍候..."):
        result = solve_problem(
            config=config,
            text_problem=text_problem,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )

    if result.error:
        st.warning("运行过程中出现异常，系统已自动兜底并继续输出。")
        with st.expander("查看异常详情"):
            st.code(result.error, language="text")

    status_cols = st.columns(4)
    status_cols[0].metric("总耗时", f"{result.metrics.get('total_ms', 0)} ms")
    status_cols[1].metric("API 调用", "是" if result.api_used else "否")
    status_cols[2].metric("兜底输出", "是" if result.fallback_used else "否")
    status_cols[3].metric("代码长度", f"{len(result.code)} 字符")

    tab_problem, tab_solution, tab_code, tab_exec, tab_docs, tab_download = st.tabs(
        ["题意识别", "解题说明", "Python 代码", "执行结果", "项目文档", "下载"]
    )

    with tab_problem:
        st.markdown(result.problem)

    with tab_solution:
        st.markdown(result.solution_markdown)

    with tab_code:
        st.code(result.code or "# 未提取到代码", language="python")

    with tab_exec:
        st.code(result.execution_report, language="text")

    with tab_docs:
        st.markdown(result.project_document)

    with tab_download:
        st.download_button(
            "下载 Python 解法文件",
            data=(result.code or "# 未提取到代码\n").encode("utf-8"),
            file_name="generated_solution.py",
            mime="text/x-python",
            use_container_width=True,
        )
        st.download_button(
            "下载项目说明与测试报告",
            data=result.project_document.encode("utf-8"),
            file_name="agent_project_report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            "下载完整运行结果 JSON",
            data=json.dumps(asdict(result), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="agent_result.json",
            mime="application/json",
            use_container_width=True,
        )


def cli_main() -> None:
    text = " ".join(arg for arg in sys.argv[1:] if arg != "--cli").strip()
    if not text:
        text = "两数之和：给定 nums 和 target，返回两个数的下标，使它们的和等于 target。"

    config = AgentConfig(
        api_key=os.getenv("DASHSCOPE_API_KEY", "") or os.getenv("BAILIAN_API_KEY", ""),
        enable_local_execution=True,
        enable_offline_fallback=True,
    )
    result = solve_problem(config=config, text_problem=text)
    print("=== 题意 ===")
    print(result.problem)
    print("\n=== 解题说明 ===")
    print(result.solution_markdown)
    print("\n=== 执行结果 ===")
    print(result.execution_report)
    print("\n提示：要打开网页界面，请运行：streamlit run ai_coding_agent_bailian.py")


def running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if "--cli" in sys.argv or not running_under_streamlit():
        cli_main()
    else:
        streamlit_app()
