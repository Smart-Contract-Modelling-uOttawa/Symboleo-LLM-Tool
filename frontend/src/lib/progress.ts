// Label the live progress counter from a stream event.
//
// The pipeline emits iteration 0 for the initial generation, then 1..max for
// each correction. So the label must NOT add 1 (that overshot max_iterations,
// e.g. showing "Iteration 4" for a 3-iteration run) and iteration 0 is the
// generation phase, not "Iteration 1".
function formatIterationLabel(iteration: number): string {
  return iteration === 0 ? 'Generating...' : `Iteration ${iteration}`
}

// Full "[Experiment N — ]Candidate N — <phase>" counter for the results pages.
// experimentIndex is absent for a single run and set within a suite. Structural
// param so both the single-run and suite progress shapes can pass through.
export function formatProgressLabel(progress: {
  experimentIndex?: number | null
  candidateId: number
  iteration: number
}): string {
  const parts: string[] = []
  if (progress.experimentIndex != null) {
    parts.push(`Experiment ${progress.experimentIndex + 1}`)
  }
  parts.push(`Candidate ${progress.candidateId + 1}`)
  parts.push(formatIterationLabel(progress.iteration))
  return parts.join(' — ')
}
