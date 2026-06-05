import type { components } from './schema'
import type { GenerateRequest, RunCreatedResponse, OptionsResponse } from './types'

type ErrorBody = components['schemas']['HTTPValidationError'] | { detail?: string }

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let message = 'Request failed'
    try {
      const data = await response.json() as ErrorBody
      const { detail } = data
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail)) message = detail.map(e => e.msg).join('; ')
    } catch { /* non-JSON body — keep generic message */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export function fetchOptions(): Promise<OptionsResponse> {
  return apiFetch<OptionsResponse>('/api/options')
}

export function submitGenerate(request: GenerateRequest): Promise<RunCreatedResponse> {
  return apiFetch<RunCreatedResponse>('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}
