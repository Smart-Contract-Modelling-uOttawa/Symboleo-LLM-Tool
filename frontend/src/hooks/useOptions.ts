import { useEffect, useState } from 'react'
import { fetchOptions } from '@/api/client'
import type { OptionsResponse } from '@/api/types'

// Options are static for the server's lifetime — cache them so remounts
// (e.g. navigating back via "New Run") skip the fetch and loading screen.
let optionsCache: OptionsResponse | null = null

// Test seam: without this, the module cache leaks options across tests, so a
// test overriding GET /api/options is served an earlier test's payload.
// Called from test/setup.ts's afterEach; production code never calls it.
export function resetOptionsCache(): void {
  optionsCache = null
}

interface UseOptionsResult {
  options: OptionsResponse | null
  loading: boolean
  error: string | null
}

export function useOptions(): UseOptionsResult {
  const [options, setOptions] = useState<OptionsResponse | null>(optionsCache)
  const [loading, setLoading] = useState(optionsCache === null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (optionsCache !== null) return
    fetchOptions()
      .then(data => {
        optionsCache = data
        setOptions(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load options'))
      .finally(() => setLoading(false))
  }, [])

  return { options, loading, error }
}
