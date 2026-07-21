import { useEffect, useState } from 'react'

export type StreamStatus = 'connecting' | 'running' | 'reconnecting' | 'complete' | 'error'

export interface StreamProgress {
  // null for single runs; the experiment index within a suite otherwise.
  experimentIndex: number | null
  candidateId: number
  iteration: number
}

interface UseEventStreamResult<TResult> {
  status: StreamStatus
  progress: StreamProgress | null
  result: TResult | null
  errorMessage: string | null
}

// Literal-typed wire shape so `data.type === '...'` narrows correctly (the
// generated schema shares one EventType enum across the event variants, which
// blocks discriminated-union narrowing). result is generic per stream.
type StreamEvent<TResult> =
  | { type: 'progress'; experiment_index?: number | null; candidate_id: number; iteration: number }
  | { type: 'complete'; result: TResult }
  | { type: 'error'; message: string }

const MAX_RETRIES = 3

// Shared SSE lifecycle for the single-run and suite streams. The only
// per-stream differences are the URL and the completion payload type
// (TResult); progress is reported uniformly, with experimentIndex null for a
// single run and set for a suite (the client-side demultiplexing key).
export function useEventStream<TResult>(url: string): UseEventStreamResult<TResult> {
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const [progress, setProgress] = useState<StreamProgress | null>(null)
  const [result, setResult] = useState<TResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    let closed = false
    let retryCount = 0
    let hasEverConnected = false
    const es = new EventSource(url)

    es.onopen = () => {
      hasEverConnected = true
      retryCount = 0
      setStatus('running')
    }

    es.onmessage = (event: MessageEvent<string>) => {
      let data: StreamEvent<TResult>
      try {
        data = JSON.parse(event.data) as StreamEvent<TResult>
      } catch {
        closed = true
        setErrorMessage('Received malformed data from server.')
        setStatus('error')
        es.close()
        return
      }
      if (data.type === 'progress') {
        setStatus('running')
        setProgress({
          experimentIndex: data.experiment_index ?? null,
          candidateId: data.candidate_id,
          iteration: data.iteration,
        })
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
  }, [url])

  return { status, progress, result, errorMessage }
}
