import { renderHook, act } from '@testing-library/react'
import { vi } from 'vitest'
import { cancelRun } from '@/api/client'
import { useRunCancel } from './useRunCancel'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, cancelRun: vi.fn() }
})
const mockCancelRun = vi.mocked(cancelRun)

// navigator.sendBeacon does not exist in happy-dom (the hook calls it
// optionally), so define it rather than spying on a missing method.
function stubBeacon() {
  const sendBeacon = vi.fn()
  Object.defineProperty(navigator, 'sendBeacon', {
    value: sendBeacon,
    configurable: true,
    writable: true,
  })
  return sendBeacon
}

describe('useRunCancel', () => {
  beforeEach(() => {
    mockCancelRun.mockReset()
  })

  it('posts the cancel and flips to stopping', () => {
    const { result } = renderHook(() => useRunCancel('run-1', true))
    expect(result.current.stopping).toBe(false)

    act(() => result.current.stop())

    expect(mockCancelRun).toHaveBeenCalledWith('run-1')
    expect(result.current.stopping).toBe(true)
  })

  it('beacons a cancel when the page is hidden mid-run', () => {
    const sendBeacon = stubBeacon()
    renderHook(() => useRunCancel('run-2', true))

    window.dispatchEvent(new Event('pagehide'))

    expect(sendBeacon).toHaveBeenCalledWith('/api/runs/run-2/cancel')
  })

  it('does not beacon for a run that already finished', () => {
    const sendBeacon = stubBeacon()
    renderHook(() => useRunCancel('run-3', false))

    window.dispatchEvent(new Event('pagehide'))

    expect(sendBeacon).not.toHaveBeenCalled()
  })

  it('unregisters the listener on unmount', () => {
    const sendBeacon = stubBeacon()
    const { unmount } = renderHook(() => useRunCancel('run-4', true))

    unmount()
    window.dispatchEvent(new Event('pagehide'))

    expect(sendBeacon).not.toHaveBeenCalled()
  })
})
