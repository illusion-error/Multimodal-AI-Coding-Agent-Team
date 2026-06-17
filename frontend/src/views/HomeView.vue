<!-- src/views/HomeView.vue -->
<template>
  <div class="home-container">
    <h1>🧠 多模态代码生成 Agent</h1>

    <!-- 输入区 -->
    <el-card class="input-card">
      <el-input
        v-model="problemText"
        type="textarea"
        :rows="4"
        placeholder="请输入编程题目描述，例如：给定一个整数数组 nums 和一个目标值 target，请你在该数组中找出和为目标值的那两个整数，并返回它们的数组下标。"
      />
      
      <div class="upload-area">
        <el-upload
          ref="uploadRef"
          action="#"
          :auto-upload="false"
          :on-change="handleFileChange"
          :limit="1"
          accept="image/*"
        >
          <el-button type="primary" plain>📷 上传题目截图</el-button>
        </el-upload>
        <span v-if="uploadFileName" class="file-name">{{ uploadFileName }}</span>
        <el-button v-if="uploadFileName" type="danger" size="small" @click="clearFile">
          移除
        </el-button>
      </div>

      <el-input
        v-model="supplementText"
        placeholder="补充说明（可选），例如：要求时间复杂度 O(n)"
        class="supplement-input"
      />

      <el-button
        type="primary"
        size="large"
        :loading="loading"
        @click="submitTask"
        :disabled="!problemText.trim() && !uploadFile"
      >
        {{ loading ? '生成中...' : '🚀 生成解法、执行代码并生成文档' }}
      </el-button>
    </el-card>

    <!-- 任务进度 -->
    <el-card v-if="taskId && loading" class="progress-card">
      <h3>⏳ 任务执行中</h3>
      <el-progress :percentage="progress" :status="progressStatus" />
      <p class="progress-hint">{{ progressHint }}</p>
    </el-card>

    <!-- 结果区 -->
    <el-card v-if="result && !loading" class="result-card">
      <!-- 部署信息卡片 -->
      <div class="deployment-cards">
        <el-row :gutter="16">
          <el-col :span="6">
            <div class="deploy-card">
              <div class="deploy-label">总耗时</div>
              <div class="deploy-value">{{ result.total_ms || 0 }} <span class="deploy-unit">毫秒</span></div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="deploy-card">
              <div class="deploy-label">API 调用</div>
              <div class="deploy-value">
                <el-tag :type="result.api_call ? 'success' : 'info'" size="small">
                  {{ result.api_call ? '是' : '否' }}
                </el-tag>
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="deploy-card">
              <div class="deploy-label">兜底输出</div>
              <div class="deploy-value">
                <el-tag :type="result.fallback_used ? 'warning' : 'success'" size="small">
                  {{ result.fallback_used ? '是' : '否' }}
                </el-tag>
              </div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="deploy-card">
              <div class="deploy-label">代码长度</div>
              <div class="deploy-value">{{ result.code_length || 0 }} <span class="deploy-unit">字符</span></div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- Tab 切换 -->
      <el-tabs v-model="activeTab" class="result-tabs">
        <el-tab-pane label="题意识别" name="problem">
          <div class="tab-content">
            <h4>题意理解</h4>
            <div class="markdown-body" v-html="renderedProblem"></div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="解题说明" name="solution">
          <div class="tab-content">
            <h4>解题思路</h4>
            <div class="markdown-body" v-html="renderedSolution"></div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Python 代码" name="code">
          <div class="tab-content">
            <h4>生成的代码</h4>
            <div class="code-container">
              <div class="code-lines">
                <span v-for="(line, idx) in codeLines" :key="idx">{{ idx + 1 }}</span>
              </div>
              <pre class="code-pre"><code>{{ result.code || '—' }}</code></pre>
            </div>
            <el-button size="small" type="primary" @click="copyCode" style="margin-top: 10px">
              📋 复制代码
            </el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="执行结果" name="execution">
          <div class="tab-content">
            <h4>运行输出</h4>
            <div v-if="result.execution_report">
              <p><strong>退出码：</strong>{{ result.execution_report.exit_code ?? '—' }}</p>
              <p><strong>标准输出：</strong></p>
              <pre class="output-pre">{{ result.execution_report.stdout || '（无输出）' }}</pre>
              <div v-if="result.execution_report.stderr" style="color: red;">
                <strong>错误输出：</strong>
                <pre class="output-pre error-pre">{{ result.execution_report.stderr }}</pre>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="项目文档" name="document">
          <div class="tab-content">
            <h4>完整报告</h4>
            <div class="document-content">
              <div class="markdown-body" v-html="renderedDocument"></div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="下载" name="download">
          <div class="tab-content">
            <h4>下载选项</h4>
            <div class="download-buttons">
              <el-button type="success" @click="downloadReport('md')" size="large">
                📥 下载 Markdown 报告
              </el-button>
              <el-button type="primary" @click="downloadReport('json')" size="large">
                📥 下载 JSON 结果
              </el-button>
              <el-button type="warning" @click="downloadCode" size="large">
                📥 下载 Python 代码
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- 注意区域 -->
      <div v-if="result.notes || result.attention" class="notes-area">
        <el-alert
          title="注意"
          :description="result.notes || result.attention"
          type="warning"
          show-icon
          :closable="false"
        />
      </div>

      <!-- Agent 步骤（折叠） -->
      <el-collapse class="agent-collapse">
        <el-collapse-item title="🤖 查看 Agent 执行链路" name="agent">
          <AgentSteps :steps="agentSteps" />
        </el-collapse-item>
      </el-collapse>

      <!-- 底部操作按钮 -->
      <div class="action-buttons">
        <el-button type="warning" @click="handleRerun" :loading="rerunLoading">
          🔄 重新执行
        </el-button>
      </div>
    </el-card>

    <el-empty v-if="!result && !loading" description="提交题目后，结果将在这里显示" />
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { 
  createTextTask, 
  createImageTask, 
  getTaskReport,
  getTaskSteps,
  rerunTask,
  pollTaskStatus 
} from '../api/task'
import AgentSteps from '../components/AgentSteps.vue'

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true
})

