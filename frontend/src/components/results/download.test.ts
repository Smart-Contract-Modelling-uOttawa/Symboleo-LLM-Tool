import { vi } from 'vitest'
import { triggerDownload } from './download'

// happy-dom has no object-URL implementation, and a real anchor click would try
// to navigate — both are stubbed so the download mechanics can be asserted.
function stubObjectUrl() {
  const createObjectURL = vi.fn(() => 'blob:stub')
  const revokeObjectURL = vi.fn()
  Object.defineProperty(URL, 'createObjectURL', {
    value: createObjectURL,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: revokeObjectURL,
    configurable: true,
    writable: true,
  })
  return { createObjectURL, revokeObjectURL }
}

function captureClicks() {
  const clicked: HTMLAnchorElement[] = []
  const spy = vi
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
  return { clicked, restore: () => spy.mockRestore() }
}

describe('triggerDownload', () => {
  it('clicks an anchor carrying the requested filename', () => {
    stubObjectUrl()
    const { clicked, restore } = captureClicks()

    triggerDownload('a,b\n1,2', 'suite_summary.csv', 'text/csv')

    expect(clicked).toHaveLength(1)
    expect(clicked[0].download).toBe('suite_summary.csv')
    expect(clicked[0].href).toContain('blob:stub')
    restore()
  })

  it('wraps the content in a blob of the requested mime type', async () => {
    const { createObjectURL } = stubObjectUrl()
    const { restore } = captureClicks()

    triggerDownload('a,b\n1,2', 'suite_summary.csv', 'text/csv')

    // The stub takes no declared parameters, so the recorded call is typed as an
    // empty tuple — assert the argument the browser actually receives.
    const [blob] = createObjectURL.mock.calls[0] as unknown as [Blob]
    expect(blob.type).toBe('text/csv')
    await expect(blob.text()).resolves.toBe('a,b\n1,2')
    restore()
  })

  it('leaves no anchor behind in the document', () => {
    stubObjectUrl()
    const { restore } = captureClicks()

    triggerDownload('x', 'x.txt', 'text/plain')

    expect(document.querySelector('a[download]')).toBeNull()
    restore()
  })

  it('revokes the object url once the download has started', () => {
    vi.useFakeTimers()
    const { revokeObjectURL } = stubObjectUrl()
    const { restore } = captureClicks()

    triggerDownload('x', 'x.txt', 'text/plain')
    // Held until after the click so the browser can read it, then released.
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(100)

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:stub')
    vi.useRealTimers()
    restore()
  })
})
