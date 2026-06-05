import { useEffect, useState } from 'react'
import type { PipelineResult, SSEEvent } from '@/api/types'

type StreamStatus = 'connecting' | 'running' | 'complete' | 'error'

interface UseStreamResult {
  status: StreamStatus
  progress: { candidateId: number; iteration: number } | null
  result: PipelineResult | null
  errorMessage: string | null
}

export function useStream(runId: string): UseStreamResult {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [progress, setProgress] = useState<{ candidateId: number; iteration: number } | null>(null)
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let closed = false
    const es = new EventSource(`/api/runs/${runId}/stream`)

    es.onopen = () => setStatus('running')

    es.onmessage = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as SSEEvent
      if (data.type === 'progress') {
        setStatus('running')
        setProgress({ candidateId: data.candidate_id, iteration: data.iteration })
      } else if (data.type === 'complete') {
        closed = true
        setResult(data.result)
        setStatus('complete')
        es.close()
      } else if (data.type === 'error') {
        closed = true
        setErrorMessage(data.message)
        setStatus('error')
        es.close()
      }
    }

    es.onerror = () => {
      if (!closed) {
        setErrorMessage('Connection lost or run not found.')
        setStatus('error')
      }
      es.close()
    }

    return () => {
      closed = true
      es.close()
    }
  }, [runId])

  return { status, progress, result, errorMessage }
}
