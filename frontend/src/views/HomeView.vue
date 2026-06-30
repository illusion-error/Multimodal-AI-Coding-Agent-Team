<template>
  <div class="home-container">
    <!-- 大标题 -->
    <div class="hero">
      <h1 class="hero-title">多模态代码生成 Agent</h1>
      <p class="hero-sub">输入编程题目，AI 自动生成解法、执行测试、输出报告</p>
    </div>

    <!-- 控制栏 -->
    <div v-if="stage2Enabled" class="control-bar">
      <div class="control-group">
        <span class="control-label">Prompt 版本</span>
        <el-select v-model="selectedPromptVersion" placeholder="选择版本" size="small" style="width: 140px">
          <el-option v-for="v in promptVersions" :key="v.version" :label="v.version + (v.is_active ? ' ✓' : '')" :value="v.version" />
        </el-select>
        <el-button size="small" type="primary" @click="applyPromptVersion">应用</el-button>
      </div>
      <div class="control-group" v-if="currentModel">
        <span class="control-label">当前模型</span>
        <el-tag type="info" size="small">{{ currentModel }}</el-tag>
      </div>
    </div>

    <!-- 输入卡片 -->
    <div class="glass-card input-area">
      <div class="api-key-row">
        <el-input
          v-model="apiKey"
          type="password"
          show-password
          clearable
          autocomplete="off"
          placeholder="输入阿里云百炼 API Key（不填写时使用离线兜底）"
        >
          <template #prepend>百炼 API Key</template>
        </el-input>
        <el-tag :type="apiKey.trim() ? 'success' : 'info'">
          {{ apiKey.trim() ? '在线模式' : '离线模式' }}
        </el-tag>
      </div>

      <el-input
        v-model="problemText"
        type="textarea"
        :rows="4"
        placeholder="请输入编程题目描述，例如：给定一个整数数组 nums 和一个目标值 target，请你在该数组中找出和为目标值的那两个整数，并返回它们的数组下标。"
        class="problem-input"
      />

      <div class="upload-area">
        <el-upload ref="uploadRef" action="#" :auto-upload="false" :on-change="handleFileChange" :limit="1" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" class="upload-component">
          <el-button type="primary" plain>📷 上传题目截图</el-button>
        </el-upload>
        <span v-if="uploadFileName" class="file-name">{{ uploadFileName }}</span>
        <el-button v-if="uploadFileName" type="danger" size="small" plain @click="clearFile">移除</el-button>
      </div>

      <el-input
        v-model="supplementText"
        placeholder="补充说明（可选），例如：要求时间复杂度 O(n)"
        class="supplement-input"
      />

      <div class="btn-row">
        <el-button type="primary" size="large" :loading="loading" @click="submitTask" :disabled="!problemText.trim() && !uploadFile">
          {{ loading ? '生成中...' : '🚀 生成解法、执行代码并生成文档' }}
        </el-button>
        <el-button size="large" plain class="btn-outline" :disabled="loading" @click="loadRepairDemo">
          载入自动修复示例
        </el-button>
      </div>
    </div>

    <!-- 进度 -->
    <div v-if="loading" class="progress-section">
      <el-progress :percentage="progress" :status="progressStatus" />
      <p class="progress-hint">{{ progressHint }}</p>
    </div>

    <!-- 结果 -->
    <div v-if="result && !loading" class="result-section">
      <el-alert v-if="result.semantic_verification_status === 'manual_review'" title="代码已运行，但题型缺少系统权威测试，模型建议用例未参与自动修复，请人工确认题意与结果。" type="warning" :closable="false" show-icon class="semantic-alert" />
      <el-alert v-else-if="result.semantic_verification_status === 'verified'" title="语义契约与系统权威测试均已通过。" type="success" :closable="false" show-icon class="semantic-alert" />

      <div class="deployment-cards">
        <el-row :gutter="16">
          <el-col :span="stage2Enabled ? 4 : 6" v-for="item in deployItems" :key="item.label">
            <div class="deploy-card">
              <div class="deploy-label">{{ item.label }}</div>
              <div class="deploy-value">{{ item.value }} <span class="deploy-unit">{{ item.unit }}</span></div>
            </div>
          </el-col>
        </el-row>
      </div>

      <el-tabs v-model="activeTab" class="result-tabs">
        <el-tab-pane label="题意识别" name="problem">
          <div class="tab-content">
            <div class="markdown-body" v-html="renderedProblem" />
            <el-descriptions v-if="result.problem_contract && result.problem_contract.id" title="系统语义契约" :column="1" border class="contract-panel">
              <el-descriptions-item label="函数签名">{{ result.problem_contract.signature }}</el-descriptions-item>
              <el-descriptions-item label="输入">{{ result.problem_contract.input }}</el-descriptions-item>
              <el-descriptions-item label="输出">{{ result.problem_contract.output }}</el-descriptions-item>
              <el-descriptions-item label="不可变规则">
                <ul class="contract-rules"><li v-for="rule in result.problem_contract.rules || []" :key="rule">{{ rule }}</li></ul>
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-tab-pane>
        <el-tab-pane label="解题思路" name="solution">
          <div class="tab-content"><div class="markdown-body" v-html="renderedSolution" /></div>
        </el-tab-pane>
        <el-tab-pane label="Python 代码" name="code">
          <div class="tab-content">
            <div class="code-container">
              <div class="code-lines"><span v-for="(_, i) in codeLines" :key="i">{{ i + 1 }}</span></div>
              <pre class="code-pre"><code>{{ result.code || '—' }}</code></pre>
            </div>
            <el-button size="small" type="primary" @click="copyCode" style="margin-top:10px;">📋 复制代码</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="执行结果" name="execution">
          <div class="tab-content">
            <div v-if="result.execution_report">
              <p><strong>退出码：</strong>{{ result.execution_report.exit_code ?? '—' }}</p>
              <pre class="output-pre">{{ result.execution_report.stdout || '（无输出）' }}</pre>
              <div v-if="result.execution_report.stderr" style="color:#EF9A9A;">
                <strong>错误输出：</strong>
                <pre class="output-pre error-pre">{{ result.execution_report.stderr }}</pre>
              </div>
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="自动测试" name="tests">
          <div class="tab-content">
            <el-table :data="testCases" empty-text="暂无测试用例">
              <el-table-column prop="category" label="类型" width="120" />
              <el-table-column label="来源" width="130">
                <template #default="{ row }">
                  <el-tag :type="row.trusted ? 'success' : 'warning'" size="small">{{ row.trusted ? '系统权威' : '模型建议' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="input" label="输入" min-width="180" />
              <el-table-column prop="expected" label="期望" min-width="130" />
              <el-table-column prop="actual" label="实际" min-width="130" />
              <el-table-column label="结果" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.trusted ? (row.passed ? 'success' : 'danger') : 'info'">
                    {{ row.trusted ? (row.passed ? '通过' : '失败') : '待确认' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
              <el-table-column prop="error" label="错误" min-width="160" />
            </el-table>
          </div>
        </el-tab-pane>
        <el-tab-pane label="修复记录" name="repairs">
          <div class="tab-content">
            <el-empty v-if="repairLogs.length === 0" description="本次代码一次运行通过，未触发修复" />
            <el-timeline v-else>
              <el-timeline-item v-for="item in repairLogs" :key="item.log_id" :type="item.repair_success ? 'success' : 'danger'" :timestamp="`第 ${item.repair_round} 轮 · ${item.duration_ms || 0} ms`">
                <p>{{ item.error_msg || '已执行修复' }}</p>
                <el-tag :type="item.repair_success ? 'success' : 'danger'" size="small">{{ item.repair_success ? '修复成功' : '修复失败' }}</el-tag>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-tab-pane>
        <el-tab-pane label="Agent Timeline" name="timeline">
          <div class="tab-content"><AgentTimeline :steps="agentSteps" /></div>
        </el-tab-pane>
        <el-tab-pane v-if="stage2Enabled" label="Trace 详情" name="trace">
          <div class="tab-content"><TraceDetail :trace-id="result.trace_id" :trace-data="traceData" /></div>
        </el-tab-pane>
        <el-tab-pane label="项目文档" name="document">
          <div class="tab-content"><div class="markdown-body" v-html="renderedDocument" /></div>
        </el-tab-pane>
        <el-tab-pane label="下载" name="download">
          <div class="tab-content">
            <div class="download-buttons">
              <el-button type="success" plain @click="downloadReport('md')">📥 Markdown</el-button>
              <el-button type="primary" plain @click="downloadReport('json')">📥 JSON</el-button>
              <el-button type="warning" plain @click="downloadCode">📥 Python</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <div v-if="result.notes || result.attention" class="notes-area">
        <el-alert title="注意" :description="result.notes || result.attention" type="warning" show-icon :closable="false" />
      </div>

      <div class="action-buttons">
        <el-button type="warning" plain @click="handleRerun" :loading="rerunLoading">🔄 重新执行</el-button>
      </div>
    </div>

    <div v-if="!result && !loading && !taskError" class="empty-state">
      <span class="empty-icon">🧠</span>
      <p>提交题目后，结果将在这里显示</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { 
  createTextTask,
  getTaskReport,
  getTaskSteps,
  getTaskTests,
  getTaskRepairs,
  getTaskTrace,
  rerunTask,
  pollTaskStatus,
  handleApiError,
  uploadImageWithFallback,
  getPromptVersions,
  updatePromptVersion
} from '../api/task'
import AgentTimeline from '../components/AgentTimeline.vue'
import TraceDetail from '../components/TraceDetail.vue'

marked.setOptions({ breaks: true, gfm: true })

const problemText = ref('')
const supplementText = ref('')
const apiKey = ref('')
const uploadFile = ref(null)
const uploadFileName = ref('')
const uploadRef = ref(null)
const loading = ref(false)
const result = ref(null)
const taskError = ref('')
const taskId = ref(null)
const agentSteps = ref([])
const testCases = ref([])
const repairLogs = ref([])
const rerunLoading = ref(false)
const progress = ref(0)
const progressStatus = ref('')
const progressHint = ref('')
const activeTab = ref('problem')
const selectedPromptVersion = ref('')
const promptVersions = ref([])
const currentModel = ref('')
const traceData = ref({})
const stage2Enabled = import.meta.env.VITE_ENABLE_STAGE2 === 'true'
let progressTimer = null

const deployItems = computed(() => {
  const items = [
    { label: '总耗时', value: result.value?.total_ms || 0, unit: 'ms' },
    { label: 'API 调用', value: result.value?.api_call ? '是' : '否', unit: '' },
    { label: '兜底输出', value: result.value?.fallback_used ? '是' : '否', unit: '' },
    { label: '代码长度', value: result.value?.code_length || 0, unit: '字符' },
  ]
  if (stage2Enabled) {
    items.push({ label: '使用模型', value: result.value?.model_name || '—', unit: '' })
    items.push({ label: 'Prompt 版本', value: result.value?.prompt_version || '—', unit: '' })
  }
  return items
})

const renderedProblem = computed(() => result.value ? marked(result.value.problem || '—') : '')
const renderedSolution = computed(() => result.value ? marked(result.value.solution_markdown || '—') : '')
const renderedDocument = computed(() => result.value ? marked(result.value.project_document || '暂无项目文档。') : '')
const codeLines = computed(() => result.value?.code ? result.value.code.split('\n') : [])

const loadPromptVersions = async () => {
  if (!stage2Enabled) return
  try {
    const response = await getPromptVersions()
    if (response.data.code === 0) {
      promptVersions.value = response.data.data || []
      const active = promptVersions.value.find(v => v.is_active)
      if (active) selectedPromptVersion.value = active.version
    }
  } catch {
    promptVersions.value = [{ version: 'v1.0', is_active: true }]
    selectedPromptVersion.value = 'v1.0'
  }
}

const applyPromptVersion = async () => {
  if (!selectedPromptVersion.value) { ElMessage.warning('请选择版本'); return }
  try {
    await updatePromptVersion('all', selectedPromptVersion.value)
    ElMessage.success(`已切换到 Prompt 版本 ${selectedPromptVersion.value}`)
  } catch { ElMessage.error('切换版本失败') }
}

const handleFileChange = (file) => {
  const allowedTypes = ['image/png', 'image/jpeg', 'image/webp']
  if (!allowedTypes.includes(file.raw?.type)) { ElMessage.error('仅支持 PNG、JPEG、WebP 图片'); clearFile(); return }
  if (file.raw.size > 10 * 1024 * 1024) { ElMessage.error('图片大小不能超过 10MB'); clearFile(); return }
  uploadFile.value = file.raw
  uploadFileName.value = file.name
}

const clearFile = () => {
  uploadFile.value = null
  uploadFileName.value = ''
  uploadRef.value?.clearFiles()
}

const loadRepairDemo = () => {
  problemText.value = `请调试并修复下面的两数之和 Python 代码，返回 nums 中和为 target 的两个下标：

\`\`\`python
def solution(nums, target)
    return []
\`\`\``
  supplementText.value = ''
  clearFile()
}

const startProgress = () => {
  progress.value = 0
  progressStatus.value = ''
  const hints = ['正在识别题目...', '正在规划解题思路...', '正在生成代码...', '正在生成测试用例...', '正在执行和调试...', '正在生成报告...']
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = setInterval(() => {
    if (progress.value >= 95) { clearInterval(progressTimer); return }
    progress.value += Math.random() * 8 + 2
    if (progress.value > 95) progress.value = 95
    const hintIndex = Math.min(Math.floor(progress.value / 20), hints.length - 1)
    progressHint.value = hints[hintIndex] || '处理中...'
  }, 800)
}

const stopProgress = () => {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  progress.value = 100
  progressStatus.value = 'success'
  progressHint.value = '✅ 完成！'
}

const fetchAgentSteps = async (id) => {
  try {
    const response = await getTaskSteps(id)
    agentSteps.value = response.data.code === 0 ? response.data.data || [] : []
  } catch { agentSteps.value = [] }
}

const fetchTaskArtifacts = async (id) => {
  const [testsResponse, repairsResponse] = await Promise.all([getTaskTests(id), getTaskRepairs(id)])
  testCases.value = testsResponse.data.code === 0 ? testsResponse.data.data || [] : []
  repairLogs.value = repairsResponse.data.code === 0 ? repairsResponse.data.data || [] : []
}

const fetchTraceData = async (id) => {
  if (!stage2Enabled) return
  try {
    const response = await getTaskTrace(id)
    traceData.value = response.data.code === 0 ? response.data.data || {} : {}
  } catch { traceData.value = {} }
}

const submitTask = async () => {
  if (!problemText.value.trim() && !uploadFile.value) { ElMessage.warning('请输入题目描述或上传截图'); return }

  loading.value = true
  result.value = null
  taskError.value = ''
  agentSteps.value = []
  testCases.value = []
  repairLogs.value = []
  traceData.value = {}
  activeTab.value = 'problem'
  startProgress()

  try {
    let response
    if (uploadFile.value) {
      try {
        response = await uploadImageWithFallback(uploadFile.value, supplementText.value, apiKey.value)
      } catch (imgError) {
        if (imgError.isImageUpload404) {
          stopProgress()
          progressStatus.value = 'exception'
          ElMessage.warning('图片上传功能暂未实现，请使用文本输入')
          loading.value = false
          return
        }
        throw imgError
      }
    } else {
      response = await createTextTask(problemText.value, apiKey.value)
    }

    if (response.data.code === 0) {
      const data = response.data.data
      taskId.value = data.task_id
      const finalResult = await pollTaskStatus(taskId.value)
      finalResult.code_length = finalResult.code ? finalResult.code.length : 0
      finalResult.api_call = Boolean(finalResult.api_call)
      finalResult.fallback_used = Boolean(finalResult.fallback_used)
      finalResult.notes = finalResult.notes || '请确保输入符合题目要求，代码在 Python 3.10+ 环境中运行。'
      finalResult.model_name = finalResult.model_name || finalResult.metrics?.text_model || '—'
      finalResult.prompt_version = finalResult.prompt_version || selectedPromptVersion.value || '—'
      result.value = finalResult
      currentModel.value = finalResult.model_name

      const followUpRequests = [fetchAgentSteps(taskId.value), fetchTaskArtifacts(taskId.value)]
      if (stage2Enabled) followUpRequests.push(fetchTraceData(taskId.value))
      await Promise.all(followUpRequests)

      if (finalResult.status === 'failed') {
        taskError.value = finalResult.error || finalResult.notes || '代码未通过全部自动测试'
        stopProgress()
        progressStatus.value = 'exception'
        progressHint.value = '任务完成，但代码未通过全部测试'
        ElMessage.error(taskError.value)
        return
      }
      stopProgress()
      ElMessage.success('生成成功！')
    } else {
      stopProgress()
      progressStatus.value = 'exception'
      ElMessage.error(response.data.message || '生成失败')
    }
  } catch (error) {
    stopProgress()
    progressStatus.value = 'exception'
    if (!error.isImageUpload404) {
      taskError.value = handleApiError(error, '请求失败，请检查后端是否启动')
      ElMessage.error(taskError.value)
    }
  } finally {
    loading.value = false
    setTimeout(() => { progress.value = 0 }, 2000)
  }
}

const downloadReport = async (format = 'md') => {
  if (!taskId.value) { ElMessage.warning('没有可下载的报告'); return }
  try {
    const response = await getTaskReport(taskId.value)
    const blob = new Blob([response.data], { type: format === 'json' ? 'application/json' : 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `report_${taskId.value}.${format === 'json' ? 'json' : 'md'}`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('下载成功')
  } catch { ElMessage.error('下载失败') }
}

const downloadCode = () => {
  if (!result.value?.code) { ElMessage.warning('没有代码可下载'); return }
  const blob = new Blob([result.value.code], { type: 'text/plain' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `solution_${taskId.value}.py`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('代码下载成功')
}

const copyCode = () => {
  if (!result.value?.code) { ElMessage.warning('没有代码可复制'); return }
  navigator.clipboard.writeText(result.value.code).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
}

const handleRerun = async () => {
  if (!taskId.value) return
  rerunLoading.value = true
  taskError.value = ''
  try {
    const response = await rerunTask(taskId.value, apiKey.value)
    if (response.data.code === 0) {
      ElMessage.success('已重新执行')
      taskId.value = response.data.data.task_id
      const finalResult = await pollTaskStatus(taskId.value)
      finalResult.code_length = finalResult.code ? finalResult.code.length : 0
      result.value = finalResult
      currentModel.value = finalResult.model_name || finalResult.metrics?.text_model || '—'
      const followUpRequests = [fetchAgentSteps(taskId.value), fetchTaskArtifacts(taskId.value)]
      if (stage2Enabled) followUpRequests.push(fetchTraceData(taskId.value))
      await Promise.all(followUpRequests)
      if (finalResult.status === 'failed') {
        taskError.value = finalResult.error || finalResult.notes || '代码未通过全部自动测试'
        ElMessage.error(taskError.value)
      }
    }
  } catch (error) {
    ElMessage.error(handleApiError(error, '重新执行失败'))
  } finally {
    rerunLoading.value = false
  }
}

loadPromptVersions()
onUnmounted(() => { if (progressTimer) clearInterval(progressTimer) })
</script>

<style scoped>
.home-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
  min-height: 100vh;
  background-image: url('/微信图片_20260630155027_91_3.jpg') !important;
  background-size: cover !important;
  background-position: center !important;
  background-attachment: fixed !important;
  background-repeat: no-repeat !important;
  position: relative;
  border-radius: 0;
}

.home-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(10, 10, 26, 0.55);
  z-index: -1;
}

.hero { margin-bottom: 32px; position: relative; z-index: 1; }
.hero-title { font-size: 40px; font-weight: 700; color: #fff; letter-spacing: -0.5px; margin-bottom: 6px; }
.hero-sub { font-size: 16px; color: rgba(255,255,255,0.4); }

.control-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  position: relative;
  z-index: 1;
}
.control-group { display: flex; align-items: center; gap: 8px; }
.control-label { font-size: 13px; color: rgba(255,255,255,0.4); }

.glass-card {
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}

.input-area .problem-input :deep(.el-textarea__inner) {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
  color: #fff !important;
  font-size: 15px;
  line-height: 1.7;
}

.api-key-row {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.upload-area {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0;
  flex-wrap: wrap;
}
.upload-area .el-upload {
  display: inline-flex !important;
  align-items: center !important;
}
.upload-area .el-upload .el-button {
  visibility: visible !important;
  opacity: 1 !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  border: 1px solid rgba(79,110,247,0.4) !important;
  color: #4F6EF7 !important;
  background: rgba(79,110,247,0.08) !important;
}
.upload-area .el-upload .el-button:hover {
  background: rgba(79,110,247,0.15) !important;
  border-color: #4F6EF7 !important;
}
.file-name { color: #4F6EF7; font-weight: 500; }
.supplement-input { margin: 12px 0; }
.supplement-input :deep(.el-input__wrapper) {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.06) !important;
  color: #fff !important;
}
.btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
.btn-outline {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  color: rgba(255,255,255,0.5) !important;
}
.btn-outline:hover {
  background: rgba(255,255,255,0.08) !important;
  border-color: rgba(255,255,255,0.15) !important;
  color: #fff !important;
}

.progress-section {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}
.progress-hint { margin-top: 8px; color: rgba(255,255,255,0.4); font-size: 14px; }

.result-section {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 20px 24px;
  position: relative;
  z-index: 1;
}
.semantic-alert { margin-bottom: 16px; }

.deployment-cards { margin-bottom: 20px; }
.deploy-card {
  background: rgba(255,255,255,0.04);
  border-radius: 10px;
  padding: 14px 12px;
  text-align: center;
  border: 1px solid rgba(255,255,255,0.04);
}
.deploy-label { font-size: 12px; color: rgba(255,255,255,0.3); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.deploy-value { font-size: 18px; font-weight: 600; color: #fff; }
.deploy-unit { font-size: 12px; font-weight: 400; color: rgba(255,255,255,0.3); }

.result-tabs { margin-top: 4px; }
.tab-content { padding: 8px 0; color: rgba(255,255,255,0.6); }
.tab-content h4 { color: #fff; margin: 0 0 10px 0; }

.markdown-body { line-height: 1.8; color: rgba(255,255,255,0.6); }
.markdown-body :deep(h1), .markdown-body :deep(h2), .markdown-body :deep(h3) { color: #fff; }
.markdown-body :deep(code) { background: rgba(255,255,255,0.06); padding: 2px 8px; border-radius: 4px; color: #4F6EF7; }
.markdown-body :deep(pre) { background: rgba(0,0,0,0.3); padding: 16px; border-radius: 8px; overflow: auto; }
.markdown-body :deep(strong) { color: #fff; }

.code-container {
  display: flex;
  background: rgba(0,0,0,0.4);
  border-radius: 10px;
  overflow: auto;
  max-height: 400px;
}
.code-lines {
  background: rgba(0,0,0,0.2);
  color: rgba(255,255,255,0.2);
  padding: 14px 10px;
  text-align: right;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.7;
  min-width: 44px;
  user-select: none;
  border-right: 1px solid rgba(255,255,255,0.04);
}
.code-lines span { display: block; }
.code-pre {
  flex: 1;
  color: rgba(255,255,255,0.8);
  padding: 14px 18px;
  margin: 0;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.7;
  overflow: auto;
}

.output-pre {
  background: rgba(0,0,0,0.2);
  padding: 14px 18px;
  border-radius: 8px;
  overflow: auto;
  max-height: 300px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255,255,255,0.7);
}
.error-pre { color: #EF9A9A !important; background: rgba(239,154,154,0.08) !important; }

.download-buttons { display: flex; gap: 12px; flex-wrap: wrap; }
.download-buttons .el-button { background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.06) !important; color: rgba(255,255,255,0.5) !important; }
.download-buttons .el-button:hover { background: rgba(255,255,255,0.08) !important; color: #fff !important; }

.notes-area { margin-top: 16px; }
.action-buttons { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; justify-content: center; }
.action-buttons .el-button { background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.06) !important; color: rgba(255,255,255,0.4) !important; }
.action-buttons .el-button:hover { background: rgba(255,255,255,0.08) !important; color: #fff !important; }

.empty-state { text-align: center; padding: 60px 0; position: relative; z-index: 1; }
.empty-icon { font-size: 48px; opacity: 0.2; margin-bottom: 12px; }
.empty-state p { color: rgba(255,255,255,0.2); font-size: 15px; }

@media (max-width: 720px) {
  .hero-title { font-size: 28px; }
  .api-key-row { grid-template-columns: 1fr; }
}
</style>