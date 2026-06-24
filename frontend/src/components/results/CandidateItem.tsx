import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { triggerDownload } from '@/components/results/download'
import { formatCost, formatTokens } from '@/lib/tokens'
import type { CandidateResult } from '@/api/types'

// One candidate's result, rendered as an accordion item. Shared by the
// single-run results page and each experiment's detail in a suite.
export function CandidateItem({ candidate }: { candidate: CandidateResult }) {
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
          <span className="text-xs text-muted-foreground">
            {formatTokens(candidate.total_tokens)} tokens ·{' '}
            {formatCost(candidate.total_cost_usd)}
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
