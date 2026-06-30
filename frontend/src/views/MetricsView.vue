<template>
  <div class="metrics-container">
    <div class="hero">
      <h1 class="hero-title">📊 指标看板</h1>
      <p class="hero-sub">系统运行状态与性能统计</p>
    </div>

    <!-- 指标卡片 -->
    <div class="stats-grid">
      <div class="stat-card" v-for="item in overviewMetrics" :key="item.label">
        <span class="stat-label">{{ item.label }}</span>
        <span class="stat-value">{{ item.value }}</span>
      </div>
    </div>

    <!-- Benchmark -->
    <div class="benchmark-section">
      <div class="benchmark-header">
        <h3>📊 Benchmark 评测</h3>
        <el-button type="primary" size="small" @click="startBenchmark" :loading="benchmarkStarting">
          {{ benchmarkRunning ? '评测中...' : '🚀 启动评测' }}
        </el-button>
      </div>

      <div v-if="benchmarkRunning" class="benchmark-progress">
        <el-progress :percentage="benchmarkProgress" />
        <p class="benchmark-status">{{ benchmarkStatusText }}</p>
      </div>

      <div v-if="benchmarkResult" class="benchmark-result">
        <el-table :data="benchmarkResult.details || []" size="small">
          <el-table-column prop="title" label="题目" min-width="120" />
          <el-table-column prop="difficulty" label="难度" width="80">
            <template #default="{ row }">
              <el-tag :type="row.difficulty === '简单' ? 'success' : row.difficulty === '中等' ? 'warning' : 'danger'" size="small">
                {{ row.difficulty || '—' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="passed" label="通过" width="70">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'danger'" size="small">
                {{ row.passed ? '✅' : '❌' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="duration" label="耗时(ms)" width="80" />
          <el-table-column prop="error" label="错误" min-width="100">
            <template #default="{ row }">
              <span style="color: #EF9A9A; font-size: 12px;">{{ row.error || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="benchmark-summary">
          <span>通过率: {{ benchmarkResult.pass_rate || 0 }}%</span>
          <span>总题数: {{ benchmarkResult.total || 0 }}</span>
          <span>通过: {{ benchmarkResult.passed || 0 }}</span>
          <span>失败: {{ (benchmarkResult.total || 0) - (benchmarkResult.passed || 0) }}</span>
        </div>
      </div>

      <div v-else-if="!benchmarkRunning && !benchmarkLoading" class="benchmark-empty">
        <el-empty description="点击「启动评测」开始 Benchmark 跑批" :image-size="60" />
      </div>
    </div>

    <!-- 详细指标 -->
    <div class="metrics-grid">
      <div class="glass-card">
        <h3>📈 任务统计</h3>
        <div class="stat-list">
          <div class="stat-row"><span>总任务数</span><span>{{ metrics.total_tasks || 0 }}</span></div>
          <div class="stat-row"><span>成功任务</span><span>{{ metrics.success_tasks || 0 }}</span></div>
          <div class="stat-row"><span>失败任务</span><span>{{ metrics.failed_tasks || 0 }}</span></div>
          <div class="stat-row highlight"><span>成功率</span><span>{{ successRate }}%</span></div>
        </div>
      </div>

      <div class="glass-card">
        <h3>⚡ 性能指标</h3>
        <div class="stat-list">
          <div class="stat-row"><span>平均响应时间</span><span>{{ metrics.avg_response_time || 0 }}ms</span></div>
          <div class="stat-row"><span>代码可运行率</span><span>{{ metrics.code_run_rate || 0 }}%</span></div>
          <div class="stat-row"><span>测试通过率</span><span>{{ metrics.test_pass_rate || 0 }}%</span></div>
          <div class="stat-row highlight"><span>修复成功率</span><span>{{ metrics.repair_rate || 0 }}%</span></div>
        </div>
      </div>
    </div>

    <el-button type="primary" @click="refreshAll" :loading="loading" class="refresh-btn">
      刷新数据
    </el-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { getMetricsSummary, getBenchmarkResults, startBenchmarkRun, getBenchmarkStatus, handleApiError } from '../api/task'

const loading = ref(false)
const metrics = ref({})
const benchmarkResult = ref(null)
const benchmarkLoading = ref(false)
const benchmarkStarting = ref(false)
const benchmarkRunning = ref(false)
const benchmarkProgress = ref(0)
const benchmarkStatusText = ref('')
let pollTimer = null

const overviewMetrics = computed(() => [
  { label: '总任务数', value: metrics.value.total_tasks || 0 },
  { label: '成功率', value: `${metrics.value.success_rate || 0}%` },
  { label: '平均耗时', value: `${metrics.value.avg_response_time || 0}ms` },
  { label: '测试通过率', value: `${metrics.value.test_pass_rate || 0}%` }
])

const successRate = computed(() => {
  const total = metrics.value.total_tasks || 0
  const success = metrics.value.success_tasks || 0
  return total ? ((success / total) * 100).toFixed(1) : 0
})

const fetchMetrics = async () => {
  loading.value = true
  try {
    const response = await getMetricsSummary()
    if (response.data.code === 0) metrics.value = response.data.data || {}
  } catch (error) {
    ElMessage.error(handleApiError(error, '加载指标失败'))
  } finally {
    loading.value = false
  }
}

const fetchBenchmarkData = async () => {
  benchmarkLoading.value = true
  try {
    const response = await getBenchmarkResults()
    if (response.data.code === 0 && response.data.data && Object.keys(response.data.data).length > 0) {
      benchmarkResult.value = response.data.data
    }
  } catch (error) {
    if (error.response?.status !== 404) {
      console.error('加载 Benchmark 数据失败:', error)
    }
  } finally {
    benchmarkLoading.value = false
  }
}

const startBenchmark = async () => {
  benchmarkStarting.value = true
  benchmarkRunning.value = true
  benchmarkProgress.value = 0
  benchmarkStatusText.value = '正在启动评测...'
  benchmarkResult.value = null

  try {
    const response = await startBenchmarkRun()
    console.log('启动Benchmark响应:', response.data)
    if (response.data.code === 0) {
      const runId = response.data.data.run_id
      console.log('获取到 run_id:', runId)
      ElMessage.success('Benchmark 已启动')
      pollBenchmarkStatus(runId)
    } else {
      ElMessage.error(response.data.message || '启动失败')
      benchmarkRunning.value = false
      benchmarkStarting.value = false
    }
  } catch (error) {
    console.error('启动失败:', error)
    ElMessage.error(handleApiError(error, '启动 Benchmark 失败'))
    benchmarkRunning.value = false
    benchmarkStarting.value = false
  }
}

const pollBenchmarkStatus = (runId) => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const response = await getBenchmarkStatus(runId)
      console.log('轮询响应:', response.data)
      if (response.data.code === 0) {
        const data = response.data.data
        // 兼容不同的字段名
        const progress = data.progress !== undefined ? data.progress : 
                        (data.total > 0 ? Math.round((data.completed || 0) / data.total * 100) : 0)
        benchmarkProgress.value = progress
        benchmarkStatusText.value = data.status === 'running' 
          ? `正在执行... (${data.completed || 0}/${data.total || 30})` 
          : data.status === 'completed' ? '评测完成' : '评测失败'
        
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollTimer)
          pollTimer = null
          benchmarkRunning.value = false
          benchmarkStarting.value = false
          setTimeout(() => {
            fetchBenchmarkData()
          }, 1000)
          if (data.status === 'completed') {
            ElMessage.success('Benchmark 评测完成')
          } else {
            ElMessage.error('Benchmark 评测失败')
          }
        }
      }
    } catch (error) {
      console.error('轮询状态失败:', error)
    }
  }, 2000)
}

