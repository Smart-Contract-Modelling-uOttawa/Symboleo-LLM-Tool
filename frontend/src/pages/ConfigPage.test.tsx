import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { vi } from 'vitest'
import { server } from '@/test/server'
import { TEST_RUN_ID } from '@/test/handlers'
import ConfigPage from './ConfigPage'

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

function renderConfigPage() {
  return render(
    <MemoryRouter>
      <ConfigPage />
    </MemoryRouter>
  )
}

function makeFile(content = 'Contract text', name = 'contract.txt') {
  return new File([content], name, { type: 'text/plain' })
}

describe('ConfigPage', () => {
  beforeEach(() => mockNavigate.mockReset())

  it('shows a loading state while options are being fetched', () => {
    renderConfigPage()
    expect(screen.getByText('Loading options...')).toBeInTheDocument()
  })

  it('shows an error when the options fetch fails', async () => {
    server.use(
      http.get('/api/options', () =>
        HttpResponse.json({ detail: 'Server error' }, { status: 500 })
      )
    )
    renderConfigPage()
    await screen.findByText('Server error')
  })

  it('renders the form after options load', async () => {
    renderConfigPage()
    await screen.findByText('Symboleo LLM Tool')
    expect(screen.getByText('Contract File')).toBeInTheDocument()
    expect(screen.getAllByText('Model').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Strategy').length).toBeGreaterThan(0)
  })

  it('disables Generate when no contract file is loaded', async () => {
    renderConfigPage()
    const button = await screen.findByRole('button', { name: 'Generate' })
    expect(button).toBeDisabled()
  })

  it('enables Generate and shows the filename after a .txt file is uploaded', async () => {
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile())

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )
    expect(screen.getByText('contract.txt')).toBeInTheDocument()
  })

  it('submits the form and navigates to the results page', async () => {
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile())
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith(`/runs/${TEST_RUN_ID}`, {
        state: { warnings: [] },
      })
    )
  })

  it('forwards API warnings to the results page via navigation state', async () => {
    server.use(
      http.post('/api/generate', () =>
        HttpResponse.json({ run_id: TEST_RUN_ID, warnings: ['generation: temperature ignored'] })
      )
    )
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile())
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith(`/runs/${TEST_RUN_ID}`, {
        state: { warnings: ['generation: temperature ignored'] },
      })
    )
  })

  it('shows an error alert when submission fails', async () => {
    server.use(
      http.post('/api/generate', () =>
        HttpResponse.json({ detail: 'Unknown model' }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile())
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await screen.findByText('Unknown model')
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('sends the contract text in the request payload', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/generate', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ run_id: 'test-run-id' })
      })
    )
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile('My legal contract'))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect((capturedBody as Record<string, unknown>)?.contract_text).toBe('My legal contract')
    )
  })

  it('omits temperature from a stage whose field was cleared', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/generate', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ run_id: TEST_RUN_ID })
      })
    )
    const user = userEvent.setup()
    const { container } = renderConfigPage()
    await screen.findByRole('button', { name: 'Generate' })

    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(input, makeFile())
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Generate' })).not.toBeDisabled()
    )

    // Clear only the generation stage's field: generation must omit the key
    // while correction (untouched) still carries a number — proving the
    // omission is per-stage, not a global drop.
    const [generationTemp] = screen.getAllByLabelText('Temperature')
    await user.clear(generationTemp)

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => {
      const body = capturedBody as {
        generation?: Record<string, unknown>
        correction?: Record<string, unknown>
      }
      expect(body?.generation).toBeDefined()
      expect(body?.generation).not.toHaveProperty('temperature')
      expect(body?.correction).toHaveProperty('temperature', 0.2)
    })
  })
})
