import type { GenerateRequest, RunCreatedResponse, OptionsResponse } from './types'

export async function fetchOptions(): Promise<OptionsResponse> {
  const response = await fetch('/api/options')
  if (!response.ok) throw new Error('Failed to load options')
  return response.json() as Promise<OptionsResponse>
}

export async function submitGenerate(request: GenerateRequest): Promise<RunCreatedResponse> {
  const response = await fetch('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    const data = await response.json() as { detail?: string | Array<{ msg: string }> }
    const detail = data?.detail
    if (typeof detail === 'string') throw new Error(detail)
    if (Array.isArray(detail)) throw new Error(detail.map(e => e.msg).join('; '))
    throw new Error('Request failed')
  }
  return response.json() as Promise<RunCreatedResponse>
}
