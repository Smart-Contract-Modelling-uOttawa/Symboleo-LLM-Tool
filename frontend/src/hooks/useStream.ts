import type { PipelineResult } from '@/api/types'
import { useEventStream, type StreamStatus } from './useEventStream'

interface UseStreamResult {
  status: StreamStatus
  progress: { candidateId: number; iteration: number } | null
  result: PipelineResult | null
  errorMessage: string | null
  outputDir: string | null
  writeError: string | null
}

export function useStream(runId: string): UseStreamResult {
  const { status, progress, result, errorMessage, outputDir, writeError } =
    useEventStream<PipelineResult>(`/api/runs/${runId}/stream`)
  return {
    status,
    // A single run has no experiment dimension — drop it from the public shape.
    progress: progress
      ? { candidateId: progress.candidateId, iteration: progress.iteration }
      : null,
    result,
    errorMessage,
    outputDir,
    writeError,
  }
}
