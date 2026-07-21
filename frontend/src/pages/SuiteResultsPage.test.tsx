import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi } from 'vitest'
import { useSuiteStream } from '@/hooks/useSuiteStream'
import { triggerDownload } from '@/components/results/download'
import { cancelRun } from '@/api/client'
import SuiteResultsPage from './SuiteResultsPage'
import type { PipelineResult, SuiteResult } from '@/api/types'

vi.mock('@/hooks/useSuiteStream')
const mockUseSuiteStream = vi.mocked(useSuiteStream)

vi.mock('@/components/results/download', () => ({ triggerDownload: vi.fn() }))
const mockTriggerDownload = vi.mocked(triggerDownload)

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, cancelRun: vi.fn() }
})
const mockCancelRun = vi.mocked(cancelRun)

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const TEST_SUITE_ID = 'test-suite-id'

type Totals = { tokens: number; cost: number | null }

// Token/cost totals and iterations_to_convergence are computed_fields on the
// backend models, so they arrive as authoritative values — the page reads them
// directly rather than re-deriving from error_history.
function pipelineResult(
  converged: boolean,
  iterations: number,
  totals: Totals = { tokens: 0, cost: null },
): PipelineResult {
  return {
    success: converged,
    timestamp: '2026-01-01T00:00:00',
    input_file: '',
    total_tokens: totals.tokens,
    total_cost_usd: totals.cost,
    iterations_to_convergence: converged ? iterations : null,
    candidates: [
      {
        candidate_id: 0,
        final_code: 'Contract C() {}',
        converged,
        iterations_used: iterations,
        error_history: [],
        total_tokens: totals.tokens,
        total_cost_usd: totals.cost,
      },
    ],
  }
}

const MOCK_SUITE_RESULT: SuiteResult = {
  timestamp: '2026-01-01T00:00:00',
  input_file: '',
  total_tokens: 3500,
  total_cost_usd: 0.007,
  experiments: [
    { name: 'zero-shot', result: pipelineResult(true, 2, { tokens: 1500, cost: 0.003 }) },
    { name: 'cot', result: pipelineResult(false, 3, { tokens: 2000, cost: 0.004 }) },
  ],
}

function renderSuiteResultsPage(warnings?: string[]) {
  const entry = warnings
    ? { pathname: `/suites/${TEST_SUITE_ID}`, state: { warnings } }
    : `/suites/${TEST_SUITE_ID}`
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/suites/:suiteId" element={<SuiteResultsPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('SuiteResultsPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    mockUseSuiteStream.mockReset()
    mockTriggerDownload.mockReset()
    mockCancelRun.mockReset()
  })

  // Each experiment's accordion trigger carries its own badge/iterations/tokens,
  // so assertions are scoped to a row — a page-wide getByText would still pass
  // with the values swapped between experiments.
  const row = (label: RegExp) => screen.getByRole('button', { name: label })

  it('shows "Connecting..." on initial load', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
  })

  it('shows the experiment/candidate/iteration counter from a progress event', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 1, candidateId: 0, iteration: 2 },
      result: null,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Experiment 2 — Candidate 1 — Iteration 2')).toBeInTheDocument()
  })

  it('shows an error alert with the error message from the stream', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'error',
      progress: null,
      result: null,
      errorMessage: 'Suite failed unexpectedly',
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Suite failed unexpectedly')).toBeInTheDocument()
  })

  it('renders comparison rows and the converged summary on completion', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('1 of 2 experiments converged.')).toBeInTheDocument()
    expect(screen.getByText('zero-shot')).toBeInTheDocument()
    expect(screen.getByText('cot')).toBeInTheDocument()
  })

  it('shows converged/failed badges and iterations per experiment', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    const convergedRow = row(/^zero-shot/)
    const failedRow = row(/^cot/)
    expect(within(convergedRow).getByText('Converged')).toBeInTheDocument()
    expect(within(failedRow).getByText('Failed to converge')).toBeInTheDocument()
    // converged experiment shows its iteration count; the failed one shows a dash
    expect(within(convergedRow).getByText('2 iterations')).toBeInTheDocument()
    expect(within(failedRow).getByText('—')).toBeInTheDocument()
  })

  it('shows per-experiment token totals and cost', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    expect(within(row(/^zero-shot/)).getByText('1,500 tokens · $0.0030')).toBeInTheDocument()
    expect(within(row(/^cot/)).getByText('2,000 tokens · $0.0040')).toBeInTheDocument()
  })

  it('shows the suite-wide token and cost total', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Suite total: 3,500 tokens · $0.0070')).toBeInTheDocument()
  })

  it('includes token and cost columns in the summary CSV', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: /Download CSV/ }))

    const csv = mockTriggerDownload.mock.calls[0][0] as string
    expect(csv).toContain('experiment,converged,iterations_to_convergence,total_tokens,cost_usd')
    expect(csv).toContain('zero-shot,true,2,1500,')
    expect(csv).toContain('cot,false,,2000,')
  })

  it('renders configuration warnings forwarded via navigation state', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderSuiteResultsPage(['zero-shot: temperature ignored'])
    expect(screen.getByText('Configuration warnings')).toBeInTheDocument()
    expect(screen.getByText(/temperature ignored/)).toBeInTheDocument()
  })

  it('shows a Stop button while running and switches to Stopping when clicked', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 0, candidateId: 0, iteration: 1 },
      result: null,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    // The backend call is the point of the button; the label flip alone would
    // still pass with the cancel request removed.
    expect(mockCancelRun).toHaveBeenCalledWith(TEST_SUITE_ID)
    expect(screen.getByRole('button', { name: /Stopping/ })).toBeInTheDocument()
  })

  it('navigates to /experiments when New Suite is clicked', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: 'New Suite' }))
    expect(mockNavigate).toHaveBeenCalledWith('/experiments')
  })
})
