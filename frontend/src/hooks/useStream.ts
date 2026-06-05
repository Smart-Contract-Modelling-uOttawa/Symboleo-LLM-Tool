import { useEffect, useState } from 'react'
import type { PipelineResult, SSEEvent } from '@/api/types'

type StreamStatus = 'connecting' | 'running' | 'reconnecting' | 'complete' | 'error'

interface UseStreamResult {
  status: StreamStatus
  progress: { candidateId: number; iteration: number } | null
  result: PipelineResult | null
  errorMessage: string | null
}

const MAX_RETRIES = 3

export function useStream(runId: string): UseStreamResult {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [progress, setProgress] = useState<{ candidateId: number; iteration: number } | null>(null)
  const [result, setResult] = useState<PipelineResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let closed = false
    let retryCount = 0
    let hasEverConnected = false
    const es = new EventSource(`/api/runs/${runId}/stream`)

    es.onopen = () => {
      hasEverConnected = true
      retryCount = 0
      setStatus('running')
    }

    es.onmessage = (event: MessageEvent<string>) => {
      let data: SSEEvent
      try {
        data = JSON.parse(event.data) as SSEEvent
      } catch {
        closed = true
        setErrorMessage('Received malformed data from server.')
        setStatus('error')
        es.close()
        return
      }
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
      if (closed) {
        es.close()
        return
      }
      // Never connected: likely a 404 or server down — fail immediately
      if (!hasEverConnected) {
        closed = true
        setErrorMessage('Connection lost or run not found.')
        setStatus('error')
        es.close()
        return
      }
      // Mid-stream drop: retry up to MAX_RETRIES, browser handles backoff
      retryCount++
      if (retryCount >= MAX_RETRIES) {
        closed = true
        setErrorMessage('Connection lost or run not found.')
        setStatus('error')
        es.close()
      } else {
        setStatus('reconnecting')
      }
    }

    return () => {
      closed = true
      es.close()
    }
  }, [runId])

  return { status, progress, result, errorMessage }
}