const refreshAll = () => {
  fetchMetrics()
  fetchBenchmarkData()
  ElMessage.success('已刷新')
}

onMounted(() => {
  fetchMetrics()
  fetchBenchmarkData()
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
.metrics-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 20px;
  min-height: 100vh;
  background-image: url('/微信图片_20260630155028_93_3.jpg') !important;
  background-size: cover !important;
  background-position: center !important;
  background-attachment: fixed !important;
  background-repeat: no-repeat !important;
  position: relative;
  border-radius: 0;
}

.metrics-container::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(10, 10, 26, 0.55);
  z-index: -1;
}

.hero { margin-bottom: 28px; position: relative; z-index: 1; }
.hero-title { font-size: 32px; font-weight: 700; color: #fff; letter-spacing: -0.5px; margin-bottom: 4px; }
.hero-sub { font-size: 15px; color: rgba(255,255,255,0.4); }

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}
.stat-card {
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 18px 16px;
  text-align: center;
}
.stat-label { display: block; font-size: 12px; color: rgba(255,255,255,0.3); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.stat-value { font-size: 28px; font-weight: 700; color: #fff; }

.benchmark-section {
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 20px 24px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}
.benchmark-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.benchmark-header h3 { color: #fff; font-size: 16px; font-weight: 600; margin: 0; }
.benchmark-progress { margin: 12px 0; }
.benchmark-status { color: rgba(255,255,255,0.4); font-size: 14px; margin-top: 6px; }
.benchmark-empty { padding: 10px 0; }
.benchmark-result { margin-top: 12px; }
.benchmark-summary {
  display: flex;
  gap: 20px;
  margin-top: 12px;
  padding: 10px 16px;
  background: rgba(255,255,255,0.04);
  border-radius: 8px;
  color: rgba(255,255,255,0.6);
  font-size: 13px;
  flex-wrap: wrap;
}

.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
  position: relative;
  z-index: 1;
}
.glass-card {
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px;
  padding: 24px;
}
.glass-card h3 { margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #fff; }

.stat-list { display: flex; flex-direction: column; gap: 6px; }
.stat-row {
  display: flex; justify-content: space-between;
  color: rgba(255,255,255,0.5); font-size: 14px;
  padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.stat-row span:last-child { color: rgba(255,255,255,0.8); font-weight: 500; }
.stat-row.highlight { color: #fff; font-weight: 600; }
.stat-row.highlight span:last-child { color: #4F6EF7; }

.refresh-btn { display: block; margin: 0 auto; position: relative; z-index: 1; }
</style>