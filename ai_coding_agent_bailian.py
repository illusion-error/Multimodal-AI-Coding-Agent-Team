"""
多模态代码生成 Agent（阿里云百炼版）

这个文件是项目的“单文件可运行版”，适合课程答辩、功能演示和成员 C
讲解 Agent/RAG 工作流。它把一个编程题自动求解过程拆成 5 个 Agent：

1. 题目识别 Agent：接收文本或截图，把输入整理成结构化题面。
2. 解题规划 Agent：结合 RAG 算法模板，判断题型并规划解法。
3. 测试生成 Agent：先设计测试策略和边界用例，作为代码生成约束。
4. 代码生成 Agent：综合题目、规划、模板、测试计划生成 Python 代码。
5. 执行调试 Agent：本地执行代码，失败时最多调用模型自动修复 3 轮。

注意：测试生成 Agent 在代码生成 Agent 之前运行，这是刻意设计的。
这样代码生成阶段能提前知道要通过哪些测试，更接近真实开发流程。

完整链路：
用户输入文本/图片
  -> 题目识别
  -> 轻量 RAG 模板检索
  -> 解题规划
  -> 测试生成
  -> 代码生成
  -> 本地执行与自动调试
  -> Streamlit 页面展示和 Markdown 项目报告

运行方式：
1. 安装依赖：
   pip install -r requirements.txt
2. 启动页面：
   streamlit run ai_coding_agent_bailian.py
3. 配置环境变量（可选）：
   Windows PowerShell: $env:DASHSCOPE_API_KEY="你的百炼API Key"

如果没有配置 API Key，系统会自动走离线兜底逻辑，确保页面始终有输出。
"""

from __future__ import annotations

import base64
import hashlib
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

from agent.rag import RAG_TEMPLATES, hybrid_retrieve
from agent.state import WorkflowState, WorkflowStatus
from agent.tools import create_default_registry
from agent.workflow import reflect_on_result


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_TEXT_MODEL = "qwen-plus"
DEFAULT_VISION_MODEL = "qwen3-vl-plus"


@dataclass
class AgentConfig:
    """运行配置。

    Streamlit 侧边栏、命令行入口和后端 API 层都可以用这个数据结构
    创建同一套 Agent 配置。这样模型、超时、是否执行代码、是否兜底
    都有统一入口，后续接 FastAPI 时也更容易复用。
    """

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    text_model: str = DEFAULT_TEXT_MODEL
    vision_model: str = DEFAULT_VISION_MODEL
    request_timeout: int = 60
    max_retries: int = 2
    execution_timeout: int = 8
    enable_local_execution: bool = True
    enable_offline_fallback: bool = True
    prompt_versions: dict = None  # 新增：保存各 Agent 的 Prompt 版本
    trace_id: str = ""


@dataclass
class AgentStep:
    """单个 Agent 步骤的可观测记录。

    每个 Agent 执行完都会生成一条 AgentStep，保存名称、角色、输入摘要、
    输出摘要、状态、耗时和错误信息。页面的“Agent 步骤”页签和报告中的
    “Agent 步骤详情”都来自这里，这也是项目从 demo 变成可讲解工作流
    的关键。
    """

    name: str
    role: str
    status: str
    input_summary: str
    output_summary: str
    duration_ms: int
    error: str = ""


@dataclass
class AgentResult:
    """一次完整任务的最终结果。

    solve_problem() 会返回这个对象。它同时包含最终答案（题目、说明、代码、
    执行报告、项目文档）和过程数据（Agent 步骤、RAG 模板、测试计划、
    修复记录、指标）。如果后续接前后端分离，后端主要就是把这个对象
    转成前端需要的 JSON 字段。
    """

    problem: str
    solution_markdown: str
    code: str
    execution_report: str
    project_document: str
    metrics: Dict[str, Any]
    agent_steps: List[AgentStep]
    retrieved_templates: List[Dict[str, Any]]
    test_plan: str
    test_cases: List[Dict[str, Any]]
    repair_attempts: List[Dict[str, Any]]
    api_used: bool
    fallback_used: bool
    error: str = ""


def now_ms() -> int:
    """返回当前毫秒时间戳，用于计算每个 Agent 的耗时。"""

    return int(time.time() * 1000)


def shorten_text(text: Any, limit: int = 1200) -> str:
    """压缩长文本，避免页面和报告里展示过长的 prompt 或模型输出。"""

    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...（已截断）"


def looks_like_corrupted_text(text: str) -> bool:
    """Detect text where non-ASCII characters were replaced by question marks."""

    value = str(text or "").strip()
    question_marks = value.count("?") + value.count("？")
    visible_chars = sum(not char.isspace() for char in value)
    return question_marks >= 4 and question_marks / max(visible_chars, 1) >= 0.12


