import { renderHook } from '@testing-library/react'
import { vi } from 'vitest'
import { useEventStream } from './useEventStream'
import { useStream } from './useStream'
import { useSuiteStream } from './useSuiteStream'

vi.mock('./useEventStream')
const mockUseEventStream = vi.mocked(useEventStream)

// The two wrappers differ only in the URL they subscribe to and how much of the
// progress shape they expose — both are invisible to the pages, which mock these
// hooks, so swapping the URLs would otherwise go unnoticed.
describe('stream wrappers', () => {
  beforeEach(() => {
    mockUseEventStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 4, candidateId: 1, iteration: 2 },
      result: null,
      errorMessage: null,
    })
  })

  it('useStream subscribes to the run stream and drops the experiment dimension', () => {
    const { result } = renderHook(() => useStream('run-9'))

    expect(mockUseEventStream).toHaveBeenCalledWith('/api/runs/run-9/stream')
    expect(result.current.progress).toEqual({ candidateId: 1, iteration: 2 })
  })

  it('useSuiteStream subscribes to the suite stream and keeps the experiment index', () => {
    const { result } = renderHook(() => useSuiteStream('suite-9'))

    expect(mockUseEventStream).toHaveBeenCalledWith('/api/suites/suite-9/stream')
    expect(result.current.progress?.experimentIndex).toBe(4)
  })

  it('passes a null progress through unchanged', () => {
    mockUseEventStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })

    const { result } = renderHook(() => useStream('run-9'))

    expect(result.current.progress).toBeNull()
  })
})
