import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 60000,
})

// ===== 基础接口 =====
export const healthCheck = () => api.get('/api/health')

export const createTextTask = (problemText) => {
  return api.post('/api/tasks/text', { problem_text: problemText })
}

export const createImageTask = (imageFile, supplementText = '') => {
  const formData = new FormData()
  formData.append('image', imageFile)
  formData.append('supplement', supplementText)
  return api.post('/api/tasks/image', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ===== 任务相关 =====
export const getTaskList = () => api.get('/api/tasks')
export const getTaskDetail = (taskId) => api.get(`/api/tasks/${taskId}`)
export const getTaskReport = (taskId) => api.get(`/api/tasks/${taskId}/report`)

// ===== Agent 步骤 =====
export const getTaskSteps = (taskId) => api.get(`/api/tasks/${taskId}/steps`)

// ===== 测试用例 =====
export const getTaskTests = (taskId) => api.get(`/api/tasks/${taskId}/tests`)

// ===== 指标看板 =====
export const getMetricsSummary = () => api.get('/api/metrics/summary')

// ===== 重新执行 =====
export const rerunTask = (taskId) => api.post(`/api/tasks/${taskId}/rerun`)

// ===== 轮询任务状态 =====
export const pollTaskStatus = async (taskId, interval = 2000, maxAttempts = 60) => {
  let attempts = 0
  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      attempts++
      try {
        const response = await getTaskDetail(taskId)
        const data = response.data.data
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(timer)
          resolve(data)
        } else if (attempts >= maxAttempts) {
          clearInterval(timer)
          reject(new Error('任务超时'))
        }
      } catch (error) {
        clearInterval(timer)
        reject(error)
      }
    }, interval)
  })
}