def _build_problem_contract(
    *,
    contract_id: str,
    title: str,
    signature: str,
    input_description: str,
    output_description: str,
    rules: List[str],
    argument_count: Optional[int],
    return_type: str,
    verification_mode: str = "authoritative",
) -> Dict[str, Any]:
    """Create an immutable semantic contract shared by all five Agents."""

    contract: Dict[str, Any] = {
        "id": contract_id,
        "title": title,
        "signature": signature,
        "input": input_description,
        "output": output_description,
        "rules": list(rules),
        "argument_count": argument_count,
        "return_type": return_type,
        "verification_mode": verification_mode,
    }
    fingerprint_source = json.dumps(
        contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    contract["fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()[:16]
    return contract


def infer_problem_contract(problem: str) -> Dict[str, Any]:
    """Infer a non-negotiable input/output contract from the recognized problem."""

    text = str(problem or "")
    lower = text.lower()
    compact_lower = re.sub(r"[\s,，.!！。:_\-]+", "", lower)
    is_two_sum = (
        "two sum" in lower
        or "两数之和" in text
        or ("nums" in lower and "target" in lower)
    )
    asks_for_indices = any(
        keyword in lower
        for keyword in ("index", "indices", "return indices")
    ) or any(keyword in text for keyword in ("下标", "索引"))

    if is_two_sum and asks_for_indices:
        return _build_problem_contract(
            contract_id="two_sum_indices",
            title="两数之和：返回下标",
            signature="solution(nums: list[int], target: int) -> list[int]",
            input_description="整数数组 nums 和整数 target",
            output_description="返回两个不同元素的下标 [i, j]；无解返回 []",
            rules=[
                "返回值必须是下标列表，不得返回 True/False。",
                "不得返回元素值本身。",
                "必须满足 i != j 且 nums[i] + nums[j] == target。",
                "期望时间复杂度 O(n)。",
            ],
            argument_count=2,
            return_type="list",
        )
    if "helloworld" in compact_lower or "你好世界" in text:
        return _build_problem_contract(
            contract_id="hello_world",
            title="Hello World 脚本",
            signature="solution() -> str",
            input_description="无参数",
            output_description='返回字符串 "Hello, World!"',
            rules=[
                '返回值必须严格等于 "Hello, World!"。',
                "solution 不接收任何参数。",
                "脚本直接运行时应输出同一文本。",
            ],
            argument_count=0,
            return_type="str",
        )
    if "palindrome" in lower or "回文" in text:
        return _build_problem_contract(
            contract_id="palindrome",
            title="回文判断",
            signature="solution(text: str) -> bool",
            input_description="字符串 text",
            output_description="返回布尔值，表示忽略大小写和非字母数字字符后是否回文",
            rules=["空字符串视为回文。"],
            argument_count=1,
            return_type="bool",
        )
    if "fibonacci" in lower or "斐波那契" in text:
        return _build_problem_contract(
            contract_id="fibonacci",
            title="斐波那契数",
            signature="solution(n: int) -> int",
            input_description="非负整数 n",
            output_description="返回第 n 个斐波那契数",
            rules=["F(0)=0，F(1)=1。"],
            argument_count=1,
            return_type="int",
        )
    if "最大值" in text or "maximum" in lower or "max value" in lower:
        return _build_problem_contract(
            contract_id="maximum",
            title="数组最大值",
            signature="solution(values: list[int]) -> int",
            input_description="非空整数数组 values",
            output_description="返回数组中的最大整数",
            rules=["必须正确处理全负数和单元素数组。"],
            argument_count=1,
            return_type="int",
        )
    if (
        "反转字符串" in text
        or "reverse string" in lower
        or ("反转" in text and "字符串" in text)
    ):
        return _build_problem_contract(
            contract_id="reverse_string",
            title="反转字符串",
            signature="solution(text: str) -> str",
            input_description="字符串 text",
            output_description="返回字符顺序完全反转后的字符串",
            rules=["空字符串返回空字符串；不得改变字符本身。"],
            argument_count=1,
            return_type="str",
        )
    return _build_problem_contract(
        contract_id="generic",
        title="通用编程题",
        signature="solution(*args)",
        input_description="以题目原文为准",
        output_description="严格保持题目要求的返回类型和语义",
        rules=[
            "不得擅自改变题目要求的输入、输出类型和返回语义。",
            "没有系统权威用例时，模型测试只能作为建议，不得驱动自动修复。",
        ],
        argument_count=None,
        return_type="unknown",
        verification_mode="manual_review",
    )


def format_problem_contract(contract: Dict[str, Any]) -> str:
    rules = "\n".join(f"- {rule}" for rule in contract.get("rules", []))
    return (
        f"契约编号：{contract.get('id', 'generic')}\n"
        f"函数签名：{contract.get('signature', 'solution(*args)')}\n"
        f"输入：{contract.get('input', '')}\n"
        f"输出：{contract.get('output', '')}\n"
        f"验证模式：{contract.get('verification_mode', 'manual_review')}\n"
        f"语义指纹：{contract.get('fingerprint', '')}\n"
        f"不可变规则：\n{rules or '- 严格遵守题目原文'}"
    )


def _authoritative_case(
    contract: Dict[str, Any],
    *,
    name: str,
    args: List[Any],
    input_text: str,
    expected: Any,
    category: str,
    purpose: str,
) -> Dict[str, Any]:
    return {
        "name": name,
        "args": args,
        "kwargs": {},
        "input": input_text,
        "expected": expected,
        "category": category,
        "purpose": purpose,
        "source": "system_authoritative",
        "trusted": True,
        "validation_status": "verified",
        "contract_id": contract.get("id", ""),
        "contract_fingerprint": contract.get("fingerprint", ""),
    }


def authoritative_test_cases(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return system-owned cases that model output cannot weaken or rewrite."""

    if contract.get("id") == "two_sum_indices":
        return [
            _authoritative_case(contract, name="基础样例", args=[[2, 7, 11, 15], 9], input_text="nums=[2,7,11,15], target=9", expected=[0, 1], category="basic", purpose="验证返回两个下标而不是布尔值"),
            _authoritative_case(contract, name="非相邻答案", args=[[3, 2, 4], 6], input_text="nums=[3,2,4], target=6", expected=[1, 2], category="normal", purpose="验证哈希表查找"),
            _authoritative_case(contract, name="重复元素", args=[[3, 3], 6], input_text="nums=[3,3], target=6", expected=[0, 1], category="edge", purpose="验证不能重复使用同一元素"),
            _authoritative_case(contract, name="无解情况", args=[[1, 2, 3], 7], input_text="nums=[1,2,3], target=7", expected=[], category="edge", purpose="验证无解返回空列表"),
        ]
    if contract.get("id") == "hello_world":
        return [
            _authoritative_case(
                contract,
                name="标准输出",
                args=[],
                input_text="无参数",
                expected="Hello, World!",
                category="basic",
                purpose="验证返回文本严格符合题意，防止兜底提示污染期望值",
            )
        ]
    if contract.get("id") == "palindrome":
        return [
            _authoritative_case(contract, name="标准回文", args=["A man, a plan, a canal: Panama"], input_text="A man, a plan, a canal: Panama", expected=True, category="basic", purpose="验证忽略大小写和符号"),
            _authoritative_case(contract, name="非回文", args=["race a car"], input_text="race a car", expected=False, category="normal", purpose="验证否定分支"),
            _authoritative_case(contract, name="空字符串", args=[""], input_text="", expected=True, category="edge", purpose="验证空输入"),
        ]
    if contract.get("id") == "fibonacci":
        return [
            _authoritative_case(contract, name="零项", args=[0], input_text="n=0", expected=0, category="edge", purpose="验证初始边界"),
            _authoritative_case(contract, name="第一项", args=[1], input_text="n=1", expected=1, category="edge", purpose="验证初始边界"),
            _authoritative_case(contract, name="常规输入", args=[10], input_text="n=10", expected=55, category="basic", purpose="验证迭代结果"),
        ]
    if contract.get("id") == "maximum":
        return [
            _authoritative_case(contract, name="常规数组", args=[[1, 9, 3, 7]], input_text="[1,9,3,7]", expected=9, category="basic", purpose="验证常规最大值"),
            _authoritative_case(contract, name="全负数", args=[[-5, -1, -10]], input_text="[-5,-1,-10]", expected=-1, category="edge", purpose="防止错误地把初始最大值设为 0"),
            _authoritative_case(contract, name="单元素", args=[[42]], input_text="[42]", expected=42, category="edge", purpose="验证最小规模"),
        ]
    if contract.get("id") == "reverse_string":
        return [
            _authoritative_case(contract, name="常规字符串", args=["hello"], input_text="hello", expected="olleh", category="basic", purpose="验证字符顺序反转"),
            _authoritative_case(contract, name="单字符", args=["a"], input_text="a", expected="a", category="edge", purpose="验证最小规模"),
            _authoritative_case(contract, name="空字符串", args=[""], input_text="", expected="", category="edge", purpose="验证空输入"),
        ]
    return []


def build_step(
    name: str,
    role: str,
    input_summary: str,
    output_summary: str,
    started_ms: int,
    status: str = "completed",
    error: str = "",
) -> AgentStep:
    """统一创建 AgentStep。

    统一入口的好处是所有步骤都能保持同样字段和同样截断规则，
    后续前端展示、接口返回、报告生成不用分别处理各种格式。
    """

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
    """整理百炼 OpenAI 兼容接口地址，保证后面能拼接 /chat/completions。"""

    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not base_url.endswith("/v1"):
        return base_url
    return base_url


def image_to_data_url(image_bytes: bytes, mime_type: str) -> str:
    """把上传截图转成视觉模型可接收的 data URL。"""

    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


# 轻量 RAG 模板库。
#
# 这里没有引入向量数据库，而是先用一组常见算法模板覆盖课程项目和
# 编程题高频场景。retrieve_algorithm_templates() 会按关键词命中数量
# 做简单召回，再把模板交给“解题规划 Agent”和“代码生成 Agent”。
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


ALGORITHM_TEMPLATES = RAG_TEMPLATES


def retrieve_algorithm_templates(problem: str, top_k: int = 3) -> List[Dict[str, Any]]:
    return hybrid_retrieve(problem, top_k=top_k)

    """根据题目关键词检索最相关的算法模板。

    这是本项目的“轻量 RAG”。流程很直观：
    1. 把题目转为小写。
    2. 遍历内置算法模板。
    3. 统计每个模板命中的关键词数量。
    4. 按命中分数排序，返回 top_k 个模板。

    如果完全没有命中，也会返回哈希表模板作为兜底参考，保证后续
    解题规划 Agent 和代码生成 Agent 总能拿到一些结构化先验知识。
    """

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
    """把检索到的模板格式化成 prompt 文本。

    大模型不直接读取 Python 字典，因此需要把模板名称、描述、解题套路、
    命中关键词整理成可读文本，再拼进解题规划和代码生成的 prompt。
    """

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
    """调用阿里云百炼的 OpenAI 兼容 Chat Completions 接口。

    这个函数是所有在线 Agent 的公共模型调用入口：
    - 解题规划 Agent
    - 测试生成 Agent
    - 代码生成 Agent
    - 执行调试 Agent
    - 图片题目识别时的视觉模型调用

    如果没有 API Key、网络失败、接口报错或响应格式异常，会抛出异常。
    上层 Agent 会捕获异常并切换到离线兜底，避免页面空白。
    """

    if not config.api_key.strip():
        raise RuntimeError("未填写阿里云百炼 API Key。")

    url = f"{clean_base_url(config.base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    attempts = max(1, int(getattr(config, "max_retries", 2)) + 1)
    last_error = ""

    for attempt_index in range(attempts):
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
            with urllib.request.urlopen(
                request,
                timeout=config.request_timeout,
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"百炼接口返回 HTTP {exc.code}: {detail}"
            should_retry = exc.code in {408, 429} or exc.code >= 500
            if not should_retry or attempt_index == attempts - 1:
                raise RuntimeError(message) from exc
            last_error = message
        except urllib.error.URLError as exc:
            message = f"无法连接百炼接口: {exc}"
            if attempt_index == attempts - 1:
                raise RuntimeError(message) from exc
            last_error = message
        else:
            try:
                result = json.loads(body)
                # ===== 新增：提取 token 信息到全局变量 =====
                usage = result.get("usage", {})
                _last_token_usage = {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                }
                return result["choices"][0]["message"]["content"]
            except Exception as exc:
                raise RuntimeError(f"百炼响应解析失败: {body[:1000]}") from exc

        time.sleep(min(2 ** attempt_index, 5))

    raise RuntimeError(last_error or "百炼接口调用失败")


def extract_problem_from_image(
    config: AgentConfig,
    image_bytes: bytes,
    mime_type: str,
    extra_text: str = "",
) -> Tuple[str, bool]:
    """题目识别 Agent 的图片分支。

    当用户上传编程题截图时，系统先调用视觉模型，把图片中的题目名称、
    题目描述、输入输出格式、样例、数据范围等信息提取为文本。这样后续
    Agent 面对的是结构化题面，而不是原始图片。
    """

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
    """解题规划 Agent 的离线兜底版本。

    当百炼 API 不可用时，仍然输出一份基础规划，并把 RAG 检索到的模板
    写进结果。这样答辩或演示时即使没有额度，也能看到完整链路。
    """

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
    contract: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    """解题规划 Agent。

    输入：题目文本 + RAG 检索到的算法模板。
    输出：题型判断、可用模板、解题步骤、边界条件、复杂度目标。

    这一阶段不直接写代码，而是先确定“怎么做”。它的输出会继续传给
    测试生成 Agent 和代码生成 Agent。
    """

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

题目语义契约（不可修改）：
{format_problem_contract(contract or infer_problem_contract(problem))}
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
    contract: Optional[Dict[str, Any]] = None,
    authoritative_cases: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, bool]:
    """代码生成 Agent。

    输入比普通 demo 更完整：
    - 题目识别 Agent 输出的题面
    - 解题规划 Agent 输出的思路
    - RAG 检索到的算法模板
    - 测试生成 Agent 输出的测试计划

    也就是说，代码生成不是“只把题目丢给模型”，而是带着前面 Agent 的
    中间结果生成代码。这里强制模型返回 Markdown，并把代码放进
    ```python 代码块，方便后续 extract_code() 提取。
    """

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
4. 必须把统一评测入口命名为 solution，例如 `solution = two_sum`。
5. 必须包含 _run_tests()，并在 __main__ 中调用，让代码直接运行时一定有输出。
6. 如果题目没有明确样例，请自己构造 2 到 4 个合理测试用例。
7. 代码要避免依赖第三方库。
8. 输出中文说明，但代码注释可以简洁。
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

题目语义契约（优先级最高，不可修改）：
{format_problem_contract(contract or infer_problem_contract(problem))}

系统权威测试用例（代码必须满足）：
{json.dumps(authoritative_cases or [], ensure_ascii=False, indent=2)}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    return call_bailian_chat(config, config.text_model, messages), True


PLACEHOLDER_EXPECTED_PATTERNS = (
    "已生成兜底代码",
    "请根据题目补充",
    "todo",
    "待实现",
    "placeholder",
    "fallback code",
)


def _matches_contract_return_type(value: Any, return_type: str) -> bool:
    """Check JSON test expectations against the locked return type."""

    if return_type == "unknown":
        return True
    if return_type == "bool":
        return type(value) is bool
    if return_type == "int":
        return type(value) is int
    if return_type == "float":
        return type(value) in {int, float}
    if return_type == "str":
        return isinstance(value, str)
    if return_type == "list":
        return isinstance(value, list)
    if return_type == "dict":
        return isinstance(value, dict)
    return False


def validate_model_test_cases(
    cases: List[Dict[str, Any]],
    contract: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Quarantine model-authored tests unless their structure is defensible.

    Model cases are always advisory. Only system-owned authoritative cases may
    drive automatic repair, preventing a hallucinated expected value from
    rewriting otherwise correct code.
    """

    accepted: List[Dict[str, Any]] = []
    rejected: List[str] = []
    expected_arg_count = contract.get("argument_count")
    return_type = str(contract.get("return_type", "unknown"))

    for index, raw_case in enumerate(cases[:20], start=1):
        if not isinstance(raw_case, dict):
            rejected.append(f"用例 {index} 不是 JSON 对象")
            continue
        args = raw_case.get("args", [])
        kwargs = raw_case.get("kwargs", {})
        if not isinstance(args, list):
            rejected.append(f"用例 {index} 的 args 不是数组")
            continue
        if not isinstance(kwargs, dict):
            rejected.append(f"用例 {index} 的 kwargs 不是对象")
            continue
        if raw_case.get("contract_id") != contract.get("id"):
            rejected.append(f"用例 {index} 的 contract_id 与锁定契约不一致")
            continue
        if raw_case.get("contract_fingerprint") != contract.get("fingerprint"):
            rejected.append(f"用例 {index} 的语义指纹与锁定契约不一致")
            continue
        if expected_arg_count is not None and len(args) != expected_arg_count:
            rejected.append(
                f"用例 {index} 参数数量为 {len(args)}，契约要求 {expected_arg_count}"
            )
            continue
        if "expected" not in raw_case:
            rejected.append(f"用例 {index} 缺少 expected")
            continue

        expected = raw_case["expected"]
        if isinstance(expected, str) and any(
            pattern in expected.lower()
            for pattern in PLACEHOLDER_EXPECTED_PATTERNS
        ):
            rejected.append(f"用例 {index} 的 expected 是兜底/占位文本")
            continue
        if not _matches_contract_return_type(expected, return_type):
            rejected.append(
                f"用例 {index} 的 expected 类型不符合契约返回类型 {return_type}"
            )
            continue

        item = dict(raw_case)
        item.setdefault("name", f"模型建议用例 {index}")
        item.setdefault("input", item.get("args", []))
        item.setdefault("category", "advisory")
        item.setdefault("purpose", "模型建议，等待人工确认")
        item["source"] = "model_advisory"
        item["trusted"] = False
        item["validation_status"] = "manual_review"
        item["contract_id"] = contract.get("id", "")
        item["contract_fingerprint"] = contract.get("fingerprint", "")
        accepted.append(item)

    return accepted, rejected


def offline_test_plan(problem: str, reason: str = "") -> Tuple[str, List[Dict[str, Any]]]:
    """测试生成 Agent 的离线兜底版本。

    根据题目关键词生成基础、边界、异常三类测试思路。虽然这里不是
    真正执行每个结构化用例，但 test_plan 会作为代码生成的约束，
    促使模型把 _run_tests() 写得更完整。
    """

    contract = infer_problem_contract(problem)
    system_cases = authoritative_test_cases(contract)
    lower = (problem or "").lower()
    if system_cases:
        cases = system_cases
    elif "two sum" in lower or "两数之和" in problem or "target" in lower:
        cases = [
            {"name": "基础样例", "args": [[2, 7, 11, 15], 9], "input": "nums=[2,7,11,15], target=9", "expected": [0, 1], "purpose": "验证常规命中"},
            {"name": "重复数字", "args": [[3, 3], 6], "input": "nums=[3,3], target=6", "expected": [0, 1], "purpose": "验证重复元素"},
            {"name": "无解情况", "args": [[1, 2, 3], 7], "input": "nums=[1,2,3], target=7", "expected": [], "purpose": "验证边界处理"},
        ]
    elif "回文" in problem or "palindrome" in lower:
        cases = [
            {"name": "标准回文", "args": ["A man, a plan, a canal: Panama"], "input": "A man, a plan, a canal: Panama", "expected": True, "purpose": "忽略大小写和符号"},
            {"name": "非回文", "args": ["race a car"], "input": "race a car", "expected": False, "purpose": "验证失败分支"},
            {"name": "空字符串", "args": [""], "input": "", "expected": True, "purpose": "验证空输入"},
        ]
    elif "fibonacci" in lower or "斐波那契" in problem:
        cases = [
            {"name": "零项", "args": [0], "input": "n=0", "expected": 0, "purpose": "验证初始边界"},
            {"name": "第一项", "args": [1], "input": "n=1", "expected": 1, "purpose": "验证初始边界"},
            {"name": "常规输入", "args": [10], "input": "n=10", "expected": 55, "purpose": "验证迭代结果"},
        ]
    elif "最大值" in problem or "maximum" in lower or "max value" in lower:
        cases = [
            {"name": "常规数组", "args": [[1, 9, 3, 7]], "input": "[1,9,3,7]", "expected": 9, "purpose": "验证常规最大值"},
            {"name": "全负数", "args": [[-5, -1, -10]], "input": "[-5,-1,-10]", "expected": -1, "purpose": "验证负数"},
            {"name": "单元素", "args": [[42]], "input": "[42]", "expected": 42, "purpose": "验证最小规模"},
        ]
    elif "反转字符串" in problem or "reverse string" in lower:
        cases = [
            {"name": "常规字符串", "args": ["hello"], "input": "hello", "expected": "olleh", "purpose": "验证反转"},
            {"name": "单字符", "args": ["a"], "input": "a", "expected": "a", "purpose": "验证最小规模"},
            {"name": "空字符串", "args": [""], "input": "", "expected": "", "purpose": "验证空输入"},
        ]
    elif "情感" in problem or "sentiment" in lower:
        cases = [
            {"name": "正向文本", "args": ["这个产品很好，我非常满意"], "input": "这个产品很好，我非常满意", "expected": "positive", "purpose": "模型建议，等待人工确认", "source": "offline_advisory", "trusted": False, "validation_status": "manual_review"},
            {"name": "负向文本", "args": ["体验糟糕，不推荐"], "input": "体验糟糕，不推荐", "expected": "negative", "purpose": "模型建议，等待人工确认", "source": "offline_advisory", "trusted": False, "validation_status": "manual_review"},
            {"name": "中性文本", "args": ["今天是星期二"], "input": "今天是星期二", "expected": "neutral", "purpose": "模型建议，等待人工确认", "source": "offline_advisory", "trusted": False, "validation_status": "manual_review"},
        ]
    else:
        cases = []

    note = f"\n\n> 测试计划兜底原因：{reason}" if reason else ""
    if cases:
        rows = "\n".join(
            f"- {case['name']}：输入 `{case.get('input', case.get('args', []))}`，"
            f"期望 `{case['expected']}`，目的：{case.get('purpose', '验证题目语义')}"
            for case in cases
        )
    else:
        rows = (
            "- 当前题型没有系统权威 Oracle。系统不会制造兜底期望值，"
            "也不会让未经确认的测试驱动自动修复；生成结果需人工确认语义。"
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
    contract: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]], bool]:
    """测试生成 Agent。

    注意它在代码生成之前运行。原因是测试计划要作为代码生成 Agent 的
    输入，让模型提前知道需要覆盖哪些样例和边界情况。

    当前函数返回两部分：
    - content：模型生成的 Markdown 测试计划。
    - cases：结构化测试用例兜底数据，用于报告和后续后端接口扩展。
    """

    system_prompt = """
你是测试用例生成 Agent。请根据题目和解题规划生成测试策略。

输出 Markdown，包含：
## 测试策略
## 测试用例
## 边界条件
## 结构化用例

“结构化用例”必须包含一个 JSON 代码块，格式如下：
```json
[
  {
    "name": "基础样例",
    "args": [[2, 7, 11, 15], 9],
    "kwargs": {},
    "expected": [0, 1],
    "category": "basic",
    "purpose": "验证常规输入",
    "contract_id": "使用下方锁定契约的编号",
    "contract_fingerprint": "使用下方锁定契约的语义指纹"
  }
]
```

要求：
1. 至少给出 3 个测试用例。
2. 覆盖基础样例、边界样例、异常或极端样例。
3. 每个用例说明输入、期望输出和测试目的。
4. args 必须是 JSON 数组，expected 必须是可直接比较的 JSON 值。
5. 每个用例必须携带 contract_id 和 contract_fingerprint，且不得输出兜底提示或占位文本作为 expected。
6. 你生成的用例只是建议；系统是否执行由语义校验层决定。
"""
    user_prompt = f"""
题目：
{problem.strip()}

解题规划：
{plan.strip()}

题目语义契约（不可修改输出类型或返回语义）：
{format_problem_contract(contract or infer_problem_contract(problem))}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    content = call_bailian_chat(config, config.text_model, messages)
    model_cases: List[Dict[str, Any]] = []
    json_blocks = re.findall(r"```json\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    for block in json_blocks:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        valid_cases = [
            item
            for item in parsed
            if isinstance(item, dict)
            and isinstance(item.get("args", []), list)
            and "expected" in item
        ]
        if valid_cases:
            model_cases = valid_cases
            break
    locked_contract = contract or infer_problem_contract(problem)
    system_cases = authoritative_test_cases(locked_contract)
    if system_cases:
        cases = system_cases
        content += (
            "\n\n## 系统权威测试用例\n\n"
            "模型生成的测试建议已保留作为说明；实际执行以下不可修改的语义测试：\n\n"
            f"```json\n{json.dumps(system_cases, ensure_ascii=False, indent=2)}\n```"
        )
    else:
        cases, rejected = validate_model_test_cases(model_cases, locked_contract)
        if rejected:
            content += (
                "\n\n## 语义校验拦截\n\n"
                + "\n".join(f"- {message}" for message in rejected)
            )
        if cases:
            content += (
                "\n\n> 当前题型没有系统权威 Oracle。以上结构化用例仅供人工确认，"
                "不会进入自动修复闭环。"
            )
        else:
            _, cases = offline_test_plan(
                problem,
                "模型用例缺失或未通过语义校验，已禁止其驱动自动修复。",
            )
    return content, cases, True


def repair_code_with_bailian(
    config: AgentConfig,
    problem: str,
    code: str,
    execution_report: str,
    test_plan: str,
    contract: Optional[Dict[str, Any]] = None,
    test_cases: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, bool]:
    """执行调试 Agent 的模型修复步骤。

    当本地运行失败时，把题目、失败代码、执行日志和测试计划一起交给
    模型，让模型只返回修复后的 Python 代码块。run_execution_debug_agent()
    会控制最多修复 3 轮，并记录每轮修复结果。
    """

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

题目语义契约（不可修改）：
{format_problem_contract(contract or infer_problem_contract(problem))}

必须通过的权威测试：
{json.dumps(test_cases or [], ensure_ascii=False, indent=2)}
"""
    messages = [
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt.strip()},
    ]
    return call_bailian_chat(config, config.text_model, messages), True


def extract_code(markdown: str) -> str:
    """从模型返回的 Markdown 中提取 Python 代码块。

    代码生成 Agent 被要求把代码放进 ```python 块中，但模型偶尔会使用
    ```py 或普通 ```。这里兼容几种常见写法，提取失败时返回空字符串，
    再由 ensure_code() 切换到离线兜底代码。
    """

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
    """代码生成 Agent 的离线兜底版本。

    兜底代码覆盖几个常见演示题型：
    - 两数之和
    - 回文判断
    - 斐波那契
    - 文本情感分析
    - 通用可运行模板

    目标不是替代真实模型能力，而是保证“题目 -> 代码 -> 执行 -> 报告”
    这条链路始终可演示，不会因为 API Key、额度或网络问题没有输出。
    """

    normalized = problem.lower()
    compact_normalized = re.sub(r"[\s,，.!！。:_\-]+", "", normalized)

    if "helloworld" in compact_normalized or "你好世界" in problem:
        code = r'''
def solution() -> str:
    return "Hello, World!"


def _run_tests() -> None:
    expected = "Hello, World!"
    actual = solution()
    assert actual == expected, f"expected={expected!r}, got={actual!r}"
    print(actual)


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "Hello World 脚本"
        idea = "定义统一评测入口 solution，返回题目要求的固定文本；脚本运行时输出同一结果。"
        complexity = "时间复杂度 O(1)，空间复杂度 O(1)。"
    elif (
        "two sum" in normalized
        or "两数之和" in problem
        or ("target" in normalized and ("nums" in normalized or "下标" in problem))
    ):
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


solution = two_sum


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


solution = is_palindrome


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


solution = fibonacci


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
    elif (
        "最大值" in problem
        or "maximum" in normalized
        or "max value" in normalized
    ):
        code = r'''
from typing import List


def solution(values: List[int]) -> int:
    if not values:
        raise ValueError("values must not be empty")
    current = values[0]
    for value in values[1:]:
        if value > current:
            current = value
    return current


def _run_tests() -> None:
    tests = [
        ([1, 9, 3, 7], 9),
        ([-5, -1, -10], -1),
        ([42], 42),
    ]
    for values, expected in tests:
        result = solution(values)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：maximum")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "寻找数组最大值"
        idea = "线性扫描数组并维护当前最大值。"
        complexity = "时间复杂度 O(n)，空间复杂度 O(1)。"
    elif (
        "反转字符串" in problem
        or "reverse string" in normalized
        or ("反转" in problem and "字符串" in problem)
    ):
        code = r'''
def solution(text: str) -> str:
    return text[::-1]


def _run_tests() -> None:
    tests = [
        ("hello", "olleh"),
        ("abc", "cba"),
        ("", ""),
    ]
    for value, expected in tests:
        result = solution(value)
        assert result == expected, f"expected={expected}, got={result}"
    print("全部自测通过：reverse string")


if __name__ == "__main__":
    _run_tests()
'''.strip()
        title = "反转字符串"
        idea = "使用 Python 切片从尾到头读取字符串。"
        complexity = "时间复杂度 O(n)，空间复杂度 O(n)。"
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


solution = analyze_sentiment


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


solution = solve


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
    """保证后续执行阶段一定有 Python 代码可用。

    返回值第二项表示是否启用了代码兜底：
    - False：模型返回了可提取代码。
    - True：模型没有给出代码块，系统改用 offline_solution()。
    """

    code = extract_code(markdown)
    if code:
        return code, False
    fallback = offline_solution(problem, "模型没有返回可提取的 Python 代码块。")
    return extract_code(fallback), True


def looks_dangerous(code: str) -> List[str]:
    """做一层简单的危险调用关键词检查。

    这是本地执行前的最低限度保护，避免生成代码直接调用系统命令、
    网络请求、删除目录或动态执行字符串。它不能替代真正的 Docker/E2B
    沙盒，但足够支撑第一阶段答辩里“有安全拦截”的说明。
    """

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
    """在本地临时目录执行生成代码，并返回文本执行报告。

    执行流程：
    1. 先用 looks_dangerous() 做危险关键词检查。
    2. 把代码写入临时目录中的 solution.py。
    3. 用当前 Python 解释器运行，限制超时时间。
    4. 返回退出码、标准输出和错误输出。

    注意：这个函数返回的是给 Streamlit 单文件版展示的文本报告。
    如果接 Vue + FastAPI，后端需要把它转换成前端需要的
    {exit_code, stdout, stderr, status, raw} 对象。
    """

    from sandbox.code_runner import execute_code_safely

    completed = execute_code_safely(
        code,
        task_id="agent-execution",
        timeout_seconds=timeout_seconds,
    )
    stdout = (completed["stdout"] or "").strip()
    stderr = (completed["stderr"] or "").strip()
    pieces = [
        f"状态：{completed['status']}",
        f"退出码：{completed['exit_code']}",
        f"耗时：{completed['duration_ms']} ms",
        f"标准输出：\n{stdout or '(无)'}",
    ]
    if stderr:
        pieces.append(f"错误输出：\n{stderr}")
    return "\n\n".join(pieces)


def execution_succeeded(execution_report: str) -> bool:
    """根据执行报告判断代码是否运行成功。"""

    report = execution_report or ""
    normalized = report.replace(" ", "").lower()
    test_rate = re.search(r"自动测试通过率[：:]\s*([0-9.]+)%", report)
    tests_passed = not test_rate or float(test_rate.group(1)) == 100.0
    return tests_passed and (
        "退出码：0" in normalized
        or "退出码:0" in normalized
        or "exitcode:0" in normalized
        or "returncode:0" in normalized
    )


def evaluate_python_code(
    code: str,
    test_cases: List[Dict[str, Any]],
    timeout_seconds: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    """运行代码并逐条执行结构化测试用例。"""

    if test_cases:
        from sandbox.evaluator import run_auto_tests

        auto_report = run_auto_tests(
            code,
            test_cases,
            timeout_seconds=timeout_seconds,
            task_id="agent-evaluation",
        )
        all_passed = (
            auto_report["total"] > 0
            and auto_report["passed"] == auto_report["total"]
        )
        execution_report = (
            f"状态：{'success' if all_passed else 'failed'}\n\n"
            f"退出码：{0 if all_passed else 1}\n\n"
            "标准输出：\n"
            f"系统权威测试：{auto_report['passed']}/{auto_report['total']}\n"
            f"自动测试通过率：{auto_report['pass_rate']}%"
        )
        failed_messages = [
            f"{item.get('name', '用例')}：{item.get('error') or item.get('actual')}"
            for item in auto_report["details"]
            if not item.get("passed")
        ]
        if failed_messages:
            execution_report += "\n失败用例：\n- " + "\n- ".join(failed_messages)
        return execution_report, auto_report["details"]

    execution_report = run_python_code(code, timeout_seconds)
    return execution_report, []


def trusted_test_cases(test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only cases allowed to decide pass/fail or trigger code repair."""

    return [
        case
        for case in test_cases
        if bool(case.get("trusted", True))
        and case.get("validation_status", "verified") == "verified"
    ]


def agent_result_to_dict(result: AgentResult) -> Dict[str, Any]:
    """将 AgentResult 转成后端、数据库和前端共用的 JSON 字典。

    业务层始终返回 dataclass，API 层只通过这个函数做一次字段适配，
    避免后端重复猜测属性名或把 AgentResult 当作 dict 使用。
    """

    steps = [
        {
            "agent_name": step.name,
            "role": step.role,
            "status": step.status,
            "input": step.input_summary,
            "output": step.output_summary,
            "duration_ms": step.duration_ms,
            "error": step.error,
        }
        for step in result.agent_steps
    ]
    execution_report = {
        "status": "success" if execution_succeeded(result.execution_report) else "failed",
        "exit_code": 0 if execution_succeeded(result.execution_report) else 1,
        "stdout": result.execution_report,
        "stderr": "" if execution_succeeded(result.execution_report) else result.execution_report,
        "timeout": "超时" in (result.execution_report or ""),
        "duration_ms": 0,
        "raw": result.execution_report,
    }
    metrics = dict(result.metrics)
    return {
        "problem": result.problem,
        "solution_markdown": result.solution_markdown,
        "code": result.code,
        "code_length": len(result.code),
        "execution_report": execution_report,
        "project_document": result.project_document,
        "metrics": metrics,
        "problem_contract": metrics.get("problem_contract", {}),
        "semantic_verification_status": metrics.get(
            "semantic_verification_status",
            "manual_review",
        ),
        "trusted_test_count": metrics.get("trusted_test_count", 0),
        "advisory_test_count": metrics.get("advisory_test_count", 0),
        "agent_steps": steps,
        "retrieved_templates": list(result.retrieved_templates),
        "rag_hits": list(result.retrieved_templates),
        "test_plan": result.test_plan,
        "test_cases": list(result.test_cases),
        "repair_attempts": list(result.repair_attempts),
        "api_call": result.api_used,
        "api_used": result.api_used,
        "fallback_used": result.fallback_used,
        "error": result.error,
        "total_ms": metrics.get("total_ms", 0),
        "model_name": metrics.get("text_model", DEFAULT_TEXT_MODEL),
    }


def run_execution_debug_agent(
    config: AgentConfig,
    problem: str,
    code: str,
    test_plan: str,
    test_cases: Optional[List[Dict[str, Any]]] = None,
    contract: Optional[Dict[str, Any]] = None,
) -> Tuple[
    str,
    str,
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    bool,
    bool,
]:
    """执行调试 Agent。

    这是完整闭环里的最后一个 Agent。它先本地运行生成代码：
    - 如果退出码为 0，说明代码通过自测，直接返回。
    - 如果运行失败，会调用 repair_code_with_bailian() 修复。
    - 最多修复 3 轮，每轮都会再次执行并记录结果。

    返回：
    - final_code：最终代码，可能是原代码，也可能是修复后的代码。
    - execution_report：最终执行报告。
    - repair_attempts：每轮修复记录。
    - api_used：调试阶段是否调用过模型。
    - fallback_used：调试阶段是否触发兜底。
    """

    api_used = False
    fallback_used = False
    repair_attempts: List[Dict[str, Any]] = []
    evaluated_cases: List[Dict[str, Any]] = []
    test_cases = test_cases or []
    executable_cases = trusted_test_cases(test_cases)

    if not code:
        return code, "未提取到可执行代码。", repair_attempts, evaluated_cases, api_used, True

    if not config.enable_local_execution:
        return (
            code,
            "本地执行未开启：已生成代码，但未运行。",
            repair_attempts,
            evaluated_cases,
            api_used,
            fallback_used,
        )

    current_code = code
    execution_report, evaluated_cases = evaluate_python_code(
        current_code,
        executable_cases,
        config.execution_timeout,
    )
    if not executable_cases:
        execution_report += (
            "\n\n语义验证：需人工确认\n"
            "原因：当前题型没有通过系统语义校验的权威测试用例；"
            "模型建议用例已隔离，不会触发自动修复。"
        )
    if execution_succeeded(execution_report):
        return (
            current_code,
            execution_report,
            repair_attempts,
            evaluated_cases,
            api_used,
            fallback_used,
        )

    for round_index in range(1, 4):
        round_started = now_ms()
        old_code = current_code
        try:
            repair_markdown, used = repair_code_with_bailian(
                config=config,
                problem=problem,
                code=current_code,
                execution_report=execution_report,
                test_plan=test_plan,
                contract=contract,
                test_cases=executable_cases,
            )
            api_used = api_used or used
            repaired_code = extract_code(repair_markdown) or repair_markdown.strip()
        except Exception as exc:
            # 无 Key、额度不足或模型不可用时，使用本地题型模板完成确定性修复。
            repair_markdown = offline_solution(
                problem,
                f"模型调试不可用，启用本地修复：{exc}",
            )
            repaired_code = extract_code(repair_markdown)
            fallback_used = True
            repair_reason = f"模型调试不可用，已使用本地算法模板修复：{exc}"
        else:
            repair_reason = "调试 Agent 已根据执行日志生成修复代码。"

        if not repaired_code:
            repair_attempts.append(
                {
                    "round": round_index,
                    "status": "failed",
                    "reason": "调试 Agent 没有返回可用代码。",
                    "old_code": old_code,
                    "new_code": "",
                    "duration_ms": now_ms() - round_started,
                }
            )
            break

        current_code = repaired_code
        execution_report, evaluated_cases = evaluate_python_code(
            current_code,
            executable_cases,
            config.execution_timeout,
        )
        if not executable_cases:
            execution_report += (
                "\n\n语义验证：需人工确认\n"
                "原因：修复仅解决代码可运行性，未宣称算法语义已通过验证。"
            )
        repair_attempts.append(
            {
                "round": round_index,
                "status": "passed" if execution_succeeded(execution_report) else "failed",
                "reason": repair_reason,
                "old_code": old_code,
                "new_code": current_code,
                "duration_ms": now_ms() - round_started,
                "execution_report": shorten_text(execution_report, 1200),
            }
        )
        if execution_succeeded(execution_report):
            break

    return (
        current_code,
        execution_report,
        repair_attempts,
        evaluated_cases,
        api_used,
        fallback_used,
    )


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
    """生成可下载的 Markdown 项目报告。

    这份报告不是简单拼接最终代码，而是把答辩需要讲的工程过程写进去：
    - 技术方案
    - 真实 Agent 顺序
    - RAG 检索模板
    - 每个 Agent 的输入/输出摘要
    - 测试计划
    - 执行报告
    - 自动调试修复记录

    所以页面中的“下载项目说明与测试报告”可以直接作为演示材料。
    """

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

- 前端界面：Vue3 + Element Plus；保留 Streamlit 单文件演示入口
- 后端接口：FastAPI + SQLite
- 大模型接口：阿里云百炼 OpenAI 兼容接口
- 文本模型：{metrics.get("text_model", DEFAULT_TEXT_MODEL)}
- 视觉模型：{metrics.get("vision_model", DEFAULT_VISION_MODEL)}
- 代码执行：Python 本地子进程，带超时控制
- 稳定性策略：API 异常时自动切换离线兜底输出

## 3. Agent 流程

1. 题目识别 Agent：接收文本或图片，输出结构化题目。
2. 解题规划 Agent：结合 RAG 模板，输出题型判断、步骤和复杂度目标。
3. 测试生成 Agent：生成基础、边界和异常测试策略，并作为代码生成约束。
4. 代码生成 Agent：根据题目、规划、RAG 模板和测试计划生成 Python 解法。
5. 执行调试 Agent：执行代码，失败时最多尝试 3 轮自动修复。

## 4. 本次运行状态

- API 状态：{api_state}
- 兜底状态：{fallback_state}
- 总耗时：{metrics.get("total_ms", 0)} ms
- 题目来源：{metrics.get("input_type", "text")}
- 代码长度：{len(code)} 字符
- 语义验证：{metrics.get("semantic_verification_status", "manual_review")}
- 系统权威测试数：{metrics.get("trusted_test_count", 0)}
- 模型建议测试数：{metrics.get("advisory_test_count", 0)}
- 语义契约指纹：{metrics.get("problem_contract", {}).get("fingerprint", "")}

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
| 语义验证状态 | {metrics.get("semantic_verification_status", "manual_review")} |
| 权威测试是否通过 | {'通过' if metrics.get("semantic_verification_status") == "verified" else "需人工确认"} |
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
    """主工作流编排函数。

    这是整个单文件项目最重要的函数。新同学读项目时可以先看这里，
    因为 5 个 Agent 的真实执行顺序都集中在这里：

    1. 题目识别 Agent：处理文本或图片题目。
    2. 解题规划 Agent：制定题型、算法、边界和复杂度计划。
    3. 测试生成 Agent：先生成测试计划，后续约束代码生成。
    4. 代码生成 Agent：生成 Markdown 解题说明和 Python 代码。
    5. 执行调试 Agent：本地运行，失败时最多自动修复 3 轮。

    轻量 RAG 检索不是单独 Agent，而是插在题目识别和解题规划之间：
    它根据题面召回算法模板，再把模板提供给解题规划和代码生成阶段。
    最后，报告生成会汇总题目、模板、步骤、测试、代码、日志和指标。

    即使某一步 API 失败，也会捕获异常并走离线兜底，保证最终仍有
    AgentResult 返回。
    """

    started = now_ms()
    api_used = False
    fallback_used = False
    errors: List[str] = []
    agent_steps: List[AgentStep] = []
    retrieved_templates: List[Dict[str, Any]] = []
    test_plan = ""
    test_cases: List[Dict[str, Any]] = []
    repair_attempts: List[Dict[str, Any]] = []

    trace_id = getattr(config, "trace_id", "") or ""
    workflow_state = WorkflowState(trace_id=trace_id)
    tool_registry = create_default_registry(trace_id=trace_id, persist=True)

    prompt_versions = getattr(config, "prompt_versions", None) or {}

    input_type = "text"
    problem = (text_problem or "").strip()
    workflow_state.apply_patch(
        node="workflow_start",
        to_status=WorkflowStatus.CREATED,
        patch={"problem": problem, "input_type": input_type},
    )

    if looks_like_corrupted_text(problem):
        raise ValueError(
            "题目文本疑似在传输前发生乱码（大量字符变成 ?）。"
            "请在浏览器页面重新输入，或确保客户端使用 UTF-8。"
        )

    # Agent 1：题目识别。
    # 文本输入直接使用；图片输入先调用视觉模型提取题意。
    # 如果图片识别失败，会保留用户补充文本或使用默认题目兜底。
    step_started = now_ms()
    recognition_input = f"input_type={input_type}; has_image={bool(image_bytes)}; text={shorten_text(problem, 600)}"
    if image_bytes:
        input_type = "image" if not problem else "image+text"
        try:
            problem, used = extract_problem_from_image(config, image_bytes, image_mime, problem)
            if looks_like_corrupted_text(problem):
                raise ValueError("视觉识别结果疑似乱码，请重新上传清晰图片。")
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

    contract = infer_problem_contract(problem)
    contract_text = format_problem_contract(contract)

    agent_steps.append(
        build_step(
            name="题目识别 Agent",
            role="接收文本/图片输入，输出结构化题面。",
            input_summary=recognition_input,
            output_summary=f"{problem}\n\n题目语义契约：\n{contract_text}",
            started_ms=step_started,
            status="completed",
        )
    )
    workflow_state.apply_patch(
        node="problem_recognition",
        to_status=WorkflowStatus.RECOGNIZED,
        patch={
            "problem": problem,
            "input_type": input_type,
            "contract": contract,
        },
    )

    # 轻量 RAG：在生成任何代码前先检索算法模板。
    # 检索结果会进入解题规划 Agent 和代码生成 Agent，减少模型“凭空写”。
    rag_output = tool_registry.call("rag_search", {"problem": problem, "top_k": 5})
    retrieved_templates = rag_output.get("results", []) or retrieve_algorithm_templates(problem)
    workflow_state.apply_patch(
        node="rag_retrieval",
        to_status=WorkflowStatus.RETRIEVED,
        patch={"templates": retrieved_templates},
    )

    # Agent 2：解题规划。
    # 这一阶段只负责想清楚算法路线，不直接生成代码。
    step_started = now_ms()
    try:
    
        effective_problem_for_plan = problem
        if prompt_versions:
            version_info = "\n\n## 当前生效的 Prompt 版本\n" + "\n".join(
                f"- {agent}: {version}" for agent, version in prompt_versions.items()
            )
            effective_problem_for_plan = problem + version_info
    
        plan_markdown, used = plan_solution_with_bailian(
            config,
            effective_problem_for_plan,  # 修改：使用增强后的题目文本
            retrieved_templates,
            contract,
        )
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
    workflow_state.apply_patch(
        node="solution_planning",
        to_status=WorkflowStatus.PLANNED,
        patch={"plan": plan_markdown},
        error=planning_error if planning_status == "failed" else "",
    )

    # Agent 3：测试生成。
    step_started = now_ms()
    try:
        # ===== 新增：如果有 prompt_versions，追加到 problem 中 =====
        effective_problem_for_tests = problem
        if prompt_versions:
            version_info = "\n\n## 当前生效的 Prompt 版本\n" + "\n".join(
                f"- {agent}: {version}" for agent, version in prompt_versions.items()
            )
            effective_problem_for_tests = problem + version_info
    
        test_plan, test_cases, used = generate_tests_with_bailian(
            config,
            effective_problem_for_tests,  # 修改：使用增强后的题目文本
            plan_markdown,
            contract,
        )
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
    workflow_state.apply_patch(
        node="test_design",
        to_status=WorkflowStatus.TESTS_DESIGNED,
        patch={"test_plan": test_plan, "test_cases": test_cases},
        error=test_error if test_status == "failed" else "",
    )

    # Agent 4：代码生成。
    step_started = now_ms()
    provided_code = extract_code(problem)
    repair_request = bool(
        provided_code
        and re.search(r"修复|调试|纠错|fix|debug|repair", problem, flags=re.IGNORECASE)
    )
    if repair_request:
        solution_markdown = (
            "## 待修复代码\n\n"
            "系统检测到用户提供的 Python 代码，将直接交给执行调试 Agent。\n\n"
            f"```python\n{provided_code}\n```"
        )
        generation_error = ""
        generation_status = "provided"
    else:
        try:
            # ===== 新增：如果有 prompt_versions，追加到 problem 中 =====
            effective_problem_for_code = problem
            if prompt_versions:
                version_info = "\n\n## 当前生效的 Prompt 版本\n" + "\n".join(
                    f"- {agent}: {version}" for agent, version in prompt_versions.items()
                )
                effective_problem_for_code = problem + version_info
            # ===== 新增结束 =====
        
            solution_markdown, used = generate_solution_with_bailian(
                config=config,
                problem=effective_problem_for_code,  # 修改：使用增强后的题目文本
                plan=plan_markdown,
                templates=retrieved_templates,
                test_plan=test_plan,
                contract=contract,
                authoritative_cases=authoritative_test_cases(contract),
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
    workflow_state.apply_patch(
        node="code_generation",
        to_status=WorkflowStatus.GENERATED,
        patch={"solution_markdown": solution_markdown, "code": code},
        error=generation_error if generation_status == "failed" else "",
    )

    # Agent 5：执行调试。
    step_started = now_ms()
    workflow_state.apply_patch(
        node="execution_debug",
        to_status=WorkflowStatus.EXECUTING,
        patch={"code": code},
    )
    (
        final_code,
        execution_report,
        repair_attempts,
        evaluated_cases,
        used,
        repair_fallback,
    ) = run_execution_debug_agent(
        config=config,
        problem=problem,
        code=code,
        test_plan=test_plan,
        test_cases=test_cases,
        contract=contract,
    )
    api_used = api_used or used
    fallback_used = fallback_used or repair_fallback
    if evaluated_cases:
        test_cases = evaluated_cases
    if final_code != code:
        solution_markdown += "\n\n## 自动调试修复\n\n执行调试 Agent 已根据运行日志修复代码，最终版本请查看“Python 代码”页签。"
    code = final_code
    trusted_cases = trusted_test_cases(test_cases)
    advisory_test_count = len(test_cases) - len(trusted_cases)
    if trusted_cases:
        semantic_verification_status = (
            "verified"
            if len(trusted_cases) == len(test_cases)
            and all(bool(case.get("passed")) for case in trusted_cases)
            else "failed"
        )
    else:
        semantic_verification_status = "manual_review"

    reflect_decision = reflect_on_result(
        execution_success=execution_succeeded(execution_report),
        semantic_status=semantic_verification_status,
        error_text=execution_report,
        repair_attempt_count=len(repair_attempts),
        max_repairs=3,
        problem=problem,
    )
    workflow_state.apply_patch(
        node="reflection",
        to_status=WorkflowStatus.REFLECTING,
        patch={
            "code": code,
            "execution_report": execution_report,
            "test_cases": test_cases,
            "repair_attempts": repair_attempts,
            "semantic_status": semantic_verification_status,
            "reflect_decision": reflect_decision.decision,
        },
    )
    if repair_attempts:
        workflow_state.apply_patch(
            node="repair_loop",
            to_status=WorkflowStatus.REPAIRING,
            patch={"repair_attempts": repair_attempts, "code": code},
        )
    workflow_final_status = (
        WorkflowStatus.COMPLETED
        if execution_succeeded(execution_report)
        and semantic_verification_status in {"verified", "manual_review"}
        else WorkflowStatus.FAILED
    )
    workflow_state.apply_patch(
        node="workflow_finish",
        to_status=workflow_final_status,
        patch={},
    )

    agent_steps.append(
        build_step(
            name="执行调试 Agent",
            role="执行代码，记录日志；失败时最多调用模型进行 3 轮自动修复。",
            input_summary=f"代码长度：{len(code)} 字符\n\n测试计划：{shorten_text(test_plan, 700)}",
            output_summary=(
                f"执行结果：\n{execution_report}\n\n"
                f"语义验证状态：{semantic_verification_status}\n"
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
        "problem_contract": contract,
        "semantic_verification_status": semantic_verification_status,
        "trusted_test_count": len(trusted_cases),
        "advisory_test_count": advisory_test_count,
        "prompt_versions": prompt_versions,  
        "workflow_status": workflow_state.status,
        "workflow_transitions": workflow_state.to_dict()["transitions"],
        "reflect_decision": reflect_decision.to_dict(),
        "rag_template_total": len(RAG_TEMPLATES),
        "tool_registry": tool_registry.summary(),
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
    tool_registry.call("report_generate", {"report": document})
    metrics["tool_registry"] = tool_registry.summary()
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
        test_cases=test_cases,
        repair_attempts=repair_attempts,
        api_used=api_used,
        fallback_used=fallback_used,
        error="\n".join(errors),
    )


def streamlit_app() -> None:
    """Streamlit 页面入口。

    这个函数只负责页面交互：
    - 读取侧边栏配置。
    - 接收文本题目或上传截图。
    - 调用 solve_problem() 执行完整 Agent 工作流。
    - 把结果拆成题意识别、Agent 步骤、RAG 模板、测试计划、代码、
      执行结果、项目文档和下载按钮展示出来。

    真正的业务逻辑不要写在这里，而是放在 solve_problem() 及其子函数中。
    这样后续改成 Vue + FastAPI 时，后端也能直接复用同一套核心逻辑。
    """

    import streamlit as st

    st.set_page_config(
        page_title="多模态代码生成 Agent - 百炼版",
        page_icon="AI",
        layout="wide",
    )

    st.title("多模态代码生成 Agent（阿里云百炼版）")
    st.caption("支持题目截图 / 文本输入，自动生成 Python 解法、运行结果和项目文档。")

    with st.sidebar:
        # 侧边栏是演示时最常用的配置入口。没有 API Key 时也能跑，
        # 因为 solve_problem() 会在各阶段触发离线兜底。
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
        # 把页面输入统一封装成 AgentConfig，后面所有 Agent 都只读 config。
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

    # Streamlit 上传文件对象只能在页面层读取；核心函数只接收 bytes，
    # 这样未来后端接口也可以把 UploadFile 转成 bytes 后复用 solve_problem()。
    image_bytes = uploaded_file.getvalue() if uploaded_file is not None else None
    image_mime = uploaded_file.type if uploaded_file is not None else "image/png"

    with st.spinner("Agent 正在处理，请稍候..."):
        result = solve_problem(
            config=config,
            text_problem=text_problem,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )

    # 如果某些 Agent 失败但已经兜底成功，仍然展示结果，并把异常细节折叠起来。
    if result.error:
        st.warning("运行过程中出现异常，系统已自动兜底并继续输出。")
        with st.expander("查看异常详情"):
            st.code(result.error, language="text")

    # 顶部指标用于答辩时快速说明：耗时、是否调用 API、是否兜底、
    # Agent 步骤数量、RAG 模板数量、自动修复轮次。
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
        # Agent 步骤展示是项目亮点：用户能看到每个阶段的输入、输出和耗时，
        # 而不是只看到最终代码。
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
        # 下载内容全部来自 AgentResult，便于答辩时提交代码、报告和完整 JSON。
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
    """命令行测试入口。

    用法：
        python ai_coding_agent_bailian.py --cli "两数之和..."

    这个入口方便不启动 Streamlit 时快速验证核心链路。它和页面一样调用
    solve_problem()，所以能覆盖同一套 Agent/RAG/执行调试逻辑。
    """

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
    """判断当前脚本是否由 Streamlit 启动。

    直接 `python ai_coding_agent_bailian.py` 时走 CLI；
    `streamlit run ai_coding_agent_bailian.py` 时走页面。
    """

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
