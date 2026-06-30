<template>
  <div class="trace-detail">
    <div class="trace-header">
      <h3>🔗 Trace 详情</h3>
      <el-tag size="small" type="info">trace_id: {{ traceId || '—' }}</el-tag>
    </div>

    <div v-if="!traceData || Object.keys(traceData).length === 0" class="trace-empty">
      <el-empty description="暂无 Trace 数据" :image-size="60" />
    </div>

    <div v-else class="trace-content">
      <div class="trace-overview">
        <div class="overview-item">
          <span class="label">开始时间</span>
          <span class="value">{{ traceData.start_time || '—' }}</span>
        </div>
        <div class="overview-item">
          <span class="label">结束时间</span>
          <span class="value">{{ traceData.end_time || '—' }}</span>
        </div>
        <div class="overview-item">
          <span class="label">总耗时</span>
          <span class="value">{{ traceData.total_duration || 0 }}ms</span>
        </div>
        <div class="overview-item">
          <span class="label">状态</span>
          <el-tag :type="traceData.status === 'success' ? 'success' : 'danger'" size="small">
            {{ traceData.status || '—' }}
          </el-tag>
        </div>
      </div>

      <div class="trace-nodes">
        <div
          v-for="(node, index) in traceData.nodes"
          :key="index"
          class="trace-node"
          :class="{
            'node-success': node.status === 'success' || node.status === 'completed',
            'node-failed': node.status === 'failed'
          }"
        >
          <div class="node-index">{{ index + 1 }}</div>
          <div class="node-content">
            <div class="node-header">
              <span class="node-name">{{ node.node_name || node.name || `节点 ${index + 1}` }}</span>
              <span class="node-duration">{{ node.duration_ms || 0 }}ms</span>
              <el-tag :type="node.status === 'success' || node.status === 'completed' ? 'success' : 'danger'" size="small">
                {{ node.status || 'pending' }}
              </el-tag>
            </div>
            <div class="node-body">
              <div v-if="node.input_data || node.input" class="node-detail">
                <span class="label">📥 输入</span>
                <pre>{{ formatContent(node.input_data || node.input) }}</pre>
              </div>
              <div v-if="node.output_data || node.output" class="node-detail">
                <span class="label">📤 输出</span>
                <pre>{{ formatContent(node.output_data || node.output) }}</pre>
              </div>
              <div v-if="node.error_message || node.error" class="node-detail">
                <span class="label error-label">❌ 错误</span>
                <pre class="error-text">{{ node.error_message || node.error }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="traceData.tool_calls && traceData.tool_calls.length > 0" class="tool-calls-section">
        <h4>🔧 工具调用</h4>
        <div
          v-for="(call, index) in traceData.tool_calls"
          :key="index"
          class="tool-call"
          :class="{ 'call-success': call.status === 'success', 'call-failed': call.status === 'failed' }"
        >
          <div class="tool-header">
            <span class="tool-name">{{ call.tool_name || '未知工具' }}</span>
            <span class="tool-duration">{{ call.duration_ms || 0 }}ms</span>
            <el-tag :type="call.status === 'success' ? 'success' : 'danger'" size="small">
              {{ call.status || 'pending' }}
            </el-tag>
          </div>
          <div class="tool-body">
            <div v-if="call.tool_input" class="tool-detail">
              <span class="label">📥 输入</span>
              <pre>{{ formatContent(call.tool_input) }}</pre>
            </div>
            <div v-if="call.tool_output" class="tool-detail">
              <span class="label">📤 输出</span>
              <pre>{{ formatContent(call.tool_output) }}</pre>
            </div>
            <div v-if="call.error_message" class="tool-detail">
              <span class="label error-label">❌ 错误</span>
              <pre class="error-text">{{ call.error_message }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  traceId: {
    type: String,
    default: ''
  },
  traceData: {
    type: Object,
    default: () => ({})
  }
})

const formatContent = (content) => {
  if (!content) return '（无内容）'
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2)
  }
  return content
}
</script>

<style scoped>
.trace-detail {
  margin: 16px 0;
  padding: 16px;
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.trace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.trace-header h3 {
  margin: 0;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}
.trace-empty { padding: 20px 0; }

.trace-overview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.15);
  border-radius: 8px;
  margin-bottom: 16px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}
.overview-item {
  display: flex;
  flex-direction: column;
}
.overview-item .label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}
.overview-item .value {
  font-size: 14px;
  font-weight: 500;
  color: #fff;
}

.trace-nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}
.trace-node {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.15);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.04);
  transition: all 0.2s;
}
.trace-node:hover {
  border-color: rgba(79, 110, 247, 0.3);
}
.node-success { border-left: 3px solid #4CAF50; }
.node-failed { border-left: 3px solid #EF5350; }
.node-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.4);
  flex-shrink: 0;
}
.node-content { flex: 1; }
.node-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.node-name {
  font-weight: 600;
  font-size: 14px;
  color: #fff;
}
.node-duration {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}
.node-body .node-detail { margin-top: 4px; }
.node-body .label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
  display: block;
}
.node-body pre {
  background: rgba(0, 0, 0, 0.2);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 2px 0;
  color: rgba(255, 255, 255, 0.7);
}
.error-text {
  color: #EF9A9A !important;
}
.error-label { color: #EF9A9A !important; }

.tool-calls-section h4 {
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 8px 0;
}
.tool-call {
  padding: 10px 12px;
  background: rgba(0, 0, 0, 0.15);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.04);
  margin-bottom: 6px;
}
.call-success { border-left: 3px solid #4CAF50; }
.call-failed { border-left: 3px solid #EF5350; }
.tool-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.tool-name {
  font-weight: 600;
  font-size: 14px;
  color: #fff;
}
.tool-duration {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}
.tool-body .tool-detail { margin-top: 4px; }
.tool-body .label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
  display: block;
}
.tool-body pre {
  background: rgba(0, 0, 0, 0.2);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 2px 0;
  color: rgba(255, 255, 255, 0.7);
}
</style>