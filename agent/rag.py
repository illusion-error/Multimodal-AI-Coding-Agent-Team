"""Hybrid RAG retrieval for algorithm templates and trusted history."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Tuple


RAG_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "hash_table",
        "name": "Hash Table",
        "problem_type": "lookup",
        "complexity": "O(n)",
        "keywords": ["two sum", "target", "index", "frequency", "hash", "map", "dict", "dictionary", "lookup", "count", "两数之和", "哈希", "字典", "频次", "下标"],
        "description": "Fast lookup, counting, deduplication, complement matching.",
        "template": "Iterate once, store seen values or counts in a dict, and query complements in O(1).",
    },
    {
        "id": "two_pointers",
        "name": "Two Pointers",
        "problem_type": "array_string",
        "complexity": "O(n)",
        "keywords": ["two pointers", "left right", "palindrome", "sorted array", "merge", "reverse", "双指针", "左右指针", "回文", "有序", "合并", "反转"],
        "description": "Process ordered arrays or strings from both ends or with fast/slow pointers.",
        "template": "Maintain left/right or slow/fast pointers and move them according to the invariant.",
    },
    {
        "id": "sliding_window",
        "name": "Sliding Window",
        "problem_type": "array_string",
        "complexity": "O(n)",
        "keywords": ["sliding window", "substring", "subarray", "longest", "shortest", "continuous", "window", "滑动窗口", "子串", "子数组", "最长", "最短", "连续"],
        "description": "Longest, shortest, or count problems over contiguous segments.",
        "template": "Expand right, shrink left while invalid, and update the answer when the window is valid.",
    },
    {
        "id": "dynamic_programming",
        "name": "Dynamic Programming",
        "problem_type": "optimization",
        "complexity": "O(n) to O(n^2)",
        "keywords": ["dynamic programming", "dp", "optimal", "ways", "knapsack", "fibonacci", "state transition", "动态规划", "最优", "方案数", "背包", "状态转移"],
        "description": "Optimal substructure, counting, path, sequence, or knapsack problems.",
        "template": "Define state, initialize boundaries, write transitions, and iterate in dependency order.",
    },
    {
        "id": "binary_search",
        "name": "Binary Search",
        "problem_type": "search",
        "complexity": "O(log n)",
        "keywords": ["binary search", "sorted", "first", "last", "boundary", "monotonic", "二分", "有序", "边界", "第一个", "最后一个", "单调"],
        "description": "Search in sorted data or answer space with a monotonic predicate.",
        "template": "Maintain low/high, test mid, and shrink the search interval until the boundary is found.",
    },
    {
        "id": "bfs_dfs",
        "name": "BFS / DFS",
        "problem_type": "graph",
        "complexity": "O(V+E)",
        "keywords": ["bfs", "dfs", "graph", "grid", "connected", "island", "path", "tree", "图", "网格", "连通", "岛屿", "路径", "深搜", "广搜"],
        "description": "Graph, grid, tree traversal, connected components, and path search.",
        "template": "Build neighbors, track visited, use BFS for shortest unweighted layers or DFS for traversal/backtracking.",
    },
    {
        "id": "stack_queue",
        "name": "Stack / Queue",
        "problem_type": "data_structure",
        "complexity": "O(n)",
        "keywords": ["stack", "queue", "parentheses", "recent", "deque", "栈", "队列", "括号", "最近", "先进先出", "后进先出"],
        "description": "Matching, recent relation, layered processing, and simulation.",
        "template": "Use a stack for nested/recent items and a queue/deque for FIFO or level-order processing.",
    },
    {
        "id": "greedy",
        "name": "Greedy",
        "problem_type": "optimization",
        "complexity": "O(n log n)",
        "keywords": ["greedy", "interval", "sort", "minimum", "maximum", "schedule", "choose", "贪心", "区间", "排序", "最小", "最大", "安排", "选择"],
        "description": "Problems where a locally optimal choice leads to a global optimum.",
        "template": "Sort or define a choice rule, take the best current option, and preserve the invariant.",
    },
    {
        "id": "sentiment_rule",
        "name": "Sentiment Rule",
        "problem_type": "nlp",
        "complexity": "O(n)",
        "keywords": ["sentiment", "positive", "negative", "neutral", "comment", "情感", "正向", "负向", "中性", "评论", "文本分类"],
        "description": "Lightweight fallback for sentiment analysis without a local trained model.",
        "template": "Score positive and negative lexicon hits, then classify as positive, negative, or neutral.",
    },
    {
        "id": "union_find",
        "name": "Union Find",
        "problem_type": "graph",
        "complexity": "Almost O(1)",
        "keywords": ["union find", "disjoint set", "connectivity", "components", "merge", "并查集", "连通", "集合", "合并", "朋友圈"],
        "description": "Dynamic connectivity, grouping, and cycle detection in undirected graphs.",
        "template": "Use parent and rank/size arrays, path compression, union, and find operations.",
    },
    {
        "id": "topological_sort",
        "name": "Topological Sort",
        "problem_type": "graph",
        "complexity": "O(V+E)",
        "keywords": ["topological", "course schedule", "dependency", "dag", "indegree", "拓扑", "课程表", "依赖", "入度", "有向无环"],
        "description": "Dependency ordering and cycle detection in directed graphs.",
        "template": "Compute indegrees, push zero-indegree nodes into a queue, and pop to build order.",
    },
    {
        "id": "backtracking",
        "name": "Backtracking",
        "problem_type": "search",
        "complexity": "Exponential",
        "keywords": ["backtracking", "permutation", "combination", "subset", "n queens", "回溯", "排列", "组合", "子集", "皇后"],
        "description": "Enumerating valid configurations with pruning.",
        "template": "Choose, recurse, undo; prune when constraints are violated.",
    },
    {
        "id": "prefix_sum",
        "name": "Prefix Sum",
        "problem_type": "array",
        "complexity": "O(n)",
        "keywords": ["prefix sum", "range sum", "subarray sum", "difference array", "前缀和", "区间和", "子数组和", "差分"],
        "description": "Fast range sum and subarray-sum counting.",
        "template": "Build prefix values; range sum is prefix[j]-prefix[i]. Use a dict for target subarray sums.",
    },
    {
        "id": "monotonic_stack",
        "name": "Monotonic Stack",
        "problem_type": "data_structure",
        "complexity": "O(n)",
        "keywords": ["monotonic stack", "next greater", "next smaller", "temperature", "histogram", "单调栈", "下一个更大", "下一个更小", "温度", "柱状图"],
        "description": "Nearest greater/smaller element and histogram rectangle problems.",
        "template": "Keep indices in monotonic order; pop while the current item resolves pending indices.",
    },
    {
        "id": "shortest_path",
        "name": "Shortest Path",
        "problem_type": "graph",
        "complexity": "O(E log V)",
        "keywords": ["shortest path", "dijkstra", "weighted graph", "distance", "最短路", "迪ijkstra", "加权图", "距离"],
        "description": "Weighted shortest path with non-negative edges.",
        "template": "Use a priority queue, relax edges, and skip stale distances.",
    },
    {
        "id": "tree_traversal",
        "name": "Tree Traversal",
        "problem_type": "tree",
        "complexity": "O(n)",
        "keywords": ["tree traversal", "binary tree", "preorder", "inorder", "postorder", "level order", "树遍历", "二叉树", "前序", "中序", "后序", "层序"],
        "description": "Tree traversal, depth, path, and aggregate calculations.",
        "template": "Use DFS recursion/stack for preorder/inorder/postorder or BFS queue for level order.",
    },
    {
        "id": "heap_priority_queue",
        "name": "Heap / Priority Queue",
        "problem_type": "data_structure",
        "complexity": "O(n log k)",
        "keywords": ["heap", "priority queue", "top k", "median", "kth", "堆", "优先队列", "前k", "第k", "中位数"],
        "description": "Top-K, kth element, streaming median, and greedy scheduling.",
        "template": "Use heapq; maintain a heap of size k or pop the highest-priority item each step.",
    },
    {
        "id": "interval_merge",
        "name": "Interval Merge",
        "problem_type": "interval",
        "complexity": "O(n log n)",
        "keywords": ["interval", "merge intervals", "overlap", "schedule", "区间", "合并区间", "重叠", "会议"],
        "description": "Merge overlapping intervals or detect scheduling conflicts.",
        "template": "Sort by start, then merge into the last interval when ranges overlap.",
    },
    {
        "id": "bit_manipulation",
        "name": "Bit Manipulation",
        "problem_type": "math",
        "complexity": "O(n)",
        "keywords": ["bit", "xor", "mask", "single number", "位运算", "异或", "掩码", "只出现一次"],
        "description": "XOR, masks, subset encoding, and parity tricks.",
        "template": "Use xor for cancellation, masks for state compression, and bit shifts for enumeration.",
    },
    {
        "id": "math_number_theory",
        "name": "Math / Number Theory",
        "problem_type": "math",
        "complexity": "Depends",
        "keywords": ["gcd", "lcm", "prime", "mod", "factor", "数学", "最大公约数", "最小公倍数", "质数", "取模", "因子"],
        "description": "GCD, primality, modular arithmetic, and factorization.",
        "template": "Apply Euclid gcd, modular arithmetic rules, and sieve/factor loops when needed.",
    },
    {
        "id": "string_parsing",
        "name": "String Parsing",
        "problem_type": "string",
        "complexity": "O(n)",
        "keywords": ["parse", "string", "token", "expression", "regex", "字符串", "解析", "表达式", "词法", "正则"],
        "description": "Parse structured strings, tokens, or simple expressions.",
        "template": "Scan characters, maintain state/stack, and validate tokens explicitly.",
    },
    {
        "id": "simulation",
        "name": "Simulation",
        "problem_type": "simulation",
        "complexity": "Depends",
        "keywords": ["simulate", "process", "game", "robot", "state", "模拟", "过程", "游戏", "机器人", "状态"],
        "description": "Step-by-step process simulation with explicit state changes.",
        "template": "Define state variables and update them exactly according to the rules.",
    },
    {
        "id": "hello_world",
        "name": "Hello World / Script Output",
        "problem_type": "script",
        "complexity": "O(1)",
        "keywords": ["hello world", "print", "script", "输出", "打印", "脚本", "hello"],
        "description": "Simple script output tasks where the expected output is part of the problem statement.",
        "template": "Implement a minimal main guard or solution function that returns/prints the required literal output.",
    },
]


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", (text or "").lower())
    return [word for word in words if word.strip()]


def cosine_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    left_counter = Counter(left)
    right_counter = Counter(right)
    if not left_counter or not right_counter:
        return 0.0
    common = set(left_counter) & set(right_counter)
    dot = sum(left_counter[token] * right_counter[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left_counter.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counter.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def template_document(template: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(template.get("name", "")),
            str(template.get("problem_type", "")),
            str(template.get("description", "")),
            str(template.get("template", "")),
            " ".join(str(keyword) for keyword in template.get("keywords", [])),
        ]
    )


def infer_problem_type(problem: str) -> str:
    text = (problem or "").lower()
    rules: List[Tuple[str, List[str]]] = [
        ("graph", ["graph", "grid", "path", "island", "课程", "拓扑", "连通", "图", "网格"]),
        ("array_string", ["array", "list", "string", "substring", "数组", "字符串", "子串"]),
        ("tree", ["tree", "binary tree", "树", "二叉树"]),
        ("script", ["hello world", "print", "script", "输出", "打印"]),
        ("nlp", ["sentiment", "情感", "评论"]),
        ("optimization", ["minimum", "maximum", "optimal", "最小", "最大", "最优"]),
    ]
    for problem_type, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return problem_type
    return "general"


def history_pass_rate(item: Dict[str, Any]) -> float:
    metrics = item.get("metrics") or item.get("data", {}).get("metrics") or {}
    trusted = int(metrics.get("trusted_test_count") or 0)
    if metrics.get("semantic_verification_status") == "verified" and trusted > 0:
        return 1.0
    return 0.0


def retrieve_history_successes(problem: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Return only verified successful historical tasks as RAG history."""

    try:
        from backend.database import get_conn
    except Exception:
        return []

    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT task_id, status, problem, data
                FROM tasks
                ORDER BY created_at DESC
                LIMIT 100
                """
            ).fetchall()
        candidates = []
        for row in rows:
            item = dict(row)
            try:
                item["data"] = json.loads(item.get("data") or "{}")
            except Exception:
                item["data"] = {}
            candidates.append(item)
    except Exception:
        return []

    problem_tokens = tokenize(problem)
    results: List[Dict[str, Any]] = []
    for task in candidates:
        data = task.get("data") or {}
        metrics = data.get("metrics") or {}
        if task.get("status") != "completed":
            continue
        if metrics.get("semantic_verification_status") != "verified":
            continue
        if int(metrics.get("trusted_test_count") or 0) <= 0:
            continue
        task_problem = task.get("problem") or data.get("problem") or ""
        score = cosine_similarity(problem_tokens, tokenize(task_problem))
        if score <= 0:
            continue
        results.append(
            {
                "id": f"history:{task.get('task_id')}",
                "name": f"History Success {task.get('task_id')}",
                "problem_type": "history",
                "complexity": metrics.get("complexity", "unknown"),
                "description": task_problem[:240],
                "template": (data.get("code") or data.get("solution_markdown") or "")[:800],
                "matched_keywords": [],
                "source": "history",
                "history_pass_rate": 1.0,
                "keyword_score": 0.0,
                "vector_score": round(score, 4),
            }
        )
    results.sort(key=lambda item: item["vector_score"], reverse=True)
    return results[:limit]


def hybrid_retrieve(
    problem: str,
    top_k: int = 5,
    history_items: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Retrieve templates with keyword score + vector similarity + reranking."""

    top_k = max(1, min(int(top_k or 5), 10))
    problem_text = problem or ""
    problem_lower = problem_text.lower()
    problem_tokens = tokenize(problem_text)
    problem_type = infer_problem_type(problem_text)
    scored: Dict[str, Dict[str, Any]] = {}

    for template in RAG_TEMPLATES:
        matched = []
        for keyword in template.get("keywords", []):
            key = str(keyword).lower()
            if key and key in problem_lower:
                matched.append(str(keyword))
        keyword_score = len(matched) / max(1, len(template.get("keywords", [])))
        vector_score = cosine_similarity(problem_tokens, tokenize(template_document(template)))
        type_bonus = 0.15 if template.get("problem_type") in {problem_type, "general"} else 0.0
        score = keyword_score * 0.55 + vector_score * 0.35 + type_bonus
        item = dict(template)
        item.update(
            {
                "matched_keywords": matched,
                "keyword_score": round(keyword_score, 4),
                "vector_score": round(vector_score, 4),
                "history_pass_rate": 0.0,
                "score": round(score, 4),
                "source": "template",
                "rerank_reason": f"keyword={keyword_score:.2f}, vector={vector_score:.2f}, type_bonus={type_bonus:.2f}",
            }
        )
        scored[item["id"]] = item

    history_candidates = history_items if history_items is not None else retrieve_history_successes(problem_text)
    for history in history_candidates:
        item = dict(history)
        item["source"] = "history"
        item["history_pass_rate"] = history_pass_rate(item) or float(item.get("history_pass_rate") or 0.0)
        item["score"] = round(float(item.get("vector_score") or 0.0) * 0.55 + item["history_pass_rate"] * 0.35, 4)
        item["rerank_reason"] = f"verified_history, vector={item.get('vector_score', 0)}, pass_rate={item['history_pass_rate']}"
        scored[item["id"]] = item

    ranked = sorted(
        scored.values(),
        key=lambda item: (
            -float(item.get("score") or 0.0),
            -float(item.get("history_pass_rate") or 0.0),
            str(item.get("complexity") or ""),
            str(item.get("name") or ""),
        ),
    )
    selected = ranked[:top_k]
    if not selected:
        fallback = dict(RAG_TEMPLATES[0])
        fallback.update(
            {
                "matched_keywords": [],
                "keyword_score": 0.0,
                "vector_score": 0.0,
                "history_pass_rate": 0.0,
                "score": 0.0,
                "source": "template",
                "rerank_reason": "fallback_no_match",
            }
        )
        return [fallback]
    return selected


def templates_to_json(templates: List[Dict[str, Any]]) -> str:
    return json.dumps(templates, ensure_ascii=False, indent=2)
