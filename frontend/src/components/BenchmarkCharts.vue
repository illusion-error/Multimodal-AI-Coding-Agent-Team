<!-- src/components/BenchmarkCharts.vue -->
<template>
  <div class="benchmark-charts">
    <div class="charts-header">
      <h3>📊 Benchmark 评测结果</h3>
      <el-button size="small" @click="$emit('refresh')" :loading="loading">
        刷新数据
      </el-button>
    </div>

    <div v-if="!data || Object.keys(data).length === 0" class="charts-empty">
      <el-empty description="暂无 Benchmark 数据" :image-size="60" />
    </div>

    <div v-else class="charts-grid">
      <!-- 概览指标 -->
      <div class="metrics-overview">
        <div class="metric-card" v-for="item in overviewMetrics" :key="item.label">
          <div class="metric-value" :style="{ color: item.color }">{{ item.value }}</div>
          <div class="metric-label">{{ item.label }}</div>
        </div>
      </div>

      <!-- 通过率图表 -->
      <div class="chart-card">
        <h4>📈 各题型通过率</h4>
        <div class="chart-container" ref="passRateChartRef"></div>
      </div>

      <!-- 耗时分布图表 -->
      <div class="chart-card">
        <h4>⏱️ 各题型平均耗时</h4>
        <div class="chart-container" ref="durationChartRef"></div>
      </div>

      <!-- 详细表格 -->
      <div class="chart-card table-card">
        <h4>📋 详细评测结果</h4>
        <el-table :data="tableData" size="small" style="width: 100%">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="title" label="题目" min-width="120" />
          <el-table-column prop="difficulty" label="难度" width="80">
            <template #default="{ row }">
              <el-tag :type="getDifficultyType(row.difficulty)" size="small">
                {{ row.difficulty }}
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
          <el-table-column prop="error" label="错误信息" min-width="100">
            <template #default="{ row }">
              <span class="error-text">{{ row.error || '—' }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: {
    type: Object,
    default: () => ({})
  },
  loading: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['refresh'])

const passRateChartRef = ref(null)
const durationChartRef = ref(null)
let passRateChart = null
let durationChart = null

const overviewMetrics = computed(() => {
  const d = props.data
  return [
    { label: '总题目数', value: d.total || 0, color: '#409EFF' },
    { label: '通过数', value: d.passed || 0, color: '#67c23a' },
    { label: '通过率', value: `${d.pass_rate || 0}%`, color: '#67c23a' },
    { label: '平均耗时', value: `${d.avg_duration || 0}ms`, color: '#e6a23c' }
  ]
})

const tableData = computed(() => {
  return props.data.details || []
})

const getDifficultyType = (difficulty) => {
  const map = {
    '简单': 'success',
    '中等': 'warning',
    '困难': 'danger'
  }
  return map[difficulty] || 'info'
}

const initCharts = () => {
  nextTick(() => {
    initPassRateChart()
    initDurationChart()
  })
}

const initPassRateChart = () => {
  if (!passRateChartRef.value) return
  if (passRateChart) {
    passRateChart.dispose()
  }
  passRateChart = echarts.init(passRateChartRef.value)

  const details = props.data.details || []
  const categories = details.map(d => d.title || d.id || '未知')
  const passData = details.map(d => d.passed ? 100 : 0)

  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const detail = details[idx] || {}
        return `<strong>${detail.title || detail.id || '未知'}</strong><br/>
                通过: ${detail.passed ? '✅ 是' : '❌ 否'}<br/>
                耗时: ${detail.duration || 0}ms<br/>
                难度: ${detail.difficulty || '—'}<br/>
                ${detail.error ? '错误: ' + detail.error : ''}`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '8%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        rotate: 30,
        interval: 0,
        fontSize: 10
      }
    },
    yAxis: {
      type: 'value',
      max: 100,
      name: '通过率 (%)'
    },
    series: [{
      type: 'bar',
      data: passData,
      itemStyle: {
        color: (params) => {
          return params.value === 100 ? '#67c23a' : '#f56c6c'
        }
      },
      label: {
        show: true,
        formatter: (params) => params.value === 100 ? '✅' : '❌',
        position: 'top'
      }
    }]
  }

  passRateChart.setOption(option)
  passRateChart.resize()
}

const initDurationChart = () => {
  if (!durationChartRef.value) return
  if (durationChart) {
    durationChart.dispose()
  }
  durationChart = echarts.init(durationChartRef.value)

  const details = props.data.details || []
  const categories = details.map(d => d.title || d.id || '未知')
  const durations = details.map(d => d.duration || 0)

  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params[0]
        const idx = p.dataIndex
        const detail = details[idx] || {}
        return `<strong>${detail.title || detail.id || '未知'}</strong><br/>
                耗时: ${detail.duration || 0}ms<br/>
                通过: ${detail.passed ? '✅ 是' : '❌ 否'}`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '8%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: {
        rotate: 30,
        interval: 0,
        fontSize: 10
      }
    },
    yAxis: {
      type: 'value',
      name: '耗时 (ms)'
    },
    series: [{
      type: 'bar',
      data: durations,
      itemStyle: {
        color: (params) => {
          const detail = details[params.dataIndex] || {}
          return detail.passed ? '#67c23a' : '#f56c6c'
        }
      },
      label: {
        show: true,
        formatter: (params) => `${params.value}ms`,
        position: 'top',
        fontSize: 10
      }
    }]
  }

  durationChart.setOption(option)
  durationChart.resize()
}

const resizeCharts = () => {
  if (passRateChart) passRateChart.resize()
  if (durationChart) durationChart.resize()
}

watch(() => props.data, () => {
  initCharts()
}, { deep: true })

onMounted(() => {
  initCharts()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  if (passRateChart) passRateChart.dispose()
  if (durationChart) durationChart.dispose()
})
</script>

<style scoped>
.benchmark-charts {
  margin: 16px 0;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}

.charts-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.charts-header h3 {
  margin: 0;
  color: #303133;
  font-size: 16px;
}

.charts-empty {
  padding: 20px 0;
}

.metrics-overview {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.metric-card {
  background: #fff;
  padding: 12px 16px;
  border-radius: 6px;
  text-align: center;
  border: 1px solid #ebeef5;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
}

.metric-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.chart-card {
  background: #fff;
  padding: 12px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  margin-bottom: 16px;
}

.chart-card h4 {
  margin: 0 0 10px 0;
  color: #303133;
  font-size: 14px;
}

.chart-container {
  width: 100%;
  height: 250px;
}

.table-card {
  overflow: auto;
}

.error-text {
  color: #f56c6c;
  font-size: 12px;
}
</style>