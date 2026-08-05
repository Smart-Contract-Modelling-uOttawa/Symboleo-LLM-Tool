import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import { Accordion } from '@/components/ui/accordion'
import { CandidateItem } from '@/components/results/CandidateItem'
import { useStream } from '@/hooks/useStream'
import { useRunCancel } from '@/hooks/useRunCancel'
import { formatProgressLabel } from '@/lib/progress'
import type { PipelineResult } from '@/api/types'

// ---------------------------------------------------------------------------
// ResultsPage
// ---------------------------------------------------------------------------

// Advisory warnings forwarded by the config form via navigation state (see
// ConfigPage handleSubmit). Lost on a hard refresh by design — they are a
// transient, submit-time notice, not run state.
type ResultsNavState = { warnings?: string[] } | null

export default function ResultsPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const { state } = useLocation()
  const { status, progress, result, errorMessage, outputDir, writeError } = useStream(runId!)
  const isRunning = status === 'connecting' || status === 'running' || status === 'reconnecting'
  const { stopping, stop } = useRunCancel(runId!, isRunning)

  const warnings = (state as ResultsNavState)?.warnings ?? []

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">Results</h1>
        <Button variant="outline" onClick={() => navigate('/')}>
          New Run
        </Button>
      </div>

      {warnings.length > 0 && (
        <Alert variant="warning" className="mb-6">
          <AlertTitle>Configuration warnings</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4 space-y-1">
              {warnings.map(warning => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {isRunning && (
        <div className="flex flex-col items-center gap-4 py-16">
          <div className="flex items-center gap-3 text-muted-foreground">
            <Loader2 className="animate-spin" size={20} />
            <span>
              {status === 'reconnecting'
                ? 'Connection dropped — retrying...'
                : progress
                ? formatProgressLabel(progress)
                : 'Connecting...'}
            </span>
          </div>
          <Button variant="outline" size="sm" onClick={stop} disabled={stopping}>
            {stopping ? 'Stopping…' : 'Stop'}
          </Button>
        </div>
      )}

      {status === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage ?? 'An unknown error occurred.'}</AlertDescription>
        </Alert>
      )}

      {status === 'complete' && result && (
        <>
          {stopping && (
            <Alert className="mb-4">
              <AlertDescription>Run stopped — showing partial results.</AlertDescription>
            </Alert>
          )}
          {writeError && (
            <Alert variant="warning" className="mb-4">
              <AlertTitle>Results were not saved</AlertTitle>
              {/* Shown in full — an undisplayed write failure is silent artifact loss. */}
              <AlertDescription>{writeError}</AlertDescription>
            </Alert>
          )}
          <ResultsView result={result} />
          {outputDir && (
            <p className="mt-6 text-xs text-muted-foreground">Saved to {outputDir}</p>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResultsView
// ---------------------------------------------------------------------------

function ResultsView({ result }: { result: PipelineResult }) {
  const defaultOpen = result.candidates.map(c => `candidate-${c.candidate_id}`)

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {result.success
          ? 'At least one candidate converged.'
          : 'No candidates converged.'}
      </p>
      <Accordion type="multiple" defaultValue={defaultOpen} className="space-y-2">
        {result.candidates.map(candidate => (
          <CandidateItem key={candidate.candidate_id} candidate={candidate} />
        ))}
      </Accordion>
    </div>
  )
}
