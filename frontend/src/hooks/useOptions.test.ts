import { renderHook, waitFor } from '@testing-library/react'
import { useOptions } from './useOptions'

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
})