const problemText = ref('')
const supplementText = ref('')
const uploadFile = ref(null)
const uploadFileName = ref('')
const loading = ref(false)
const result = ref(null)
const taskId = ref(null)
const agentSteps = ref([])
const rerunLoading = ref(false)
const progress = ref(0)
const progressStatus = ref('')
const progressHint = ref('')
const activeTab = ref('problem')
let progressTimer = null

// 渲染 Markdown
const renderedProblem = computed(() => {
  if (!result.value) return ''
  return marked(result.value.problem || '—')
})

const renderedSolution = computed(() => {
  if (!result.value) return ''
  return marked(result.value.solution_markdown || '—')
})

const renderedDocument = computed(() => {
  if (!result.value) return ''
  return marked(JSON.stringify(result.value, null, 2))
})

// 代码行号
const codeLines = computed(() => {
  if (!result.value || !result.value.code) return []
  const lines = result.value.code.split('\n')
  return lines.map((_, i) => i + 1)
})

const handleFileChange = (file) => {
  uploadFile.value = file.raw
  uploadFileName.value = file.name
}

const clearFile = () => {
  uploadFile.value = null
  uploadFileName.value = ''
}

const startProgress = () => {
  progress.value = 0
  progressStatus.value = ''
  const hints = ['正在识别题目...', '正在规划解题思路...', '正在生成代码...', '正在生成测试用例...', '正在执行和调试...', '正在生成报告...']
  
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = setInterval(() => {
    if (progress.value >= 95) {
      clearInterval(progressTimer)
      return
    }
    progress.value += Math.random() * 8 + 2
    if (progress.value > 95) progress.value = 95
    const hintIndex = Math.min(Math.floor(progress.value / 20), hints.length - 1)
    progressHint.value = hints[hintIndex] || '处理中...'
  }, 800)
}

const stopProgress = () => {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
  progress.value = 100
  progressStatus.value = 'success'
  progressHint.value = '✅ 完成！'
}

const submitTask = async () => {
  if (!problemText.value.trim() && !uploadFile.value) {
    ElMessage.warning('请输入题目描述或上传截图')
    return
  }

  loading.value = true
  result.value = null
  agentSteps.value = []
  activeTab.value = 'problem'
  startProgress()

  try {
    let response
    if (uploadFile.value) {
      response = await createImageTask(uploadFile.value, supplementText.value)
    } else {
      response = await createTextTask(problemText.value)
    }

    if (response.data.code === 0) {
      const data = response.data.data
      taskId.value = data.task_id
      
      const finalResult = await pollTaskStatus(taskId.value)
      
      finalResult.code_length = finalResult.code ? finalResult.code.length : 0
      finalResult.api_call = true
      finalResult.fallback_used = finalResult.fallback_used || false
      // 添加注意信息（如果后端返回了）
      finalResult.notes = finalResult.notes || '请确保输入符合题目要求，代码在 Python 3.10+ 环境中运行。'
      
      result.value = finalResult
      
      const stepsResponse = await getTaskSteps(taskId.value)
      if (stepsResponse.data.code === 0) {
        agentSteps.value = stepsResponse.data.data || []
      }
      
      stopProgress()
      ElMessage.success('生成成功！')
    } else {
      stopProgress()
      progressStatus.value = 'exception'
      ElMessage.error(response.data.message || '生成失败')
    }
  } catch (error) {
    console.error('提交失败:', error)
    stopProgress()
    progressStatus.value = 'exception'
    ElMessage.error(error.message || '请求失败，请检查后端是否启动')
  } finally {
    loading.value = false
    setTimeout(() => {
      progress.value = 0
    }, 2000)
  }
}

