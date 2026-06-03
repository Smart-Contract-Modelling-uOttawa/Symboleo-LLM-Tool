import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/options', () => {
    return HttpResponse.json({
      strategies: ['zero_shot', 'few_shot', 'cot'],
      models: { openai: ['gpt-4o-mini', 'gpt-4o'] },
      parameters: {},
      examples: [],
    })
  }),

  http.post('/api/generate', () => {
    return HttpResponse.json({ run_id: 'test-run-id' })
  }),
]
