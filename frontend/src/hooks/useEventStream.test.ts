import { renderHook, act } from '@testing-library/react'
import { vi } from 'vitest'
import { useEventStream } from './useEventStream'

// happy-dom has no EventSource, which is why the pages mock the stream wrappers
// wholesale. This stub supplies one, so the SSE lifecycle itself — retry
// budgeting, never-connected vs mid-stream drops, malformed payloads — can be
// driven directly instead of going untested behind those mocks.
class StubEventSource {
  static instances: StubEventSource[] = []
  readonly url: string
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    StubEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

const source = () => StubEventSource.instances[StubEventSource.instances.length - 1]
const open = () => act(() => source().onopen?.())
const fail = () => act(() => source().onerror?.())
const send = (payload: unknown) =>
  act(() => source().onmessage?.({ data: JSON.stringify(payload) }))

describe('useEventStream', () => {
  beforeEach(() => {
    StubEventSource.instances = []
    vi.stubGlobal('EventSource', StubEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('subscribes to the url it was given', () => {
    renderHook(() => useEventStream('/api/runs/abc/stream'))
    expect(source().url).toBe('/api/runs/abc/stream')
  })

  it('starts connecting and flips to running once the stream opens', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    expect(result.current.status).toBe('connecting')
    open()
    expect(result.current.status).toBe('running')
  })

  it('maps a progress event, defaulting experimentIndex to null for a single run', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    send({ type: 'progress', candidate_id: 1, iteration: 2 })
    expect(result.current.progress).toEqual({
      experimentIndex: null,
      candidateId: 1,
      iteration: 2,
    })
  })

  it('keeps experiment_index when a suite tags it (the client-side demux key)', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    send({ type: 'progress', experiment_index: 3, candidate_id: 0, iteration: 1 })
    expect(result.current.progress?.experimentIndex).toBe(3)
  })

  it('stores the payload and closes the stream on complete', () => {
    const { result } = renderHook(() => useEventStream<{ ok: boolean }>('/x'))
    open()
    send({ type: 'complete', result: { ok: true } })
    expect(result.current.status).toBe('complete')
    expect(result.current.result).toEqual({ ok: true })
    expect(source().closed).toBe(true)
  })

  it('captures the persistence fields from a complete event', () => {
    const { result } = renderHook(() => useEventStream<{ ok: boolean }>('/x'))
    open()
    send({
      type: 'complete',
      result: { ok: true },
      output_dir: 'output/run_20260101_120000',
      write_error: 'Results were not written to disk: disk full',
    })
    expect(result.current.outputDir).toBe('output/run_20260101_120000')
    expect(result.current.writeError).toBe('Results were not written to disk: disk full')
  })

  it('defaults the persistence fields to null when the event omits them', () => {
    const { result } = renderHook(() => useEventStream<{ ok: boolean }>('/x'))
    open()
    send({ type: 'complete', result: { ok: true } })
    expect(result.current.outputDir).toBeNull()
    expect(result.current.writeError).toBeNull()
  })

  it('surfaces a server error event and closes the stream', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    send({ type: 'error', message: 'pipeline boom' })
    expect(result.current.status).toBe('error')
    expect(result.current.errorMessage).toBe('pipeline boom')
    expect(source().closed).toBe(true)
  })

  it('reports a malformed payload instead of throwing', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    act(() => source().onmessage?.({ data: 'not json at all' }))
    expect(result.current.status).toBe('error')
    expect(result.current.errorMessage).toBe('Received malformed data from server.')
    expect(source().closed).toBe(true)
  })

  it('fails immediately when the stream never connected (404 or server down)', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    fail()
    expect(result.current.status).toBe('error')
    expect(result.current.errorMessage).toBe('Connection lost or run not found.')
    expect(source().closed).toBe(true)
  })

  it('retries a mid-stream drop and gives up on the third failure', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    fail()
    expect(result.current.status).toBe('reconnecting')
    fail()
    expect(result.current.status).toBe('reconnecting')
    fail() // MAX_RETRIES reached
    expect(result.current.status).toBe('error')
    expect(result.current.errorMessage).toBe('Connection lost or run not found.')
  })

  it('restarts the retry budget after a successful reconnect', () => {
    const { result } = renderHook(() => useEventStream('/x'))
    open()
    fail()
    fail()
    open() // the browser got back in
    fail()
    fail()
    // Five failures in total, but only two since the last open — without the
    // reset this would already have exhausted the budget and errored.
    expect(result.current.status).toBe('reconnecting')
  })

  it('closes the stream when the consumer unmounts', () => {
    const { unmount } = renderHook(() => useEventStream('/x'))
    const stream = source()
    unmount()
    expect(stream.closed).toBe(true)
  })
})
