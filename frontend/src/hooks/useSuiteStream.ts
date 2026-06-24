import type { SuiteResult } from '@/api/types'
import { useEventStream, type StreamProgress, type StreamStatus } from './useEventStream'

interface UseSuiteStreamResult {
  status: StreamStatus
  // progress.experimentIndex routes the live counter to the active experiment.
  progress: StreamProgress | null
  result: SuiteResult | null
  errorMessage: string | null
}

export function useSuiteStream(suiteId: string): UseSuiteStreamResult {
  return useEventStream<SuiteResult>(`/api/suites/${suiteId}/stream`)
}
