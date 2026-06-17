<!-- src/components/AgentSteps.vue -->
<template>
  <div class="agent-steps">
    <h3>🤖 Agent 执行链路</h3>
    
    <el-timeline>
      <el-timeline-item
        v-for="(step, index) in steps"
        :key="index"
        :type="getStepType(step.status)"
        :hollow="true"
      >
        <div class="step-item">
          <div class="step-header">
            <span class="step-name">{{ step.agent_name || step.step_name || `步骤 ${index + 1}` }}</span>
            <el-tag :type="getStatusTag(step.status)" size="small">
              {{ step.status || 'pending' }}
            </el-tag>
            <span class="step-duration" v-if="step.duration_ms">
              ⏱️ {{ (step.duration_ms / 1000).toFixed(2) }}s
            </span>
          </div>
          
          <div class="step-detail">
            <el-collapse>
              <el-collapse-item title="📥 输入" name="input">
                <pre>{{ formatContent(step.input) }}</pre>
              </el-collapse-item>
              <el-collapse-item title="📤 输出" name="output">
                <pre>{{ formatContent(step.output) }}</pre>
              </el-collapse-item>
              <el-collapse-item v-if="step.error" title="❌ 错误" name="error">
                <pre class="error-text">{{ step.error }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </div>
      </el-timeline-item>
    </el-timeline>
  </div>
</template>

<script setup>
const props = defineProps({
  steps: {
    type: Array,
    default: () => []
  }
})

const getStepType = (status) => {
  const map = {
    'completed': 'success',
    'running': 'primary',
    'failed': 'danger',
    'pending': 'info'
  }
  return map[status] || 'info'
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
.agent-steps { margin: 20px 0; }
.step-item { width: 100%; }
.step-header { 
  display: flex; 
  align-items: center; 
  gap: 12px; 
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.step-name { 
  font-weight: 600; 
  font-size: 16px;
  color: #303133;
}
.step-duration { 
  color: #909399; 
  font-size: 13px;
  margin-left: auto;
}
.step-detail { margin-top: 8px; }
.step-detail pre {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-size: 13px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 4px 0;
}
.error-text { color: #f56c6c; }
</style>