const downloadReport = async (format = 'md') => {
  if (!taskId.value) {
    ElMessage.warning('没有可下载的报告')
    return
  }
  try {
    const response = await getTaskReport(taskId.value)
    let blob, filename
    if (format === 'json') {
      blob = new Blob([JSON.stringify(result.value, null, 2)], { type: 'application/json' })
      filename = `report_${taskId.value}.json`
    } else {
      blob = new Blob([response.data], { type: 'text/markdown' })
      filename = `report_${taskId.value}.md`
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('下载成功')
  } catch {
    ElMessage.error('下载失败')
  }
}

const downloadCode = () => {
  if (!result.value || !result.value.code) {
    ElMessage.warning('没有代码可下载')
    return
  }
  const blob = new Blob([result.value.code], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `solution_${taskId.value}.py`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('代码下载成功')
}

const copyCode = () => {
  if (!result.value || !result.value.code) {
    ElMessage.warning('没有代码可复制')
    return
  }
  navigator.clipboard.writeText(result.value.code).then(() => {
    ElMessage.success('代码已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const handleRerun = async () => {
  if (!taskId.value) return
  rerunLoading.value = true
  try {
    const response = await rerunTask(taskId.value)
    if (response.data.code === 0) {
      ElMessage.success('已重新执行')
      const finalResult = await pollTaskStatus(taskId.value)
      finalResult.code_length = finalResult.code ? finalResult.code.length : 0
      result.value = finalResult
      const stepsResponse = await getTaskSteps(taskId.value)
      if (stepsResponse.data.code === 0) {
        agentSteps.value = stepsResponse.data.data || []
      }
    }
  } catch (error) {
    ElMessage.error('重新执行失败')
  } finally {
    rerunLoading.value = false
  }
}

onUnmounted(() => {
  if (progressTimer) {
    clearInterval(progressTimer)
  }
})
</script>

<style scoped>
.home-container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.input-card { margin-bottom: 20px; }
.upload-area { display: flex; align-items: center; gap: 10px; margin: 12px 0; flex-wrap: wrap; }
.file-name { color: #409EFF; }
.supplement-input { margin: 12px 0; }
.progress-card { margin-bottom: 20px; }
.progress-hint { margin-top: 10px; color: #606266; font-size: 14px; }

.result-card { margin-top: 20px; }

/* 部署卡片 */
.deployment-cards { margin-bottom: 20px; }
.deploy-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px 20px;
  text-align: center;
  border: 1px solid #ebeef5;
}
.deploy-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 6px;
}
.deploy-value {
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}
.deploy-unit {
  font-size: 13px;
  font-weight: 400;
  color: #909399;
}

/* Tab 样式 */
.result-tabs { margin-top: 10px; }
.tab-content { padding: 10px 0; }
.tab-content h4 { margin: 0 0 10px 0; color: #303133; }

/* Markdown 渲染 */
.markdown-body {
  line-height: 1.8;
  color: #303133;
}
.markdown-body :deep(h1) { font-size: 22px; margin: 16px 0 8px 0; }
.markdown-body :deep(h2) { font-size: 18px; margin: 14px 0 6px 0; }
.markdown-body :deep(h3) { font-size: 16px; margin: 12px 0 4px 0; }
.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 24px; }
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
}
.markdown-body :deep(pre) {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
  overflow: auto;
  font-family: 'Courier New', monospace;
  font-size: 13px;
}
.markdown-body :deep(strong) {
  font-weight: 700;
  color: #303133;
}

/* 代码容器（带行号） */
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
.code-lines span {
  display: block;
}
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
.code-pre code {
  font-family: 'Courier New', monospace;
}

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
.error-pre {
  background: #1e1e2e;
  color: #f38ba8;
}
.document-content pre {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
  font-size: 13px;
}
.download-buttons {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.agent-collapse { margin-top: 20px; }
.action-buttons {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  flex-wrap: wrap;
  justify-content: center;
}

/* 注意区域 */
.notes-area {
  margin-top: 16px;
}
</style>