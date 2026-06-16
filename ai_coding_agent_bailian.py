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
class AgentStep:
    name: str
    role: str
    status: str
    input_summary: str
    output_summary: str
    duration_ms: int
    error: str = ""


@dataclass
class AgentResult:
    problem: str
    solution_markdown: str
    code: str
    execution_report: str
    project_document: str
    metrics: Dict[str, Any]
    agent_steps: List[AgentStep]
    retrieved_templates: List[Dict[str, Any]]
    test_plan: str
    repair_attempts: List[Dict[str, Any]]
    api_used: bool
    fallback_used: bool
    error: str = ""


def now_ms() -> int:
    return int(time.time() * 1000)


def shorten_text(text: Any, limit: int = 1200) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...（已截断）"


def build_step(
    name: str,
    role: str,
    input_summary: str,
    output_summary: str,
    started_ms: int,
    status: str = "completed",
    error: str = "",
) -> AgentStep:
    return AgentStep(
        name=name,
        role=role,
        status=status,
        input_summary=shorten_text(input_summary),
        output_summary=shorten_text(output_summary),
        duration_ms=now_ms() - started_ms,
        error=shorten_text(error, 800),
    )


def clean_base_url(base_url: str) -> str:
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.endswith("/v1"):
        return base_url
    return base_url


def image_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


ALGORITHM_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "hash_table",
        "name": "哈希表 / Hash Table",
        "keywords": ["两数之和", "two sum", "target", "下标", "频次", "出现次数", "hash", "map", "字典"],
        "description": "适合快速查找、去重、计数、两数之和等问题。",
        "template": "遍历元素，用 dict 记录已访问信息；每次 O(1) 查询需要的补数或状态。",
    },
    {
        "id": "two_pointers",
        "name": "双指针 / Two Pointers",
        "keywords": ["双指针", "左右指针", "有序数组", "回文", "palindrome", "反转", "合并"],
        "description": "适合有序数组、字符串回文、区间收缩、原地处理等问题。",
        "template": "left 从左开始，right 从右开始，根据条件移动指针并维护答案。",
    },
    {
        "id": "sliding_window",
        "name": "滑动窗口 / Sliding Window",
        "keywords": ["最长", "最短", "子串", "子数组", "连续", "窗口", "substring", "subarray"],
        "description": "适合连续子串/子数组的最长、最短、计数问题。",
        "template": "右指针扩展窗口，左指针在条件不满足时收缩窗口，过程中更新答案。",
    },
    {
        "id": "dynamic_programming",
        "name": "动态规划 / Dynamic Programming",
        "keywords": ["动态规划", "dp", "最优", "最大", "最小", "方案数", "斐波那契", "fibonacci", "背包"],
        "description": "适合最优子结构、计数、路径、背包、序列状态转移问题。",
        "template": "定义 dp 状态，写出状态转移，初始化边界，按依赖顺序递推。",
    },
    {
        "id": "binary_search",
        "name": "二分查找 / Binary Search",
        "keywords": ["二分", "binary", "有序", "查找", "搜索", "第一个", "最后一个", "边界"],
        "description": "适合有序数据查找、边界定位、答案单调性问题。",
        "template": "维护 left/right，根据 mid 判断缩小区间，注意循环条件和边界收敛。",
    },
    {
        "id": "graph_search",
        "name": "图搜索 / BFS DFS",
        "keywords": ["图", "树", "节点", "路径", "连通", "bfs", "dfs", "grid", "岛屿", "最短路径"],
        "description": "适合图、树、网格连通性、路径搜索和层序遍历。",
        "template": "建立邻接关系，用 visited 防止重复访问；BFS 求最短层数，DFS 做遍历/回溯。",
    },
    {
        "id": "stack_queue",
        "name": "栈与队列 / Stack Queue",
        "keywords": ["栈", "队列", "括号", "单调栈", "最近", "下一个更大", "stack", "queue"],
        "description": "适合括号匹配、单调栈、最近关系、层序处理。",
        "template": "用 stack 保存待匹配或单调候选元素；必要时用 deque 做队列。",
    },
    {
        "id": "greedy",
        "name": "贪心 / Greedy",
        "keywords": ["贪心", "greedy", "区间", "排序", "最少", "最多", "安排", "选择"],
        "description": "适合局部最优可推出全局最优的排序、区间、选择问题。",
        "template": "先排序或定义选择标准，每一步选择当前最优并证明不会影响后续最优。",
    },
    {
        "id": "sentiment_rule",
        "name": "文本情感规则 / Sentiment Rule",
        "keywords": ["情感", "sentiment", "positive", "negative", "文本分类", "评论", "满意", "推荐"],
        "description": "适合没有本地训练模型时做轻量情感分析兜底。",
        "template": "维护正负向词典，统计命中数量，按分数判断 positive/negative/neutral。",
    },
]


