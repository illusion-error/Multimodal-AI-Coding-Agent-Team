<template>
  <div class="history-container">
    <div class="hero">
      <h1 class="hero-title">📚 历史任务</h1>
      <p class="hero-sub">查看所有已提交的编程任务</p>
    </div>

    <div class="glass-card">
      <div class="filter-bar">
        <el-select v-model="filterStatus" placeholder="筛选状态" clearable size="small">
          <el-option label="全部" value="" />
          <el-option label="已完成" value="completed" />
          <el-option label="执行中" value="running" />
          <el-option label="失败" value="failed" />
          <el-option label="已取消" value="cancelled" />
        </el-select>
        <el-input v-model="searchKeyword" placeholder="搜索题目关键词" style="width: 200px" size="small" clearable />
        <el-button type="primary" size="small" @click="fetchHistory">刷新</el-button>
      </div>

      <el-table :data="filteredTaskList" v-loading="loading">
        <el-table-column prop="task_id" label="任务ID" width="150" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="problem" label="题目" min-width="200">
          <template #default="{ row }">
            {{ row.problem ? row.problem.substring(0, 50) + '...' : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column prop="total_ms" label="耗时(ms)" width="100" />
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="viewDetail(row.task_id)">查看详情</el-button>
            <el-button size="small" type="success" plain @click="downloadReport(row.task_id)">下载报告</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="任务详情" width="85%" :close-on-click-modal="false">
      <div v-if="detailData" class="detail-content">
        <div class="info-grid">
          <div class="info-item"><span class="label">任务ID</span><span class="value">{{ detailData.task_id }}</span></div>
          <div class="info-item"><span class="label">状态</span><span class="value">{{ detailData.status }}</span></div>
          <div class="info-item"><span class="label">总耗时</span><span class="value">{{ detailData.total_ms || 0 }}ms</span></div>
          <div class="info-item"><span class="label">模型</span><span class="value">{{ detailData.selected_model || '—' }}</span></div>
        </div>
        <h4>📋 题意识别</h4>
        <p>{{ detailData.problem || '—' }}</p>
        <h4>💡 解题思路</h4>
        <p>{{ detailData.solution_markdown || '—' }}</p>
        <h4>💻 代码</h4>
        <pre>{{ detailData.code || '—' }}</pre>
        <h4>⚙️ 执行结果</h4>
        <pre>{{ detailData.execution_report ? JSON.stringify(detailData.execution_report, null, 2) : '—' }}</pre>
        <h4>🤖 Agent 步骤</h4>
        <div v-if="detailSteps.length === 0" class="empty-steps"><el-empty description="暂无 Agent 步骤数据" :image-size="60" /></div>
        <AgentSteps v-else :steps="detailSteps" />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" plain @click="goToTaskDetail(currentTaskId)">查看完整详情</el-button>
        <el-button type="success" plain @click="downloadReport(currentTaskId)">下载报告</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTaskList, getTaskDetail, getTaskReport, getTaskSteps, handleApiError } from '../api/task'
import AgentSteps from '../components/AgentSteps.vue'

const router = useRouter()
const loading = ref(false)
const taskList = ref([])
const filterStatus = ref('')
const searchKeyword = ref('')
const dialogVisible = ref(false)
const detailData = ref(null)
const detailSteps = ref([])
const currentTaskId = ref('')

const filteredTaskList = computed(() => {
  let list = taskList.value
  if (filterStatus.value) list = list.filter(item => item.status === filterStatus.value)
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    list = list.filter(item => item.problem && item.problem.toLowerCase().includes(kw))
  }
  return list
})

const getStatusType = (status) => {
  const map = { completed: 'success', running: 'warning', failed: 'danger', pending: 'info', cancelled: 'info' }
  return map[status] || 'info'
}

const fetchHistory = async () => {
  loading.value = true
  try {
    const response = await getTaskList()
    if (response.data.code === 0) taskList.value = response.data.data || []
  } catch (error) {
    ElMessage.error(handleApiError(error, '加载历史失败'))
  } finally {
    loading.value = false
  }
}

const viewDetail = async (taskId) => {
  currentTaskId.value = taskId
  try {
    const detailRes = await getTaskDetail(taskId)
    if (detailRes.data.code === 0) {
      detailData.value = detailRes.data.data
    } else {
      ElMessage.error(detailRes.data.message || '加载详情失败')
      return
    }
    try {
      const stepsRes = await getTaskSteps(taskId)
      detailSteps.value = stepsRes.data?.code === 0 ? stepsRes.data.data || [] : []
    } catch { detailSteps.value = [] }
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(handleApiError(error, '加载详情失败'))
  }
}

const goToTaskDetail = (taskId) => {
  dialogVisible.value = false
  router.push(`/task/${taskId}`)
}

