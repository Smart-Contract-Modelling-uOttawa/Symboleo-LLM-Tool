import { useCallback, useEffect, useState } from 'react'
import { cancelRun } from '@/api/client'

// Explicit cancellation for a run/suite results page. Returns a `stop` action for
// the Stop button and a `stopping` flag for its label; while the run is live it
// also fires a best-effort beacon on tab close / navigate-away so a voluntary
// leave cancels immediately (the grace sweep is only the fallback for crashes).
export function useRunCancel(
  runId: string,
  isRunning: boolean,
): { stopping: boolean; stop: () => void } {
  const [stopping, setStopping] = useState(false)

  const stop = useCallback(() => {
    setStopping(true)
    void cancelRun(runId)
  }, [runId])

  useEffect(() => {
    if (!isRunning) return
    // pagehide covers normal unload and bfcache; sendBeacon survives the unload.
    const onLeave = () => navigator.sendBeacon?.(`/api/runs/${runId}/cancel`)
    window.addEventListener('pagehide', onLeave)
    return () => window.removeEventListener('pagehide', onLeave)
  }, [runId, isRunning])

  return { stopping, stop }
}