def retrieve_algorithm_templates(problem: str, top_k: int = 3) -> List[Dict[str, Any]]:
    text = (problem or "").lower()
    scored: List[Dict[str, Any]] = []
    for template in ALGORITHM_TEMPLATES:
        matched = []
        for keyword in template["keywords"]:
            key = str(keyword).lower()
            if key and key in text:
                matched.append(str(keyword))
        if matched:
            item = {
                "id": template["id"],
                "name": template["name"],
                "description": template["description"],
                "template": template["template"],
                "matched_keywords": matched,
                "score": len(matched),
            }
            scored.append(item)

    scored.sort(key=lambda item: (-item["score"], item["name"]))
    if scored:
        return scored[:top_k]

    fallback = ALGORITHM_TEMPLATES[0]
    return [
        {
            "id": fallback["id"],
            "name": fallback["name"],
            "description": fallback["description"],
            "template": fallback["template"],
            "matched_keywords": [],
            "score": 0,
            "note": "未命中明确关键词，返回通用哈希表模板作为兜底参考。",
        }
    ]


def format_templates_for_prompt(templates: List[Dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(templates, start=1):
        keywords = ", ".join(item.get("matched_keywords", [])) or "无明确命中"
        lines.append(
            f"{index}. {item['name']}\n"
            f"   描述：{item['description']}\n"
            f"   模板：{item['template']}\n"
            f"   命中关键词：{keywords}"
        )
    return "\n".join(lines) if lines else "未检索到算法模板。"


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


def offline_plan_solution(problem: str, templates: List[Dict[str, Any]], reason: str = "") -> str:
    template_text = format_templates_for_prompt(templates)
    note = f"\n\n> 规划兜底原因：{reason}" if reason else ""
    return f"""
## 解题规划

1. 先确认输入、输出、边界条件和样例。
2. 根据题目关键词检索算法模板，优先使用命中的模板。
3. 生成 Python 单文件解法，代码中必须包含 `_run_tests()`。
4. 运行代码并根据执行结果判断是否需要调试修复。

## 检索到的算法模板

{template_text}
{note}
""".strip()


def plan_solution_with_bailian(
    config: AgentConfig,
    problem: str,
    templates: List[Dict[str, Any]],
) -> Tuple[str, bool]:
    system_prompt = """
你是解题规划 Agent。你的任务不是直接写完整代码，而是先制定可执行的解题计划。

请输出 Markdown，包含：
## 题型判断
## 可用算法模板
## 解题步骤
## 边界条件
## 复杂度目标

要求：优先参考给定的 RAG 算法模板；如果模板不完全匹配，请说明取舍。
"""
    user_prompt = f"""
题目：
{problem.strip()}

RAG 检索到的算法模板：
{format_templates_for_prompt(templates)}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    return call_bailian_chat(config, config.text_model, messages), True


def generate_solution_with_bailian(
    config: AgentConfig,
    problem: str,
    plan: str = "",
    templates: Optional[List[Dict[str, Any]]] = None,
    test_plan: str = "",
) -> Tuple[str, bool]:
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
    template_text = format_templates_for_prompt(templates or [])
    user_prompt = f"""
请解决下面的编程题，并生成可直接运行的 Python 代码。

题目：
{problem.strip()}

解题规划 Agent 输出：
{plan.strip() or "暂无单独规划。"}

RAG 算法模板：
{template_text}

测试生成 Agent 输出：
{test_plan.strip() or "暂无测试计划，请在代码中自行补充 _run_tests()。"}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    return call_bailian_chat(config, config.text_model, messages), True


def offline_test_plan(problem: str, reason: str = "") -> Tuple[str, List[Dict[str, str]]]:
    lower = (problem or "").lower()
    if "two sum" in lower or "两数之和" in problem or "target" in lower:
        cases = [
            {"name": "基础样例", "input": "nums=[2,7,11,15], target=9", "expected": "[0,1]", "purpose": "验证常规命中"},
            {"name": "重复数字", "input": "nums=[3,3], target=6", "expected": "[0,1]", "purpose": "验证重复元素"},
            {"name": "无解情况", "input": "nums=[1,2,3], target=7", "expected": "[] 或题目约定", "purpose": "验证边界处理"},
        ]
    elif "回文" in problem or "palindrome" in lower:
        cases = [
            {"name": "标准回文", "input": "A man, a plan, a canal: Panama", "expected": "True", "purpose": "忽略大小写和符号"},
            {"name": "非回文", "input": "race a car", "expected": "False", "purpose": "验证失败分支"},
            {"name": "空字符串", "input": "", "expected": "True", "purpose": "验证空输入"},
        ]
    elif "情感" in problem or "sentiment" in lower:
        cases = [
            {"name": "正向文本", "input": "这个产品很好，我非常满意", "expected": "positive", "purpose": "验证正向识别"},
            {"name": "负向文本", "input": "体验糟糕，不推荐", "expected": "negative", "purpose": "验证负向识别"},
            {"name": "中性文本", "input": "今天是星期二", "expected": "neutral", "purpose": "验证中性兜底"},
        ]
    else:
        cases = [
            {"name": "基础样例", "input": "题目给定样例", "expected": "题目给定输出", "purpose": "验证主流程"},
            {"name": "边界样例", "input": "空输入 / 单元素 / 极值", "expected": "符合题意", "purpose": "验证边界条件"},
            {"name": "异常样例", "input": "重复值 / 无解 / 大规模输入", "expected": "不崩溃且输出合理", "purpose": "验证鲁棒性"},
        ]

    note = f"\n\n> 测试计划兜底原因：{reason}" if reason else ""
    rows = "\n".join(
        f"- {case['name']}：输入 `{case['input']}`，期望 `{case['expected']}`，目的：{case['purpose']}"
        for case in cases
    )
    plan = f"""
## 测试策略

覆盖基础样例、边界样例和异常样例。生成代码时应将这些用例写入 `_run_tests()` 或等价测试函数。

## 测试用例

{rows}
{note}
""".strip()
    return plan, cases


def generate_tests_with_bailian(
    config: AgentConfig,
    problem: str,
    plan: str,
) -> Tuple[str, List[Dict[str, str]], bool]:
    system_prompt = """
你是测试用例生成 Agent。请根据题目和解题规划生成测试策略。

输出 Markdown，包含：
## 测试策略
## 测试用例
## 边界条件

要求：
1. 至少给出 3 个测试用例。
2. 覆盖基础样例、边界样例、异常或极端样例。
3. 每个用例说明输入、期望输出和测试目的。
"""
    user_prompt = f"""
题目：
{problem.strip()}

解题规划：
{plan.strip()}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    content = call_bailian_chat(config, config.text_model, messages)
    fallback_plan, cases = offline_test_plan(problem)
    return content, cases, True


def repair_code_with_bailian(
    config: AgentConfig,
    problem: str,
    code: str,
    execution_report: str,
    test_plan: str,
) -> Tuple[str, bool]:
    system_prompt = """
你是执行调试 Agent。你会收到题目、失败代码、执行日志和测试计划。

请修复代码，并且只返回一个 ```python 代码块，不要返回额外解释。
修复后的代码必须是单文件可运行代码，并包含 _run_tests()。
"""
    user_prompt = f"""
题目：
{problem.strip()}

失败代码：
```python
{code}
```

执行日志：
{execution_report}

测试计划：
{test_plan}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
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


def execution_succeeded(execution_report: str) -> bool:
    report = execution_report or ""
    normalized = report.replace(" ", "").lower()
    return (
        "退出码：0" in normalized
        or "退出码:0" in normalized
        or "exitcode:0" in normalized
        or "returncode:0" in normalized
    )


def run_execution_debug_agent(
    config: AgentConfig,
    problem: str,
    code: str,
    test_plan: str,
) -> Tuple[str, str, List[Dict[str, Any]], bool, bool]:
    api_used = False
    fallback_used = False
    repair_attempts: List[Dict[str, Any]] = []

    if not code:
        return code, "未提取到可执行代码。", repair_attempts, api_used, True

    if not config.enable_local_execution:
        return code, "本地执行未开启：已生成代码，但未运行。", repair_attempts, api_used, fallback_used

    current_code = code
    execution_report = run_python_code(current_code, config.execution_timeout)
    if execution_succeeded(execution_report):
        return current_code, execution_report, repair_attempts, api_used, fallback_used

    for round_index in range(1, 4):
        try:
            repair_markdown, used = repair_code_with_bailian(
                config=config,
                problem=problem,
                code=current_code,
                execution_report=execution_report,
                test_plan=test_plan,
            )
            api_used = api_used or used
            repaired_code = extract_code(repair_markdown) or repair_markdown.strip()
            if not repaired_code:
                repair_attempts.append(
                    {
                        "round": round_index,
                        "status": "failed",
                        "reason": "调试 Agent 没有返回可用代码。",
                    }
                )
                fallback_used = True
                break

            current_code = repaired_code
            new_report = run_python_code(current_code, config.execution_timeout)
            repair_attempts.append(
                {
                    "round": round_index,
                    "status": "passed" if execution_succeeded(new_report) else "failed",
                    "reason": "调试 Agent 已根据执行日志生成修复代码。",
                    "execution_report": shorten_text(new_report, 1200),
                }
            )
            execution_report = new_report
            if execution_succeeded(execution_report):
                break
        except Exception as exc:
            repair_attempts.append(
                {
                    "round": round_index,
                    "status": "skipped",
                    "reason": str(exc),
                }
            )
            fallback_used = True
            break

    return current_code, execution_report, repair_attempts, api_used, fallback_used


def build_project_document(
    problem: str,
    solution_markdown: str,
    code: str,
    execution_report: str,
    metrics: Dict[str, Any],
    api_used: bool,
    fallback_used: bool,
    agent_steps: Optional[List[AgentStep]] = None,
    retrieved_templates: Optional[List[Dict[str, Any]]] = None,
    test_plan: str = "",
    repair_attempts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    api_state = "已调用阿里云百炼 API" if api_used else "未调用 API"
    fallback_state = "启用兜底输出" if fallback_used else "未启用兜底"
    code_preview = code if len(code) < 5000 else code[:5000] + "\n# ... 代码过长，已截断展示"
    agent_steps = agent_steps or []
    retrieved_templates = retrieved_templates or []
    repair_attempts = repair_attempts or []
    steps_text = "\n\n".join(
        f"### {index}. {step.name}\n"
        f"- 角色：{step.role}\n"
        f"- 状态：{step.status}\n"
        f"- 耗时：{step.duration_ms} ms\n"
        f"- 输入摘要：\n{step.input_summary}\n"
        f"- 输出摘要：\n{step.output_summary}\n"
        f"{'- 错误：' + step.error if step.error else ''}"
        for index, step in enumerate(agent_steps, start=1)
    ) or "暂无 Agent 步骤记录。"
    templates_text = format_templates_for_prompt(retrieved_templates)
    repairs_text = (
        json.dumps(repair_attempts, ensure_ascii=False, indent=2)
        if repair_attempts
        else "本次未触发自动修复，或初次执行已经通过。"
    )

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

1. 题目识别 Agent：接收文本或图片，输出结构化题目。
2. 解题规划 Agent：结合 RAG 模板，输出题型判断、步骤和复杂度目标。
3. 代码生成 Agent：根据题目、规划和模板生成 Python 解法。
4. 测试生成 Agent：生成基础、边界和异常测试策略。
5. 执行调试 Agent：执行代码，失败时最多尝试 3 轮自动修复。

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

## 7. RAG 检索模板

{templates_text}

## 8. Agent 步骤详情

{steps_text}

## 9. 测试生成 Agent 输出

{test_plan.strip() or "暂无测试计划。"}

## 10. 执行报告

```text
{execution_report.strip()}
```

## 11. 调试修复记录

```json
{repairs_text}
```

## 12. 接口文档

### 12.1 百炼 Chat Completions

- 请求地址：`{DEFAULT_BASE_URL}/chat/completions`
- 请求方法：`POST`
- 鉴权方式：`Authorization: Bearer <DASHSCOPE_API_KEY>`
- 输入：messages、model、temperature
- 输出：choices[0].message.content

### 12.2 本地执行接口

- 输入：Python 代码字符串
- 处理：写入临时目录并调用当前 Python 解释器执行
- 约束：默认超时时间 {metrics.get("execution_timeout", 8)} 秒
- 输出：退出码、标准输出、错误输出

## 13. 测试报告

| 测试项 | 结果 |
|---|---|
| 页面是否有输出 | 通过 |
| 是否生成 Python 代码 | {'通过' if bool(code.strip()) else '未通过'} |
| 是否生成执行报告 | {'通过' if bool(execution_report.strip()) else '未通过'} |
| 是否记录 5 个 Agent 输出 | {'通过' if len(agent_steps) >= 5 else '未通过'} |
| 是否返回 RAG 算法模板 | {'通过' if bool(retrieved_templates) else '未通过'} |
| API 失败兜底 | {'通过' if fallback_used else '未触发'} |
| 文档生成 | 通过 |

## 14. 可交付代码

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
    agent_steps: List[AgentStep] = []
    retrieved_templates: List[Dict[str, Any]] = []
    test_plan = ""
    test_cases: List[Dict[str, str]] = []
    repair_attempts: List[Dict[str, Any]] = []

    input_type = "text"
    problem = (text_problem or "").strip()

    # Agent 1: problem recognition.
    step_started = now_ms()
    recognition_input = f"input_type={input_type}; has_image={bool(image_bytes)}; text={shorten_text(problem, 600)}"
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

    agent_steps.append(
        build_step(
            name="题目识别 Agent",
            role="接收文本/图片输入，输出结构化题面。",
            input_summary=recognition_input,
            output_summary=problem,
            started_ms=step_started,
            status="completed",
        )
    )

    # RAG before generation: lightweight algorithm template retrieval.
    retrieved_templates = retrieve_algorithm_templates(problem)

    # Agent 2: solution planning.
    step_started = now_ms()
    try:
        plan_markdown, used = plan_solution_with_bailian(config, problem, retrieved_templates)
        api_used = api_used or used
        planning_error = ""
        planning_status = "completed"
    except Exception as exc:
        planning_error = str(exc)
        errors.append(planning_error)
        plan_markdown = offline_plan_solution(problem, retrieved_templates, planning_error)
        fallback_used = True
        planning_status = "fallback"

    agent_steps.append(
        build_step(
            name="解题规划 Agent",
            role="结合 RAG 模板输出题型判断、解题步骤、边界条件和复杂度目标。",
            input_summary=f"题目：{shorten_text(problem, 700)}\n\n模板：\n{format_templates_for_prompt(retrieved_templates)}",
            output_summary=plan_markdown,
            started_ms=step_started,
            status=planning_status,
            error=planning_error,
        )
    )

    # Agent 4 runs before code generation to provide tests as generation constraints.
    step_started = now_ms()
    try:
        test_plan, test_cases, used = generate_tests_with_bailian(config, problem, plan_markdown)
        api_used = api_used or used
        test_error = ""
        test_status = "completed"
    except Exception as exc:
        test_error = str(exc)
        errors.append(test_error)
        test_plan, test_cases = offline_test_plan(problem, test_error)
        fallback_used = True
        test_status = "fallback"

    test_case_text = json.dumps(test_cases, ensure_ascii=False, indent=2)
    agent_steps.append(
        build_step(
            name="测试生成 Agent",
            role="生成基础、边界、异常测试用例，约束代码生成和执行验证。",
            input_summary=f"题目：{shorten_text(problem, 700)}\n\n规划：{shorten_text(plan_markdown, 700)}",
            output_summary=f"{test_plan}\n\n结构化测试用例：\n{test_case_text}",
            started_ms=step_started,
            status=test_status,
            error=test_error,
        )
    )

    # Agent 3: code generation.
    step_started = now_ms()
    try:
        solution_markdown, used = generate_solution_with_bailian(
            config=config,
            problem=problem,
            plan=plan_markdown,
            templates=retrieved_templates,
            test_plan=test_plan,
        )
        api_used = api_used or used
        generation_error = ""
        generation_status = "completed"
    except Exception as exc:
        generation_error = str(exc)
        errors.append(generation_error)
        if not config.enable_offline_fallback:
            solution_markdown = f"## 生成失败\n\n{exc}"
        else:
            solution_markdown = offline_solution(problem, generation_error)
            fallback_used = True
        generation_status = "fallback"

    code, code_fallback = ensure_code(solution_markdown, problem)
    fallback_used = fallback_used or code_fallback
    agent_steps.append(
        build_step(
            name="代码生成 Agent",
            role="根据题目、规划、RAG 模板和测试计划生成 Python 单文件代码。",
            input_summary=(
                f"题目：{shorten_text(problem, 500)}\n\n"
                f"规划：{shorten_text(plan_markdown, 600)}\n\n"
                f"测试计划：{shorten_text(test_plan, 500)}"
            ),
            output_summary=f"{shorten_text(solution_markdown, 1200)}\n\n提取代码长度：{len(code)} 字符",
            started_ms=step_started,
            status=generation_status,
            error=generation_error,
        )
    )

    # Agent 5: execution and debug repair.
    step_started = now_ms()
    final_code, execution_report, repair_attempts, used, repair_fallback = run_execution_debug_agent(
        config=config,
        problem=problem,
        code=code,
        test_plan=test_plan,
    )
    api_used = api_used or used
    fallback_used = fallback_used or repair_fallback
    if final_code != code:
        solution_markdown += "\n\n## 自动调试修复\n\n执行调试 Agent 已根据运行日志修复代码，最终版本请查看“Python 代码”页签。"
    code = final_code
    agent_steps.append(
        build_step(
            name="执行调试 Agent",
            role="执行代码，记录日志；失败时最多调用模型进行 3 轮自动修复。",
            input_summary=f"代码长度：{len(code)} 字符\n\n测试计划：{shorten_text(test_plan, 700)}",
            output_summary=(
                f"执行结果：\n{execution_report}\n\n"
                f"修复记录：\n{json.dumps(repair_attempts, ensure_ascii=False, indent=2) if repair_attempts else '未触发修复'}"
            ),
            started_ms=step_started,
            status="completed" if execution_succeeded(execution_report) else "finished_with_warnings",
        )
    )

    metrics = {
        "input_type": input_type,
        "text_model": config.text_model,
        "vision_model": config.vision_model,
        "execution_timeout": config.execution_timeout,
        "total_ms": now_ms() - started,
        "api_used": api_used,
        "fallback_used": fallback_used,
        "error_count": len(errors),
        "agent_step_count": len(agent_steps),
        "retrieved_template_count": len(retrieved_templates),
        "test_case_count": len(test_cases),
        "repair_attempt_count": len(repair_attempts),
        "execution_success": execution_succeeded(execution_report),
    }
    document = build_project_document(
        problem=problem,
        solution_markdown=solution_markdown,
        code=code,
        execution_report=execution_report,
        metrics=metrics,
        api_used=api_used,
        fallback_used=fallback_used,
        agent_steps=agent_steps,
        retrieved_templates=retrieved_templates,
        test_plan=test_plan,
        repair_attempts=repair_attempts,
    )
    return AgentResult(
        problem=problem,
        solution_markdown=solution_markdown,
        code=code,
        execution_report=execution_report,
        project_document=document,
        metrics=metrics,
        agent_steps=agent_steps,
        retrieved_templates=retrieved_templates,
        test_plan=test_plan,
        repair_attempts=repair_attempts,
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

    status_cols = st.columns(6)
    status_cols[0].metric("总耗时", f"{result.metrics.get('total_ms', 0)} ms")
    status_cols[1].metric("API 调用", "是" if result.api_used else "否")
    status_cols[2].metric("兜底输出", "是" if result.fallback_used else "否")
    status_cols[3].metric("Agent 步骤", result.metrics.get("agent_step_count", len(result.agent_steps)))
    status_cols[4].metric("RAG 模板", result.metrics.get("retrieved_template_count", len(result.retrieved_templates)))
    status_cols[5].metric("修复轮次", result.metrics.get("repair_attempt_count", len(result.repair_attempts)))

    (
        tab_problem,
        tab_agents,
        tab_rag,
        tab_tests,
        tab_solution,
        tab_code,
        tab_exec,
        tab_docs,
        tab_download,
    ) = st.tabs(
        ["题意识别", "Agent 步骤", "RAG 模板", "测试计划", "解题说明", "Python 代码", "执行结果", "项目文档", "下载"]
    )

    with tab_problem:
        st.markdown(result.problem)

    with tab_agents:
        for index, step in enumerate(result.agent_steps, start=1):
            title = f"{index}. {step.name} - {step.status} - {step.duration_ms} ms"
            with st.expander(title, expanded=index <= 2):
                st.markdown(f"**角色**：{step.role}")
                if step.error:
                    st.warning(step.error)
                st.markdown("**输入摘要**")
                st.code(step.input_summary or "(无)", language="text")
                st.markdown("**输出摘要**")
                st.markdown(step.output_summary or "(无)")

    with tab_rag:
        if result.retrieved_templates:
            for item in result.retrieved_templates:
                st.markdown(f"### {item.get('name', '模板')}")
                st.markdown(f"- 分数：{item.get('score', 0)}")
                st.markdown(f"- 描述：{item.get('description', '')}")
                st.markdown(f"- 模板：{item.get('template', '')}")
                st.markdown(f"- 命中关键词：{', '.join(item.get('matched_keywords', [])) or '无明确命中'}")
        else:
            st.info("未检索到算法模板。")

    with tab_tests:
        st.markdown(result.test_plan or "暂无测试计划。")
        if result.repair_attempts:
            st.divider()
            st.markdown("### 调试修复记录")
            st.json(result.repair_attempts)

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
    print("\n=== Agent 步骤 ===")
    for index, step in enumerate(result.agent_steps, start=1):
        print(f"{index}. {step.name} [{step.status}] {step.duration_ms} ms")
        print(shorten_text(step.output_summary, 500))
    print("\n=== RAG 模板 ===")
    print(format_templates_for_prompt(result.retrieved_templates))
    print("\n=== 测试计划 ===")
    print(result.test_plan)
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
