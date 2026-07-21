import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { vi } from 'vitest'
import { server } from '@/test/server'
import { TEST_RUN_ID } from '@/test/handlers'
import ExperimentsPage from './ExperimentsPage'

const mockNavigate = vi.hoisted(() => vi.fn())
const mockTriggerDownload = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

vi.mock('@/components/results/download', () => ({ triggerDownload: mockTriggerDownload }))

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
  beforeEach(() => {
    mockNavigate.mockReset()
    mockTriggerDownload.mockReset()
  })

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

  it('generates one experiment per selected axis value via the expander', async () => {
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')

    // Strategy is the default axis; few_shot is excluded, leaving zero_shot + cot.
    const expander = screen.getByRole('group', { name: 'Generate variants' })
    await user.click(within(expander).getByRole('button', { name: 'zero_shot' }))
    await user.click(within(expander).getByRole('button', { name: 'cot' }))
    await user.click(within(expander).getByRole('button', { name: /Generate/ }))

    // 1 base experiment + 2 generated variants
    expect(screen.getByText('Experiments (3)')).toBeInTheDocument()
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

  it('downloads the suite config the server builds', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/suites/export', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ filename: 'suite.yaml', content: 'experiments:\n  - name: x\n' })
      })
    )
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')
    await user.click(screen.getByRole('button', { name: /Add experiment/ }))

    await user.click(screen.getByRole('button', { name: /Download suite config/ }))

    await waitFor(() =>
      expect(mockTriggerDownload).toHaveBeenCalledWith(
        'experiments:\n  - name: x\n',
        'suite.yaml',
        'application/yaml',
      )
    )
    // One entry per card, and no contract: the file is a config, and the loader
    // rejects a contract_text key outright.
    const body = capturedBody as { experiments: unknown[]; contract_text?: string }
    expect(body.experiments).toHaveLength(2)
    expect(body.contract_text).toBeUndefined()
    // A type="submit" button here would run the suite instead of exporting it.
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('allows downloading the config before a contract is chosen', async () => {
    // The contract is a CLI argument, not part of the file, so export must not
    // inherit the Run button's disabled-until-uploaded rule.
    server.use(
      http.post('/api/suites/export', () =>
        HttpResponse.json({ filename: 'suite.yaml', content: 'experiments: []\n' })
      )
    )
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')

    expect(screen.getByRole('button', { name: /Run 1 experiment/ })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Download suite config/ }))

    await waitFor(() => expect(mockTriggerDownload).toHaveBeenCalled())
  })

  it('surfaces export warnings without blocking the download', async () => {
    server.use(
      http.post('/api/suites/export', () =>
        HttpResponse.json({
          filename: 'suite.yaml',
          content: 'experiments: []\n',
          warnings: ['haiku: temperature=0.7 is set, but it is a reasoning model'],
        })
      )
    )
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')

    await user.click(screen.getByRole('button', { name: /Download suite config/ }))

    // The file is valid — the warning is about a param the model rejects at run
    // time, so it must not suppress the download.
    await screen.findByText(/temperature=0.7 is set/)
    expect(mockTriggerDownload).toHaveBeenCalled()
  })

  it('shows an error alert when the export fails', async () => {
    server.use(
      http.post('/api/suites/export', () =>
        HttpResponse.json({ detail: 'Unknown model: gpt-9-ultra' }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    renderExperimentsPage()
    await screen.findByText('Experiment Suite')

    await user.click(screen.getByRole('button', { name: /Download suite config/ }))

    await screen.findByText('Unknown model: gpt-9-ultra')
    expect(mockTriggerDownload).not.toHaveBeenCalled()
  })

  it('defaults the concurrency control and includes the edited value in the payload', async () => {
    let capturedBody: unknown
    server.use(
      http.post('/api/suites', async ({ request }) => {
        capturedBody = await request.json()
        return HttpResponse.json({ run_id: TEST_RUN_ID })
      })
    )
    const { container } = renderExperimentsPage()
    await screen.findByText('Experiment Suite')

    const concurrency = screen.getByLabelText('Concurrency') as HTMLInputElement
    expect(concurrency.value).toBe('2') // DEFAULTS fallback (mock options have no params)
    fireEvent.change(concurrency, { target: { value: '4' } })

    await uploadContract(container, 'My contract')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Run 1 experiment/ })).not.toBeDisabled()
    )
    fireEvent.submit(container.querySelector('form') as HTMLFormElement)

    await waitFor(() => {
      expect((capturedBody as { max_concurrency: number }).max_concurrency).toBe(4)
    })
  })
})
