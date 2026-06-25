import type { components } from './schema'
import type { GenerateRequest, RunCreatedResponse, OptionsResponse, SuiteRequest } from './types'

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

export function generate(request: GenerateRequest): Promise<RunCreatedResponse> {
  return apiFetch<RunCreatedResponse>('/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function createSuite(request: SuiteRequest): Promise<RunCreatedResponse> {
  return apiFetch<RunCreatedResponse>('/api/suites', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

// Cancel a run or suite by id. Best-effort and fire-and-forget: the endpoint
// returns 204 (no body, so not apiFetch), and a finished/expired run is fine to
// "cancel" — we don't surface failures to the user who just asked to stop.
export async function cancelRun(runId: string): Promise<void> {
  await fetch(`/api/runs/${runId}/cancel`, { method: 'POST' }).catch(() => {})
}
