<template>
  <div class="agent-timeline">
    <div class="timeline-header">
      <h3>🤖 Agent 执行链路</h3>
      <div class="timeline-stats">
        <span class="stat-item">
          <span class="dot success"></span> 成功 {{ successCount }}
        </span>
        <span class="stat-item">
          <span class="dot failed"></span> 失败 {{ failedCount }}
        </span>
        <span class="stat-item">总耗时 {{ totalDuration }}ms</span>
      </div>
    </div>

    <div v-if="!steps || steps.length === 0" class="timeline-empty">
      <el-empty description="暂无 Agent 步骤数据" :image-size="60" />
    </div>

    <div v-else class="timeline-container">
      <div
        v-for="(step, index) in steps"
        :key="index"
        class="timeline-item"
        :class="{
          'is-completed': step.status === 'completed',
          'is-running': step.status === 'running',
          'is-failed': step.status === 'failed',
          'is-pending': step.status === 'pending' || !step.status
        }"
      >
        <div class="timeline-connector">
          <div class="timeline-dot" :class="getDotClass(step.status)">
            <span v-if="step.status === 'completed'">✓</span>
            <span v-else-if="step.status === 'failed'">✗</span>
            <span v-else-if="step.status === 'running'">⟳</span>
            <span v-else class="dot-number">{{ index + 1 }}</span>
          </div>
          <div v-if="index < steps.length - 1" class="timeline-line" :class="getLineClass(step.status)"></div>
        </div>

        <div class="timeline-content">
          <div class="step-header">
            <div class="step-info">
              <span class="step-name">{{ step.agent_name || step.step_name || `步骤 ${index + 1}` }}</span>
              <el-tag :type="getStatusTag(step.status)" size="small">
                {{ step.status || 'pending' }}
              </el-tag>
            </div>
            <span class="step-duration" v-if="step.duration_ms">
              ⏱️ {{ step.duration_ms }}ms
            </span>
          </div>

          <div class="step-body">
            <div class="step-input" v-if="step.input">
              <span class="label">📥 输入</span>
              <pre>{{ formatContent(step.input) }}</pre>
            </div>
            <div class="step-output" v-if="step.output">
              <span class="label">📤 输出</span>
              <pre>{{ formatContent(step.output) }}</pre>
            </div>
            <div class="step-error" v-if="step.error">
              <span class="label error-label">❌ 错误</span>
              <pre class="error-text">{{ step.error }}</pre>
            </div>
            <div class="step-model" v-if="step.model_name">
              <span class="label">🤖 模型</span>
              <el-tag size="small" type="info">{{ step.model_name }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  }
})

const successCount = computed(() => {
  return props.steps.filter(s => s.status === 'completed').length
})

const failedCount = computed(() => {
  return props.steps.filter(s => s.status === 'failed').length
})

const totalDuration = computed(() => {
  return props.steps.reduce((sum, s) => sum + (s.duration_ms || 0), 0)
})

const getDotClass = (status) => {
  const map = {
    'completed': 'dot-success',
    'running': 'dot-running',
    'failed': 'dot-failed',
    'pending': 'dot-pending'
  }
  return map[status] || 'dot-pending'
}

const getLineClass = (status) => {
  const map = {
    'completed': 'line-success',
    'running': 'line-running',
    'failed': 'line-failed',
    'pending': 'line-pending'
  }
  return map[status] || 'line-pending'
}

const getStatusTag = (status) => {
  const map = {
    'completed': 'success',
    'running': 'warning',
    'failed': 'danger',
    'pending': 'info'
  }
  return map[status] || 'info'
}

const formatContent = (content) => {
  if (!content) return '（无内容）'
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2)
  }
  return content
}
</script>

<style scoped>
.agent-timeline {
  margin: 16px 0;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}
.timeline-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}
.timeline-header h3 {
  margin: 0;
  color: #303133;
  font-size: 16px;
}
.timeline-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #606266;
}
.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot.success { background: #67c23a; }
.dot.failed { background: #f56c6c; }
.timeline-empty { padding: 20px 0; }
.timeline-container { position: relative; }
.timeline-item {
  display: flex;
  gap: 16px;
  padding: 4px 0;
}
.timeline-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 32px;
}
.timeline-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
  z-index: 1;
}
.dot-success { background: #67c23a; }
.dot-running { background: #e6a23c; animation: pulse 1.5s ease-in-out infinite; }
.dot-failed { background: #f56c6c; }
.dot-pending { background: #909399; }
.dot-number { font-size: 12px; }
.timeline-line {
  width: 2px;
  flex: 1;
  min-height: 20px;
  margin: 2px 0;
}
.line-success { background: #67c23a; }
.line-running { background: #e6a23c; }
.line-failed { background: #f56c6c; }
.line-pending { background: #dcdfe6; }
.timeline-content { flex: 1; padding-bottom: 12px; }
.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  flex-wrap: wrap;
  gap: 4px;
}
.step-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-name {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.step-duration {
  font-size: 12px;
  color: #909399;
}
.step-body { padding-left: 4px; }
.step-body .label {
  font-size: 12px;
  color: #909399;
  display: block;
  margin: 6px 0 2px 0;
}
.step-body pre {
  background: #f5f7fa;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 150px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 2px 0;
}
.error-text {
  color: #f56c6c;
  background: #fef0f0 !important;
}
.error-label { color: #f56c6c; }
.step-model { margin-top: 6px; }
.step-model .label { display: inline; margin-right: 8px; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>