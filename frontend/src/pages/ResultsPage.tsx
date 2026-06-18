import { useParams, useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { useStream } from '@/hooks/useStream'
import type { CandidateResult, PipelineResult } from '@/api/types'

// ---------------------------------------------------------------------------
// ResultsPage
// ---------------------------------------------------------------------------

export default function ResultsPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const { status, progress, result, errorMessage } = useStream(runId!)

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">Results</h1>
        <Button variant="outline" onClick={() => navigate('/')}>
          New Run
        </Button>
      </div>

      {(status === 'connecting' || status === 'running') && (
        <div className="flex items-center justify-center gap-3 py-16 text-muted-foreground">
          <Loader2 className="animate-spin" size={20} />
          <span>
            {progress
              ? `Candidate ${progress.candidateId + 1} — Iteration ${progress.iteration + 1}`
              : 'Connecting...'}
          </span>
        </div>
      )}

      {status === 'error' && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage ?? 'An unknown error occurred.'}</AlertDescription>
        </Alert>
      )}

      {status === 'complete' && result && <ResultsView result={result} />}
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

// ---------------------------------------------------------------------------
// CandidateItem
// ---------------------------------------------------------------------------

function CandidateItem({ candidate }: { candidate: CandidateResult }) {
  function downloadSl() {
    triggerDownload(
      candidate.final_code,
      `candidate_${candidate.candidate_id}.symboleo`,
      'text/plain',
    )
  }

  function downloadReport() {
    triggerDownload(
      JSON.stringify(candidate, null, 2),
      `candidate_${candidate.candidate_id}_report.json`,
      'application/json',
    )
  }

  return (
    <AccordionItem
      value={`candidate-${candidate.candidate_id}`}
      className="border rounded-lg px-4"
    >
      <AccordionTrigger className="hover:no-underline">
        <div className="flex items-center gap-3">
          <span className="font-medium">
            Candidate {candidate.candidate_id + 1}
          </span>
          <Badge variant={candidate.converged ? 'default' : 'destructive'}>
            {candidate.converged ? 'Converged' : 'Failed to converge'}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {candidate.iterations_used} iteration
            {candidate.iterations_used !== 1 ? 's' : ''}
          </span>
        </div>
      </AccordionTrigger>
      <AccordionContent className="space-y-4 pb-4">
        <pre className="text-xs font-mono bg-muted p-3 rounded-md overflow-auto max-h-96 whitespace-pre-wrap break-words">
          {candidate.final_code}
        </pre>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={downloadSl}>
            Download .symboleo
          </Button>
          <Button size="sm" variant="outline" onClick={downloadReport}>
            Download report.json
          </Button>
        </div>
      </AccordionContent>
    </AccordionItem>
  )
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function triggerDownload(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
