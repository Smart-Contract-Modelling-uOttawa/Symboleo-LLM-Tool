import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi } from 'vitest'
import { useSuiteStream } from '@/hooks/useSuiteStream'
import SuiteResultsPage from './SuiteResultsPage'
import type { PipelineResult, SuiteResult } from '@/api/types'

vi.mock('@/hooks/useSuiteStream')
const mockUseSuiteStream = vi.mocked(useSuiteStream)

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const TEST_SUITE_ID = 'test-suite-id'

function pipelineResult(converged: boolean, iterations: number): PipelineResult {
  return {
    success: converged,
    timestamp: '2026-01-01T00:00:00',
    input_file: '',
    candidates: [
      {
        candidate_id: 0,
        final_code: 'Contract C() {}',
        converged,
        iterations_used: iterations,
        error_history: [],
      },
    ],
  }
}

const MOCK_SUITE_RESULT: SuiteResult = {
  timestamp: '2026-01-01T00:00:00',
  input_file: '',
  experiments: [
    { name: 'zero-shot', result: pipelineResult(true, 2) },
    { name: 'cot', result: pipelineResult(false, 3) },
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
  })

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
    expect(screen.getByText('Converged')).toBeInTheDocument()
    expect(screen.getByText('Failed to converge')).toBeInTheDocument()
    // converged experiment shows its iteration count; the failed one shows a dash
    expect(screen.getByText('2 iterations')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
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
