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
            'node-success': node.status === 'success',
            'node-failed': node.status === 'failed'
          }"
        >
          <div class="node-index">{{ index + 1 }}</div>
          <div class="node-content">
            <div class="node-header">
              <span class="node-name">{{ node.name || node.agent_name || `节点 ${index + 1}` }}</span>
              <span class="node-duration">{{ node.duration || 0 }}ms</span>
              <el-tag :type="node.status === 'success' ? 'success' : 'danger'" size="small">
                {{ node.status || 'pending' }}
              </el-tag>
            </div>
            <div class="node-body">
              <div v-if="node.input" class="node-detail">
                <span class="label">输入</span>
                <pre>{{ formatContent(node.input) }}</pre>
              </div>
              <div v-if="node.output" class="node-detail">
                <span class="label">输出</span>
                <pre>{{ formatContent(node.output) }}</pre>
              </div>
              <div v-if="node.error" class="node-detail">
                <span class="label error-label">错误</span>
                <pre class="error-text">{{ node.error }}</pre>
              </div>
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
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #ebeef5;
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
  color: #303133;
  font-size: 16px;
}
.trace-empty { padding: 20px 0; }
.trace-overview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  padding: 12px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 16px;
  border: 1px solid #ebeef5;
}
.overview-item {
  display: flex;
  flex-direction: column;
}
.overview-item .label {
  font-size: 12px;
  color: #909399;
}
.overview-item .value {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}
.trace-nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.trace-node {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  transition: all 0.2s;
}
.trace-node:hover { border-color: #409EFF; }
.node-success { border-left: 3px solid #67c23a; }
.node-failed { border-left: 3px solid #f56c6c; }
.node-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
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
  color: #303133;
}
.node-duration {
  font-size: 12px;
  color: #909399;
}
.node-body .node-detail { margin-top: 4px; }
.node-body .label {
  font-size: 12px;
  color: #909399;
  display: block;
}
.node-body pre {
  background: #f5f7fa;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 2px 0;
}
.error-text { color: #f56c6c; }
.error-label { color: #f56c6c; }
</style>