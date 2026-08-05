// Label the live progress counter from a stream event.
//
// A progress event fires AFTER an iteration validates, so iteration 0 is the
// *completed* generation pass ("Generated", not "Generating"), then 1..max for
// each correction. The label must NOT add 1 (that overshot max_iterations,
// e.g. showing "Iteration 4" for a 3-iteration run).
function formatIterationLabel(iteration: number): string {
  return iteration === 0 ? 'Generated' : `Iteration ${iteration}`
}

// errorCount counts blocking errors only (the count that gates convergence);
// zero reads as "converged", mirroring the CLI's progress line.
function formatErrorCount(errorCount: number): string {
  return errorCount === 0 ? 'converged' : `${errorCount} error${errorCount !== 1 ? 's' : ''}`
}

// Full "[Experiment N — ]Candidate N — <phase> — <errors>" counter for the
// results pages. experimentIndex is absent for a single run and set within a
// suite. Structural param so both the single-run and suite progress shapes can
// pass through.
export function formatProgressLabel(progress: {
  experimentIndex?: number | null
  candidateId: number
  iteration: number
  errorCount: number
}): string {
  const parts: string[] = []
  if (progress.experimentIndex != null) {
    parts.push(`Experiment ${progress.experimentIndex + 1}`)
  }
  parts.push(`Candidate ${progress.candidateId + 1}`)
  parts.push(formatIterationLabel(progress.iteration))
  parts.push(formatErrorCount(progress.errorCount))
  return parts.join(' — ')
}
