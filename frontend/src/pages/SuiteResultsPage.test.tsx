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

// The backend exposes its rollups as computed_fields, so they arrive as
// authoritative values — the page reads them directly rather than re-deriving
// from error_history. `splits` gives each
// experiment two candidates whose totals sum to the experiment's without
// matching it, so a page reading candidate-level rollups instead of the
// experiment's own field fails.
function pipelineResult(
  converged: boolean,
  iterations: number,
  totals: Totals,
  splits: Totals[],
): PipelineResult {
  return {
    success: converged,
    timestamp: '2026-01-01T00:00:00',
    input_file: '',
    total_tokens: totals.tokens,
    total_cost_usd: totals.cost,
    iterations_to_convergence: converged ? iterations : null,
    failed_candidate_count: 0,
    candidates: splits.map((split, index) => ({
      candidate_id: index,
      final_code: 'Contract C() {}',
      converged,
      iterations_used: iterations,
      error_history: [],
      total_tokens: split.tokens,
      total_cost_usd: split.cost,
      final_error_count: converged ? 0 : 3,
      final_warning_count: 0,
    })),
  }
}

const MOCK_SUITE_RESULT: SuiteResult = {
  timestamp: '2026-01-01T00:00:00',
  input_file: '',
  total_tokens: 3500,
  total_cost_usd: 0.007,
  experiments: [
    {
      name: 'zero-shot',
      result: pipelineResult(true, 2, { tokens: 1500, cost: 0.003 }, [
        { tokens: 900, cost: 0.002 },
        { tokens: 600, cost: 0.001 },
      ]),
    },
    {
      name: 'cot',
      result: pipelineResult(false, 3, { tokens: 2000, cost: 0.004 }, [
        { tokens: 1200, cost: 0.0025 },
        { tokens: 800, cost: 0.0015 },
      ]),
    },
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
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
  })

  it('shows the experiment/candidate/iteration/error counter from a progress event', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 1, candidateId: 0, iteration: 2, errorCount: 4 },
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    expect(
      screen.getByText('Experiment 2 — Candidate 1 — Iteration 2 — 4 errors')
    ).toBeInTheDocument()
  })

  it('shows an error alert with the error message from the stream', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'error',
      progress: null,
      result: null,
      errorMessage: 'Suite failed unexpectedly',
      outputDir: null,
      writeError: null,
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
      outputDir: null,
      writeError: null,
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
      outputDir: null,
      writeError: null,
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
      outputDir: null,
      writeError: null,
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
      outputDir: null,
      writeError: null,
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
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: /Download CSV/ }))

    const rows = (mockTriggerDownload.mock.calls[0][0] as string).split('\n')
    expect(rows[0]).toBe(
      'experiment,converged,iterations_to_convergence,failed_candidates,total_tokens,cost_usd'
    )
    // Full rows, so the cost column and the column order are both pinned — a
    // trailing-comma prefix match left the cost cell free to be anything.
    expect(rows[1]).toBe('zero-shot,true,2,0,1500,0.003')
    // Not converged → empty iterations cell, and the experiment's own totals
    // (2000/0.004), not either candidate's.
    expect(rows[2]).toBe('cot,false,,0,2000,0.004')
  })

  it('shows where the server saved the suite', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
      outputDir: 'output/suite_20260101_120000',
      writeError: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Saved to output/suite_20260101_120000')).toBeInTheDocument()
    expect(screen.queryByText('Results were not saved')).not.toBeInTheDocument()
  })

  it('still shows the comparison when the server could not write it to disk', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
      outputDir: null,
      writeError: 'Results were not written to disk: disk full',
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Results were not saved')).toBeInTheDocument()
    expect(screen.getByText('Results were not written to disk: disk full')).toBeInTheDocument()
    expect(screen.getByText('zero-shot')).toBeInTheDocument()
    expect(screen.queryByText(/Saved to/)).not.toBeInTheDocument()
  })

  it('renders configuration warnings forwarded via navigation state', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage(['zero-shot: temperature ignored'])
    expect(screen.getByText('Configuration warnings')).toBeInTheDocument()
    expect(screen.getByText(/temperature ignored/)).toBeInTheDocument()
  })

  it('shows a Stop button while running and switches to Stopping when clicked', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 0, candidateId: 0, iteration: 1, errorCount: 2 },
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    // The backend call is the point of the button; the label flip alone would
    // still pass with the cancel request removed.
    expect(mockCancelRun).toHaveBeenCalledWith(TEST_SUITE_ID)
    expect(screen.getByRole('button', { name: /Stopping/ })).toBeInTheDocument()
  })

  it('tells the user the browser is retrying a dropped connection', () => {
    mockUseSuiteStream.mockReturnValue({
      status: 'reconnecting',
      progress: { experimentIndex: 0, candidateId: 0, iteration: 1, errorCount: 2 },
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    expect(screen.getByText('Connection dropped — retrying...')).toBeInTheDocument()
    expect(
      screen.queryByText('Experiment 1 — Candidate 1 — Iteration 1 — 2 errors')
    ).not.toBeInTheDocument()
  })

  it('flags the results as partial once a stopped suite completes', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'running',
      progress: { experimentIndex: 0, candidateId: 0, iteration: 1, errorCount: 2 },
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    // Clicking Stop re-renders, by which point the stream has completed.
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_SUITE_RESULT,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    await user.click(screen.getByRole('button', { name: 'Stop' }))

    expect(screen.getByText('Suite stopped — showing partial results.')).toBeInTheDocument()
  })

  it('quotes an experiment name containing a comma so the CSV stays parseable', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: {
        ...MOCK_SUITE_RESULT,
        // Experiment names are free text, and the axis expander encourages
        // descriptive ones — an unescaped comma would shift every later column.
        experiments: [
          { name: 'zero-shot, temp 0.2', result: MOCK_SUITE_RESULT.experiments[0].result },
        ],
      },
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: /Download CSV/ }))

    const rows = (mockTriggerDownload.mock.calls[0][0] as string).split('\n')
    expect(rows[1]).toBe('"zero-shot, temp 0.2",true,2,0,1500,0.003')
  })

  it('navigates to /experiments when New Suite is clicked', async () => {
    const user = userEvent.setup()
    mockUseSuiteStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
      outputDir: null,
      writeError: null,
    })
    renderSuiteResultsPage()
    await user.click(screen.getByRole('button', { name: 'New Suite' }))
    expect(mockNavigate).toHaveBeenCalledWith('/experiments')
  })
})
