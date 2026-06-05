import { useEffect, useState } from 'react'
import { fetchOptions } from '@/api/client'
import type { OptionsResponse } from '@/api/types'

// Options are static for the server's lifetime — cache them so remounts
// (e.g. navigating back via "New Run") skip the fetch and loading screen.
let _cached: OptionsResponse | null = null

interface UseOptionsResult {
  options: OptionsResponse | null
  loading: boolean
  error: string | null
}

export function useOptions(): UseOptionsResult {
  const [options, setOptions] = useState<OptionsResponse | null>(_cached)
  const [loading, setLoading] = useState(_cached === null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (_cached !== null) return
    fetchOptions()
      .then(data => {
        _cached = data
        setOptions(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load options'))
      .finally(() => setLoading(false))
  }, [])

  return { options, loading, error }
}
