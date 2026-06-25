import { http, HttpResponse } from 'msw'

export const TEST_RUN_ID = 'test-run-id'

export const MOCK_OPTIONS = {
  strategies: ['zero_shot', 'few_shot', 'cot'],
  models: { openai: ['gpt-4o-mini', 'gpt-4o'] },
  parameters: {},
  examples: [],
}

export const handlers = [
  http.get('/api/options', () => {
    return HttpResponse.json(MOCK_OPTIONS)
  }),

  http.post('/api/generate', () => {
    return HttpResponse.json({ run_id: TEST_RUN_ID })
  }),

  http.post('/api/suites', () => {
    return HttpResponse.json({ run_id: TEST_RUN_ID })
  }),

  http.post('/api/runs/:id/cancel', () => new HttpResponse(null, { status: 204 })),
]
