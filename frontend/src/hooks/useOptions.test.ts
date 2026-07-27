import { renderHook, waitFor } from '@testing-library/react'
import { resetOptionsCache, useOptions } from './useOptions'

// Error path is covered by ConfigPage > "shows an error when the options fetch fails"
// which exercises the same useOptions code path through a real component render.
describe('useOptions', () => {
  it('returns loading: true before the fetch resolves', () => {
    const { result } = renderHook(() => useOptions())
    expect(result.current.loading).toBe(true)
    expect(result.current.options).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('returns options and clears loading on success', async () => {
    const { result } = renderHook(() => useOptions())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.options).not.toBeNull()
    expect(result.current.options?.strategies).toEqual(['zero_shot', 'few_shot', 'cot'])
    expect(result.current.error).toBeNull()
  })

  it('serves the cache on remount until resetOptionsCache clears it', async () => {
    // Binds the test seam directly: if resetOptionsCache became a no-op, the
    // post-reset mount would serve the cache synchronously (loading: false)
    // instead of refetching, and every cross-test /api/options override in
    // the suite would silently see stale data.
    const first = renderHook(() => useOptions())
    await waitFor(() => expect(first.result.current.loading).toBe(false))

    const warm = renderHook(() => useOptions())
    expect(warm.result.current.loading).toBe(false)

    resetOptionsCache()
    const cold = renderHook(() => useOptions())
    expect(cold.result.current.loading).toBe(true)
  })
})
