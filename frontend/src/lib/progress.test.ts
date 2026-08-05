import { describe, it, expect } from 'vitest'
import { formatProgressLabel } from './progress'

describe('formatProgressLabel', () => {
  it('labels iteration 0 as the completed generation pass, not Iteration 1', () => {
    // The event fires after generation validates, so "Generated", and the
    // count is the draft's blocking errors.
    expect(formatProgressLabel({ candidateId: 0, iteration: 0, errorCount: 13 })).toBe(
      'Candidate 1 — Generated — 13 errors',
    )
  })

  it('labels correction iterations without adding 1', () => {
    // iteration 3 of a max_iterations=3 run must read "Iteration 3", not "Iteration 4".
    expect(formatProgressLabel({ candidateId: 0, iteration: 3, errorCount: 4 })).toBe(
      'Candidate 1 — Iteration 3 — 4 errors',
    )
  })

  it('uses the singular for exactly one error', () => {
    expect(formatProgressLabel({ candidateId: 0, iteration: 1, errorCount: 1 })).toBe(
      'Candidate 1 — Iteration 1 — 1 error',
    )
  })

  it('reads "converged" when no blocking errors remain', () => {
    expect(formatProgressLabel({ candidateId: 0, iteration: 2, errorCount: 0 })).toBe(
      'Candidate 1 — Iteration 2 — converged',
    )
  })

  it('includes the experiment prefix when experimentIndex is set', () => {
    expect(
      formatProgressLabel({ experimentIndex: 1, candidateId: 0, iteration: 2, errorCount: 4 }),
    ).toBe('Experiment 2 — Candidate 1 — Iteration 2 — 4 errors')
  })

  it('omits the experiment prefix when experimentIndex is null', () => {
    expect(
      formatProgressLabel({ experimentIndex: null, candidateId: 1, iteration: 1, errorCount: 2 }),
    ).toBe('Candidate 2 — Iteration 1 — 2 errors')
  })
})
