import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi } from 'vitest'
import { TEST_RUN_ID } from '@/test/handlers'
import { useStream } from '@/hooks/useStream'
import ResultsPage from './ResultsPage'
import type { PipelineResult } from '@/api/types'

vi.mock('@/hooks/useStream')
const mockUseStream = vi.mocked(useStream)

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const MOCK_RESULT: PipelineResult = {
  success: true,
  timestamp: '2026-01-01T00:00:00',
  input_file: 'contract.txt',
  total_tokens: 2300,
  total_cost_usd: 0.003,
  iterations_to_convergence: 2,
  candidates: [
    {
      candidate_id: 0,
      final_code: 'Contract Test() {}',
      converged: true,
      iterations_used: 2,
      error_history: [],
      total_tokens: 1500,
      total_cost_usd: 0.003,
    },
    {
      candidate_id: 1,
      final_code: 'Contract Broken() {}',
      converged: false,
      iterations_used: 3,
      error_history: [],
      total_tokens: 800,
      total_cost_usd: null,
    },
  ],
}

function renderResultsPage(warnings?: string[]) {
  const entry = warnings
    ? { pathname: `/runs/${TEST_RUN_ID}`, state: { warnings } }
    : `/runs/${TEST_RUN_ID}`
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/runs/:runId" element={<ResultsPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('ResultsPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    mockUseStream.mockReset()
  })

  it('shows "Connecting..." on initial load', () => {
    mockUseStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
  })

  it('shows candidate and iteration counter from a progress event', () => {
    mockUseStream.mockReturnValue({
      status: 'running',
      progress: { candidateId: 0, iteration: 2 },
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    // iteration 2 is the 2nd correction — not "Iteration 3" (no +1; that
    // overshot max_iterations). See lib/progress.
    expect(screen.getByText('Candidate 1 — Iteration 2')).toBeInTheDocument()
  })

  it('labels the generation pass (iteration 0) as generating, not Iteration 1', () => {
    mockUseStream.mockReturnValue({
      status: 'running',
      progress: { candidateId: 0, iteration: 0 },
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('Candidate 1 — Generating...')).toBeInTheDocument()
  })

  it('shows an error alert with the error message from the stream', () => {
    mockUseStream.mockReturnValue({
      status: 'error',
      progress: null,
      result: null,
      errorMessage: 'Pipeline failed unexpectedly',
    })
    renderResultsPage()
    expect(screen.getByText('Pipeline failed unexpectedly')).toBeInTheDocument()
  })

  it('shows a fallback message when errorMessage is null', () => {
    mockUseStream.mockReturnValue({
      status: 'error',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('An unknown error occurred.')).toBeInTheDocument()
  })

  it('renders candidate results and convergence summary on completion', () => {
    mockUseStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_RESULT,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('At least one candidate converged.')).toBeInTheDocument()
    expect(screen.getByText('Candidate 1')).toBeInTheDocument()
    expect(screen.getByText('Candidate 2')).toBeInTheDocument()
  })

  it('shows converged and failed-to-converge badges', () => {
    mockUseStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_RESULT,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('Converged')).toBeInTheDocument()
    expect(screen.getByText('Failed to converge')).toBeInTheDocument()
  })

  it('shows "no candidates converged" when success is false', () => {
    mockUseStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: { ...MOCK_RESULT, success: false },
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('No candidates converged.')).toBeInTheDocument()
  })

  it('displays the iterations used per candidate', () => {
    mockUseStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_RESULT,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('2 iterations')).toBeInTheDocument()
    expect(screen.getByText('3 iterations')).toBeInTheDocument()
  })

  it('displays per-candidate token and cost totals (unknown cost as a dash)', () => {
    mockUseStream.mockReturnValue({
      status: 'complete',
      progress: null,
      result: MOCK_RESULT,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.getByText('1,500 tokens · $0.0030')).toBeInTheDocument()
    expect(screen.getByText('800 tokens · —')).toBeInTheDocument()
  })

  it('renders configuration warnings forwarded via navigation state', () => {
    mockUseStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderResultsPage(["generation: temperature=0.2 is set, but 'gpt-5' is a reasoning model"])
    expect(screen.getByText('Configuration warnings')).toBeInTheDocument()
    expect(screen.getByText(/temperature=0.2 is set/)).toBeInTheDocument()
  })

  it('renders no warnings section when none are forwarded', () => {
    mockUseStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    expect(screen.queryByText('Configuration warnings')).not.toBeInTheDocument()
  })

  it('shows a Stop button while running and switches to Stopping when clicked', async () => {
    const user = userEvent.setup()
    mockUseStream.mockReturnValue({
      status: 'running',
      progress: { candidateId: 0, iteration: 1 },
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    expect(screen.getByRole('button', { name: /Stopping/ })).toBeInTheDocument()
  })

  it('navigates to / when New Run is clicked', async () => {
    const user = userEvent.setup()
    mockUseStream.mockReturnValue({
      status: 'connecting',
      progress: null,
      result: null,
      errorMessage: null,
    })
    renderResultsPage()
    await user.click(screen.getByRole('button', { name: 'New Run' }))
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })
})
