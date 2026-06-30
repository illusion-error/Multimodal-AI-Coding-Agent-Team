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
  background: rgba(255, 255, 255, 0.04);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
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
  color: #ffffff;
  font-size: 16px;
  font-weight: 600;
}
.timeline-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
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
.dot.success { background: #4CAF50; }
.dot.failed { background: #EF5350; }
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
.dot-success { background: #4CAF50; }
.dot-running { background: #FF9800; animation: pulse 1.5s ease-in-out infinite; }
.dot-failed { background: #EF5350; }
.dot-pending { background: #6B7280; }
.dot-number { font-size: 12px; }
.timeline-line {
  width: 2px;
  flex: 1;
  min-height: 20px;
  margin: 2px 0;
}
.line-success { background: #4CAF50; }
.line-running { background: #FF9800; }
.line-failed { background: #EF5350; }
.line-pending { background: #6B7280; }
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
  color: #ffffff;
}
.step-duration {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
}
.step-body { padding-left: 4px; }
.step-body .label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
  display: block;
  margin: 6px 0 2px 0;
}
.step-body pre {
  background: rgba(0, 0, 0, 0.4) !important;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 150px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 2px 0;
  color: rgba(255, 255, 255, 0.85) !important;
}
.error-text {
  color: #EF9A9A !important;
  background: rgba(239, 154, 154, 0.08) !important;
}
.error-label { color: #EF9A9A !important; }
.step-model { margin-top: 6px; }
.step-model .label { display: inline; margin-right: 8px; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>