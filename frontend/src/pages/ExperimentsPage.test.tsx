import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { vi } from 'vitest'
import { server } from '@/test/server'
import { TEST_RUN_ID } from '@/test/handlers'
import ExperimentsPage from './ExperimentsPage'

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

function renderExperimentsPage() {
  return render(
    <MemoryRouter>
      <ExperimentsPage />
    </MemoryRouter>
  )
}

function makeFile(content = 'Contract text', name = 'contract.txt') {
  return new File([content], name, { type: 'text/plain' })
}

async function uploadContract(container: HTMLElement, content = 'Contract text') {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  await userEvent.upload(input, makeFile(content))
}

describe('ExperimentsPage', () => {
  beforeEach(() => mockNavigate.mockReset())

  it('renders one experiment by default after options load', async () => {
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    expect(screen.getByText('Experiments (1)')).toBeInTheDocument()
  })

  it('adds an experiment', async () => {
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await user.click(screen.getByRole('button', { name: /Add experiment/ }))
    expect(screen.getByText('Experiments (2)')).toBeInTheDocument()
  })

  it('duplicates an experiment', async () => {
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await user.click(screen.getAllByTitle('Duplicate')[0])
    expect(screen.getByText('Experiments (2)')).toBeInTheDocument()
  })

  it('removes an experiment (and keeps at least one)', async () => {
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await user.click(screen.getByRole('button', { name: /Add experiment/ }))
    expect(screen.getByText('Experiments (2)')).toBeInTheDocument()
    await user.click(screen.getAllByTitle('Remove')[0])
    expect(screen.getByText('Experiments (1)')).toBeInTheDocument()
  })

  it('disables submit until a contract is uploaded', async () => {
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    expect(screen.getByRole('button', { name: /Run 1 experiment/ })).toBeDisabled()
  })

  it('submits the suite and forwards warnings via navigation state', async () => {
    server.use(
      http.post('/api/suites', () =>
        HttpResponse.json({ run_id: TEST_RUN_ID, warnings: ['zero-shot: temperature ignored'] })
      )
    )
    const { container } = renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await uploadContract(container)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Run 1 experiment/ })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith(`/suites/${TEST_RUN_ID}`, {
        state: { warnings: ['zero-shot: temperature ignored'] },
      })
    )
  })

  it('shows an error alert when submission fails', async () => {
    server.use(
      http.post('/api/suites', () =>
        HttpResponse.json({ detail: 'experiment names must be unique' }, { status: 422 })
      )
    )
    const { container } = renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await uploadContract(container)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Run 1 experiment/ })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await screen.findByText('experiment names must be unique')
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('sends the contract and one entry per experiment card in the payload', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/suites', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ run_id: TEST_RUN_ID })
      })
    )
    const user = userEvent.setup()
    const { container } = renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await user.click(screen.getByRole('button', { name: /Add experiment/ }))
    await uploadContract(container, 'My legal contract')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Run 2 experiments/ })).not.toBeDisabled()
    )

    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => {
      const body = capturedBody as { contract_text: string; experiments: unknown[] }
      expect(body.contract_text).toBe('My legal contract')
      expect(body.experiments).toHaveLength(2)
    })
  })
})