const downloadReport = async (taskId) => {
  try {
    const response = await getTaskReport(taskId)
    const blob = new Blob([response.data], { type: 'text/markdown' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `report_${taskId}.md`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('下载成功')
  } catch { ElMessage.error('下载失败') }
}

onMounted(fetchHistory)
</script>

<style scoped>
.history-container {
  max-width: 1000px;
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

.history-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(10, 10, 26, 0.55);
  z-index: 0;
}

.hero { margin-bottom: 28px; position: relative; z-index: 1; }
.hero-title { font-size: 32px; font-weight: 700; color: #fff; letter-spacing: -0.5px; margin-bottom: 4px; }
.hero-sub { font-size: 15px; color: rgba(255,255,255,0.4); }

.glass-card {
  background: rgba(15, 15, 35, 0.85) !important;
  backdrop-filter: blur(16px) !important;
  -webkit-backdrop-filter: blur(16px) !important;
  border: 1px solid rgba(255, 255, 255, 0.06) !important;
  border-radius: 16px;
  padding: 24px;
  position: relative;
  z-index: 1;
}

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: center;
  flex-wrap: wrap;
}

.filter-bar .el-input__wrapper {
  background: rgba(255,255,255,0.08) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
}

.filter-bar .el-input__wrapper:hover {
  border-color: rgba(255,255,255,0.25) !important;
}

.filter-bar .el-input__wrapper.is-focus {
  border-color: #4F6EF7 !important;
  box-shadow: 0 0 0 3px rgba(79,110,247,0.15) !important;
}

.filter-bar .el-input__inner {
  color: #fff !important;
  background: transparent !important;
}

.filter-bar .el-input__inner::placeholder {
  color: rgba(255,255,255,0.35) !important;
}

.filter-bar .el-select .el-input__wrapper {
  background: rgba(255,255,255,0.08) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
}

.filter-bar .el-button--primary {
  background: linear-gradient(135deg, #4F6EF7, #7C5CFC) !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  color: #fff !important;
}

.filter-bar .el-button--primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(79,110,247,0.3) !important;
}

/* ===== 深色空状态 ===== */
.el-empty {
  padding: 40px 0;
}
.el-empty .el-empty__image {
  opacity: 0.3;
}
.el-empty .el-empty__description p {
  color: rgba(255,255,255,0.3) !important;
  font-size: 14px !important;
}
.el-table__empty-block {
  background: transparent !important;
  min-height: 120px !important;
}
.el-table__empty-text {
  color: rgba(255,255,255,0.3) !important;
}

/* ===== 表格深色背景 ===== */
.el-table {
  background: transparent !important;
}
.el-table__header-wrapper {
  background: rgba(20, 20, 50, 0.95) !important;
}
.el-table__header {
  background: rgba(20, 20, 50, 0.95) !important;
}
.el-table thead {
  background: rgba(20, 20, 50, 0.95) !important;
}
.el-table th.el-table__cell {
  background: rgba(30, 30, 60, 0.95) !important;
  color: rgba(255, 255, 255, 0.85) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
}
.el-table__body-wrapper {
  background: rgba(20, 20, 50, 0.9) !important;
}
.el-table__body {
  background: rgba(20, 20, 50, 0.9) !important;
}
.el-table__empty-block {
  background: rgba(20, 20, 50, 0.9) !important;
}
.el-table tr {
  background: rgba(20, 20, 50, 0.9) !important;
}
.el-table tr.el-table__row {
  background: rgba(20, 20, 50, 0.9) !important;
}
.el-table tr.el-table__row td.el-table__cell {
  background: rgba(20, 20, 50, 0.9) !important;
  color: rgba(255, 255, 255, 0.85) !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04) !important;
}
.el-table tr.el-table__row:hover td.el-table__cell {
  background: rgba(79, 110, 247, 0.2) !important;
}
.el-table .cell {
  color: rgba(255, 255, 255, 0.85) !important;
}
.el-table .cell .el-button {
  background: rgba(255, 255, 255, 0.06) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  color: rgba(255, 255, 255, 0.6) !important;
}
.el-table .cell .el-button:hover {
  background: rgba(79, 110, 247, 0.2) !important;
  color: #fff !important;
}

.detail-content { padding: 10px 0; color: rgba(255,255,255,0.6); }
.detail-content h4 { margin: 16px 0 8px 0; color: #fff; font-size: 15px; }
.detail-content pre { background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; overflow: auto; max-height: 300px; color: rgba(255,255,255,0.7); }
.empty-steps { padding: 10px 0; }

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.info-item { display: flex; flex-direction: column; }
.info-item .label { font-size: 12px; color: rgba(255,255,255,0.3); }
.info-item .value { font-size: 14px; font-weight: 500; color: #fff; }
</style>