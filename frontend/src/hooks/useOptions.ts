import { useEffect, useState } from 'react'
import { fetchOptions } from '@/api/client'
import type { OptionsResponse } from '@/api/types'

interface UseOptionsResult {
  options: OptionsResponse | null
  loading: boolean
  error: string | null
}

export function useOptions(): UseOptionsResult {
  const [options, setOptions] = useState<OptionsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchOptions()
      .then(setOptions)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load options'))
      .finally(() => setLoading(false))
  }, [])

  return { options, loading, error }
}
