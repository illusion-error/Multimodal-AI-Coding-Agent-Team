import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn()
}))

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => apiMock)
  }
}))

import {
  createTextTask,
  getBenchmarkStatus,
  getPromptVersions,
  startBenchmarkRun,
  updatePromptVersion
} from './task'

describe('task api wrappers', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
  })

  it('loads prompt versions and switches by canonical agent name', async () => {
    const promptPayload = {
      data: {
        code: 0,
        data: [
          {
            agent_name: 'CodeGenerator',
            version: 'v1.0',
            is_enabled: 1,
            change_log: 'default'
          }
        ]
      }
    }
    apiMock.get.mockResolvedValueOnce(promptPayload)
    apiMock.post.mockResolvedValueOnce({ data: { code: 0 } })

    const response = await getPromptVersions()
    await updatePromptVersion('CodeGenerator', 'v1.0')

    expect(apiMock.get).toHaveBeenCalledWith('/api/prompt/versions')
    expect(response.data.data[0]).toMatchObject({
      agent_name: 'CodeGenerator',
      version: 'v1.0'
    })
    expect(apiMock.post).toHaveBeenCalledWith('/api/prompt/version', {
      agent_name: 'CodeGenerator',
      version: 'v1.0'
    })
  })

  it('uses stable benchmark start and status endpoints', async () => {
    apiMock.post.mockResolvedValueOnce({
      data: { code: 0, data: { run_id: 'run-001', status: 'running' } }
    })
    apiMock.get.mockResolvedValueOnce({
      data: { code: 0, data: { run_id: 'run-001', status: 'completed' } }
    })

    await startBenchmarkRun()
    const statusResponse = await getBenchmarkStatus('run-001')

    expect(apiMock.post).toHaveBeenCalledWith('/api/benchmark/runs')
    expect(apiMock.get).toHaveBeenCalledWith('/api/benchmark/runs/run-001')
    expect(statusResponse.data.data.status).toBe('completed')
  })

  it('posts text tasks with problem_text and optional request API key header', async () => {
    apiMock.post.mockResolvedValueOnce({
      data: { code: 0, data: { task_id: 'task-001', status: 'running' } }
    })

    await createTextTask('two sum', 'sk-test')

    expect(apiMock.post).toHaveBeenCalledWith(
      '/api/tasks/text',
      { problem_text: 'two sum' },
      { headers: { 'X-DashScope-API-Key': 'sk-test' } }
    )
  })
})
