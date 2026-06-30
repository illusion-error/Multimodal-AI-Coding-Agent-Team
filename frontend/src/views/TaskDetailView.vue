<!-- src/views/TaskDetailView.vue -->
<template>
  <div class="task-detail-container">
    <div class="detail-header">
      <el-button type="primary" @click="goBack">← 返回</el-button>
      <h1>📋 任务详情</h1>
      <el-tag v-if="task" :type="task.status === 'completed' ? 'success' : 'danger'" size="large">
        {{ task.status }}
      </el-tag>
    </div>

    <el-card v-loading="loading" class="detail-card">
      <div v-if="task" class="detail-content">
        <!-- 基本信息 -->
        <div class="info-grid">
          <div class="info-item">
            <span class="label">任务ID</span>
            <span class="value">{{ task.task_id }}</span>
          </div>
          <div class="info-item">
            <span class="label">Trace ID</span>
            <span class="value">{{ task.trace_id || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="label">创建时间</span>
            <span class="value">{{ task.created_at || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="label">总耗时</span>
            <span class="value">{{ task.total_ms || 0 }}ms</span>
          </div>
        </div>

        <!-- 题意识别 -->
        <el-divider />
        <h3>📋 题意识别</h3>
        <div class="markdown-body" v-html="renderedProblem"></div>

        <!-- 解题思路 -->
        <el-divider />
        <h3>💡 解题思路</h3>
        <div class="markdown-body" v-html="renderedSolution"></div>

        <!-- 代码 -->
        <el-divider />
        <h3>💻 Python 代码</h3>
        <div class="code-container">
          <div class="code-lines">
            <span v-for="(line, idx) in codeLines" :key="idx">{{ idx + 1 }}</span>
          </div>
          <pre class="code-pre"><code>{{ task.code || '—' }}</code></pre>
        </div>
        <el-button size="small" type="primary" @click="copyCode" style="margin-top: 10px">
          📋 复制代码
        </el-button>

        <!-- 执行结果 -->
        <el-divider />
        <h3>⚙️ 执行结果</h3>
        <div v-if="task.execution_report">
          <p><strong>退出码：</strong>{{ task.execution_report.exit_code ?? '—' }}</p>
          <p><strong>标准输出：</strong></p>
          <pre class="output-pre">{{ task.execution_report.stdout || '（无输出）' }}</pre>
          <div v-if="task.execution_report.stderr" style="color: red;">
            <strong>错误输出：</strong>
            <pre class="output-pre error-pre">{{ task.execution_report.stderr }}</pre>
          </div>
        </div>

        <!-- 测试用例 -->
        <el-divider />
        <h3>🧪 测试用例</h3>
        <el-table :data="testCases" size="small" v-if="testCases.length > 0">
          <el-table-column prop="input" label="输入" min-width="120" />
          <el-table-column prop="expected" label="期望输出" min-width="120" />
          <el-table-column prop="actual" label="实际输出" min-width="120" />
          <el-table-column prop="passed" label="通过" width="80">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'danger'" size="small">
                {{ row.passed ? '✅' : '❌' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无测试用例" :image-size="60" />

        <!-- 模型路由信息 -->
        <el-divider />
        <h3>🤖 模型路由</h3>
        <div class="info-grid">
          <div class="info-item">
            <span class="label">使用模型</span>
            <span class="value">{{ task.selected_model || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="label">路由原因</span>
            <span class="value">{{ task.route_reason || '—' }}</span>
          </div>
          <div class="info-item">
            <span class="label">Token 使用</span>
            <span class="value">{{ tokenUsage || 'unknown' }}</span>
          </div>
          <div class="info-item">
            <span class="label">估算成本</span>
            <span class="value">{{ task.estimated_cost !== undefined ? '$' + task.estimated_cost : 'unknown' }}</span>
          </div>
        </div>

        <!-- Agent Timeline -->
        <el-divider />
        <AgentTimeline :steps="agentSteps" />

        <!-- Trace 详情 -->
        <el-divider />
        <TraceDetail :trace-id="task.trace_id" :trace-data="traceData" />

        <!-- 操作按钮 -->
        <div class="action-buttons">
          <el-button type="success" @click="downloadReport">📥 下载报告</el-button>
          <el-button type="warning" @click="handleRerun" :loading="rerunLoading">🔄 重新执行</el-button>
        </div>
      </div>

      <el-empty v-else-if="!loading" description="任务不存在" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { getTaskDetail, getTaskSteps, getTaskReport, getTaskTrace, rerunTask, handleApiError } from '../api/task'
import AgentTimeline from '../components/AgentTimeline.vue'
import TraceDetail from '../components/TraceDetail.vue'

const route = useRoute()
const router = useRouter()
const taskId = route.params.id

const loading = ref(false)
const task = ref(null)
const agentSteps = ref([])
const traceData = ref({})
const rerunLoading = ref(false)

const testCases = computed(() => {
  return task.value?.test_cases || []
})

const codeLines = computed(() => {
  if (!task.value?.code) return []
  return task.value.code.split('\n').map((_, i) => i + 1)
})

const renderedProblem = computed(() => {
  if (!task.value?.problem) return ''
  return marked(task.value.problem)
})

const renderedSolution = computed(() => {
  if (!task.value?.solution_markdown) return ''
  return marked(task.value.solution_markdown)
})

const tokenUsage = computed(() => {
  const tokens = task.value?.token_usage
  if (!tokens) return 'unknown'
  if (typeof tokens === 'object') {
    return tokens.total_tokens || 'unknown'
  }
  return tokens || 'unknown'
})

const goBack = () => {
  router.push('/history')
}

const copyCode = () => {
  if (!task.value?.code) {
    ElMessage.warning('没有代码可复制')
    return
  }
  navigator.clipboard.writeText(task.value.code).then(() => {
    ElMessage.success('代码已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const downloadReport = async () => {
  try {
    const response = await getTaskReport(taskId)
    const blob = new Blob([response.data], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `report_${taskId}.md`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('下载成功')
  } catch (error) {
    ElMessage.error(handleApiError(error, '下载失败'))
  }
}

const handleRerun = async () => {
  rerunLoading.value = true
  try {
    const response = await rerunTask(taskId)
    if (response.data.code === 0) {
      const newTaskId = response.data.data.task_id
      ElMessage.success(`已重新执行，新任务ID: ${newTaskId}`)
      // 跳转到新任务详情
      router.push(`/task/${newTaskId}`)
    }
  } catch (error) {
    ElMessage.error(handleApiError(error, '重新执行失败'))
  } finally {
    rerunLoading.value = false
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const [detailRes, stepsRes, traceRes] = await Promise.all([
      getTaskDetail(taskId),
      getTaskSteps(taskId),
      getTaskTrace(taskId)
    ])

    if (detailRes.data.code === 0) {
      task.value = detailRes.data.data
    }

    if (stepsRes.data.code === 0) {
      agentSteps.value = stepsRes.data.data || []
    }

    if (traceRes.data.code === 0) {
      traceData.value = traceRes.data.data || {}
    }
  } catch (error) {
    console.error('加载任务详情失败:', error)
    ElMessage.error(handleApiError(error, '加载任务详情失败'))
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.task-detail-container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.detail-header h1 { margin: 0; }
.detail-card { margin-top: 10px; }
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.info-item {
  display: flex;
  flex-direction: column;
}
.info-item .label { font-size: 12px; color: #909399; }
.info-item .value { font-size: 14px; font-weight: 500; color: #303133; }
.markdown-body { line-height: 1.8; color: #303133; }
.markdown-body :deep(code) { background: #f5f7fa; padding: 2px 6px; border-radius: 3px; }
.markdown-body :deep(pre) { background: #f5f7fa; padding: 12px; border-radius: 6px; overflow: auto; }
.code-container {
  display: flex;
  background: #1e1e2e;
  border-radius: 6px;
  overflow: auto;
  max-height: 400px;
}
.code-lines {
  background: #1e1e2e;
  color: #6c7086;
  padding: 12px 8px;
  text-align: right;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  min-width: 40px;
  user-select: none;
  border-right: 1px solid #313244;
}
.code-lines span { display: block; }
.code-pre {
  flex: 1;
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 12px 16px;
  margin: 0;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow: auto;
}
.code-pre code { font-family: 'Courier New', monospace; }
.output-pre {
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 16px;
  border-radius: 6px;
  overflow: auto;
  max-height: 300px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
}
.error-pre { background: #1e1e2e; color: #f38ba8; }
.action-buttons { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; }
</style>