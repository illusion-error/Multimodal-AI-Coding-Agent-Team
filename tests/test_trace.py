import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from backend.database import (
    init_db, get_conn, generate_trace_id, 
    insert_trace_node, insert_tool_call, get_trace_by_trace_id
)
import json

def test_trace_tables_created():
    """测试 trace 相关表是否创建成功"""
    init_db()
    
    with get_conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('trace_nodes', 'tool_calls', 'cache_entries', 'prompt_versions')"
        ).fetchall()
        table_names = [row['name'] for row in tables]
        
        assert 'trace_nodes' in table_names
        assert 'tool_calls' in table_names
        assert 'cache_entries' in table_names
        assert 'prompt_versions' in table_names

def test_tasks_trace_id_column():
    """测试 tasks 表是否有 trace_id 字段"""
    init_db()
    
    with get_conn() as conn:
        columns = conn.execute("PRAGMA table_info(tasks)").fetchall()
        col_names = [col['name'] for col in columns]
        
        assert 'trace_id' in col_names
        assert 'prompt_version' in col_names
        assert 'selected_model' in col_names
        assert 'route_reason' in col_names
        assert 'token_usage' in col_names
        assert 'estimated_cost' in col_names

def test_insert_and_query_trace():
    """测试插入和查询 trace 数据"""
    init_db()
    trace_id = generate_trace_id()
    
    # 插入节点
    node_id = insert_trace_node(
        trace_id=trace_id,
        node_name="test_agent",
        node_type="agent",
        status="completed",
        input_data={"test": "input"},
        output_data={"result": "output"}
    )
    assert node_id > 0
    
    # 插入工具调用
    tool_id = insert_tool_call(
        trace_id=trace_id,
        tool_name="test_tool",
        tool_input={"arg": "value"},
        tool_output={"result": "success"},
        status="completed"
    )
    assert tool_id > 0
    
    # 查询
    result = get_trace_by_trace_id(trace_id)
    assert len(result['nodes']) == 1
    assert result['nodes'][0]['node_name'] == 'test_agent'
    assert len(result['tool_calls']) == 1
    assert result['tool_calls'][0]['tool_name'] == 'test_tool'

def test_empty_trace_query():
    """测试查询空 trace"""
    init_db()
    result = get_trace_by_trace_id('non-existent-trace-id')
    assert result['task'] is None
    assert len(result['nodes']) == 0
    assert len(result['tool_calls']) == 0