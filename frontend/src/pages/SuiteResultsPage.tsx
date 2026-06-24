import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { Loader2, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { CandidateItem } from '@/components/results/CandidateItem'
import { triggerDownload } from '@/components/results/download'
import { useSuiteStream } from '@/hooks/useSuiteStream'
import { formatProgressLabel } from '@/lib/progress'
import { formatCost, formatTokens } from '@/lib/tokens'
import type { ExperimentResult, SuiteResult } from '@/api/types'

// Warnings forwarded from the experiments form via navigation state (see
// ExperimentsPage). Transient — lost on a hard refresh, by design.
type SuiteNavState = { warnings?: string[] } | null

export default function SuiteResultsPage() {
  const { suiteId } = useParams<{ suiteId: string }>()
  const navigate = useNavigate()
  const { state } = useLocation()
  const { status, progress, result, errorMessage } = useSuiteStream(suiteId!)

  const warnings = (state as SuiteNavState)?.warnings ?? []

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">Suite Results</h1>
        <Button variant="outline" onClick={() => navigate('/experiments')}>
          New Suite
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

      {(status === 'connecting' || status === 'running' || status === 'reconnecting') && (
        <div className="flex items-center justify-center gap-3 py-16 text-muted-foreground">
          <Loader2 className="animate-spin" size={20} />
          <span>
            {status === 'reconnecting'
              ? 'Connection dropped — retrying...'
              : progress
              ? formatProgressLabel(progress)
              : 'Connecting...'}
          </span>
        </div>
      )}

      {status === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage ?? 'An unknown error occurred.'}</AlertDescription>
        </Alert>
      )}

      {status === 'complete' && result && <SuiteView result={result} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SuiteView — comparison rows (each expandable into per-candidate detail)
// ---------------------------------------------------------------------------

function SuiteView({ result }: { result: SuiteResult }) {
  const convergedCount = result.experiments.filter(e => e.result.success).length

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            {convergedCount} of {result.experiments.length} experiments converged.
          </p>
          <p className="text-xs text-muted-foreground">
            Suite total: {formatTokens(result.total_tokens)} tokens ·{' '}
            {formatCost(result.total_cost_usd)}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => triggerDownload(buildSummaryCsv(result), 'suite_summary.csv', 'text/csv')}
        >
          <Download size={14} /> Download CSV
        </Button>
      </div>

      <Accordion type="multiple" className="space-y-2">
        {result.experiments.map((experiment, index) => (
          <ExperimentRow key={index} index={index} experiment={experiment} />
        ))}
      </Accordion>
    </div>
  )
}

function ExperimentRow({ index, experiment }: { index: number; experiment: ExperimentResult }) {
  const { success, total_tokens, total_cost_usd, iterations_to_convergence } = experiment.result
  const candidates = experiment.result.candidates

  return (
    <AccordionItem value={`experiment-${index}`} className="border rounded-lg px-4">
      <AccordionTrigger className="hover:no-underline">
        <div className="flex items-center gap-3">
          <span className="font-medium">{experiment.name}</span>
          <Badge variant={success ? 'default' : 'destructive'}>
            {success ? 'Converged' : 'Failed to converge'}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {iterations_to_convergence !== null
              ? `${iterations_to_convergence} iteration${iterations_to_convergence !== 1 ? 's' : ''}`
              : '—'}
          </span>
          <span className="text-xs text-muted-foreground">
            {formatTokens(total_tokens)} tokens · {formatCost(total_cost_usd)}
          </span>
        </div>
      </AccordionTrigger>
      <AccordionContent className="pb-4">
        <Accordion type="multiple" className="space-y-2">
          {candidates.map(candidate => (
            <CandidateItem key={candidate.candidate_id} candidate={candidate} />
          ))}
        </Accordion>
      </AccordionContent>
    </AccordionItem>
  )
}

// ---------------------------------------------------------------------------
// Summary CSV — built from the result models' computed rollups
// ---------------------------------------------------------------------------

function buildSummaryCsv(result: SuiteResult): string {
  const header = 'experiment,converged,iterations_to_convergence,total_tokens,cost_usd'
  const rows = result.experiments.map(exp => {
    const { success, iterations_to_convergence, total_tokens, total_cost_usd } = exp.result
    return [
      csvCell(exp.name),
      success,
      iterations_to_convergence ?? '',
      total_tokens,
      total_cost_usd ?? '',
    ].join(',')
  })
  return [header, ...rows].join('\n')
}

function csvCell(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}
