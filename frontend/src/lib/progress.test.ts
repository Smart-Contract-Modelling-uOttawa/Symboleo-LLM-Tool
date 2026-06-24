import { describe, it, expect } from 'vitest'
import { formatProgressLabel } from './progress'

describe('formatProgressLabel', () => {
  it('labels iteration 0 as the generation phase, not Iteration 1', () => {
    expect(formatProgressLabel({ candidateId: 0, iteration: 0 })).toBe(
      'Candidate 1 — Generating...',
    )
  })

  it('labels correction iterations without adding 1', () => {
    // iteration 3 of a max_iterations=3 run must read "Iteration 3", not "Iteration 4".
    expect(formatProgressLabel({ candidateId: 0, iteration: 3 })).toBe(
      'Candidate 1 — Iteration 3',
    )
  })

  it('includes the experiment prefix when experimentIndex is set', () => {
    expect(formatProgressLabel({ experimentIndex: 1, candidateId: 0, iteration: 2 })).toBe(
      'Experiment 2 — Candidate 1 — Iteration 2',
    )
  })

  it('omits the experiment prefix when experimentIndex is null', () => {
    expect(formatProgressLabel({ experimentIndex: null, candidateId: 1, iteration: 1 })).toBe(
      'Candidate 2 — Iteration 1',
    )
  })
})
