<!-- src/views/MetricsView.vue -->
<template>
  <div class="metrics-container">
    <h1>📊 指标看板</h1>

    <!-- 概览卡片 -->
    <el-row :gutter="20" class="metrics-cards">
      <el-col :span="6" v-for="item in overviewMetrics" :key="item.label">
        <el-card shadow="hover">
          <div class="metric-item">
            <div class="metric-value">{{ item.value }}</div>
            <div class="metric-label">{{ item.label }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Benchmark 图表 -->
    <el-card v-if="stage2Enabled" class="benchmark-card">
      <BenchmarkCharts :data="benchmarkData" :loading="benchmarkLoading" @refresh="fetchBenchmarkData" />
    </el-card>

    <!-- 详细指标 -->
    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="12">
        <el-card>
          <h3>📈 任务统计</h3>
          <div class="chart-placeholder">
            <p>总任务数：{{ metrics.total_tasks || 0 }}</p>
            <p>成功任务：{{ metrics.success_tasks || 0 }}</p>
            <p>失败任务：{{ metrics.failed_tasks || 0 }}</p>
            <p>成功率：{{ successRate }}%</p>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <h3>⚡ 性能指标</h3>
          <div class="chart-placeholder">
            <p>平均响应时间：{{ metrics.avg_response_time || 0 }}ms</p>
            <p>代码可运行率：{{ codeRunRate }}%</p>
            <p>测试通过率：{{ testPassRate }}%</p>
            <p>修复成功率：{{ repairRate }}%</p>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-button 
      type="primary" 
      @click="refreshAll" 
      :loading="loading"
      style="margin-top: 20px"
    >
      刷新数据
    </el-button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getMetricsSummary, getBenchmarkData, handleApiError } from '../api/task'
import BenchmarkCharts from '../components/BenchmarkCharts.vue'

const loading = ref(false)
const benchmarkLoading = ref(false)
const metrics = ref({})
const benchmarkData = ref({})
const stage2Enabled = import.meta.env.VITE_ENABLE_STAGE2 === 'true'

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

const codeRunRate = computed(() => metrics.value.code_run_rate || 0)
const testPassRate = computed(() => metrics.value.test_pass_rate || 0)
const repairRate = computed(() => metrics.value.repair_rate || 0)

const fetchMetrics = async () => {
  loading.value = true
  try {
    const response = await getMetricsSummary()
    if (response.data.code === 0) {
      metrics.value = response.data.data || {}
    }
  } catch (error) {
    console.error('加载指标失败:', error)
    ElMessage.error(handleApiError(error, '加载指标失败'))
  } finally {
    loading.value = false
  }
}

const fetchBenchmarkData = async () => {
  if (!stage2Enabled) return
  benchmarkLoading.value = true
  try {
    const response = await getBenchmarkData()
    if (response.data.code === 0) {
      benchmarkData.value = response.data.data || {}
    } else {
      benchmarkData.value = {}
    }
  } catch (error) {
    if (error.response && error.response.status === 404) {
      benchmarkData.value = {}
    } else {
      console.error('加载 Benchmark 数据失败:', error)
      ElMessage.error(handleApiError(error, '加载 Benchmark 数据失败'))
    }
  } finally {
    benchmarkLoading.value = false
  }
}

const refreshAll = () => {
  fetchMetrics()
  if (stage2Enabled) fetchBenchmarkData()
  ElMessage.success('已刷新')
}

onMounted(() => {
  fetchMetrics()
  if (stage2Enabled) fetchBenchmarkData()
})
</script>

<style scoped>
.metrics-container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.metrics-cards { margin-bottom: 20px; }
.metric-item { text-align: center; }
.metric-value { 
  font-size: 28px; 
  font-weight: 700; 
  color: #409EFF;
}
.metric-label { 
  font-size: 14px; 
  color: #909399; 
  margin-top: 8px;
}
.chart-placeholder { padding: 10px 0; }
.chart-placeholder p { margin: 8px 0; font-size: 15px; }
.benchmark-card { margin-top: 20px; }
</style>
