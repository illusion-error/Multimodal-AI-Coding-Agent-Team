<!-- src/views/HistoryView.vue -->
<template>
  <div class="history-container">
    <h1>📚 历史任务</h1>
    
    <div class="filter-bar">
      <el-select v-model="filterStatus" placeholder="筛选状态" clearable>
        <el-option label="全部" value="" />
        <el-option label="已完成" value="completed" />
        <el-option label="执行中" value="running" />
        <el-option label="失败" value="failed" />
        <el-option label="已取消" value="cancelled" />
      </el-select>
      <el-input 
        v-model="searchKeyword" 
        placeholder="搜索题目关键词" 
        style="width: 200px"
        clearable
      />
      <el-button type="primary" @click="fetchHistory">刷新</el-button>
    </div>

    <el-table :data="filteredTaskList" style="width: 100%" v-loading="loading">
      <el-table-column prop="task_id" label="任务ID" width="150" />
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)">
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="problem" label="题目" min-width="200">
        <template #default="{ row }">
          {{ row.problem ? row.problem.substring(0, 50) + '...' : '—' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" />
      <el-table-column prop="total_ms" label="耗时(ms)" width="100" />
      <el-table-column label="操作" width="280">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="viewDetail(row.task_id)">
            📋 查看详情
          </el-button>
          <el-button size="small" type="success" @click="downloadReport(row.task_id)">
            📥 下载报告
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 详情弹窗 -->
    <el-dialog 
      v-model="dialogVisible" 
      title="任务详情" 
      width="85%"
      :close-on-click-modal="false"
    >
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
        <div v-if="detailSteps.length === 0" class="empty-steps">
          <el-empty description="暂无 Agent 步骤数据" :image-size="60" />
        </div>
        <AgentSteps v-else :steps="detailSteps" />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="goToTaskDetail(currentTaskId)">
          📋 查看完整详情
        </el-button>
        <el-button type="success" @click="downloadReport(currentTaskId)">
          📥 下载报告
        </el-button>
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
  if (filterStatus.value) {
    list = list.filter(item => item.status === filterStatus.value)
  }
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(item => 
      item.problem && item.problem.toLowerCase().includes(keyword)
    )
  }
  return list
})

const getStatusType = (status) => {
  const map = {
    'completed': 'success',
    'running': 'warning',
    'failed': 'danger',
    'pending': 'info',
    'cancelled': 'info'
  }
  return map[status] || 'info'
}

const fetchHistory = async () => {
  loading.value = true
  try {
    const response = await getTaskList()
    if (response.data.code === 0) {
      taskList.value = response.data.data || []
    }
  } catch (error) {
    console.error('加载历史失败:', error)
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
      if (stepsRes.data && stepsRes.data.code === 0) {
        detailSteps.value = stepsRes.data.data || []
      } else {
        detailSteps.value = []
      }
    } catch (stepsError) {
      detailSteps.value = []
      console.log('Agent步骤接口暂未实现或获取失败')
    }
    
    dialogVisible.value = true
  } catch (error) {
    console.error('加载详情失败:', error)
    ElMessage.error(handleApiError(error, '加载详情失败'))
  }
}

const goToTaskDetail = (taskId) => {
  dialogVisible.value = false
  router.push(`/task/${taskId}`)
}

const downloadReport = async (taskId) => {
  if (!taskId) {
    ElMessage.warning('没有可下载的报告')
    return
  }
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
    console.error('下载失败:', error)
    ElMessage.error(handleApiError(error, '下载失败'))
  }
}

onMounted(fetchHistory)
</script>

<style scoped>
.history-container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.filter-bar { 
  display: flex; 
  gap: 12px; 
  margin-bottom: 20px;
  align-items: center;
  flex-wrap: wrap;
}
.detail-content { padding: 10px 0; }
.detail-content h4 { margin: 16px 0 8px 0; color: #303133; }
.detail-content pre {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  overflow: auto;
  max-height: 300px;
  font-size: 13px;
}
.empty-steps { padding: 10px 0; }
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.info-item {
  display: flex;
  flex-direction: column;
}
.info-item .label { font-size: 12px; color: #909399; }
.info-item .value { font-size: 14px; font-weight: 500; color: #303133; }
</style>