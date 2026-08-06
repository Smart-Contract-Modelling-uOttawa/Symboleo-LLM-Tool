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
            {candidate.converged
              ? 'Converged'
              : // "Failed to converge" implies the loop ran its course; a
                // candidate with a failure was cut short by a failed call.
                candidate.failure
                ? 'Cut short'
                : 'Failed to converge'}
          </Badge>
          {candidate.final_error_count > 0 && (
            // Keyed on the count, not on !converged: a run cancelled before
            // its first validation has no count to show.
            <Badge variant="outline" className="text-destructive font-normal">
              {candidate.final_error_count} error
              {candidate.final_error_count !== 1 ? 's' : ''}
            </Badge>
          )}
          {candidate.final_warning_count > 0 && (
            // Warnings surface but never block: "Converged" can legitimately
            // sit beside lingering stylistic warnings.
            <Badge variant="outline" className="text-muted-foreground font-normal">
              {candidate.final_warning_count} warning
              {candidate.final_warning_count !== 1 ? 's' : ''}
            </Badge>
          )}
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
        {candidate.failure && (
          // The badge names the state; this line is the only place naming the cause.
          <p className="text-sm text-destructive">
            Cut short by a failed call: {candidate.failure}
          </p>
        )}
        {candidate.final_code && (
          <pre className="text-xs font-mono bg-muted p-3 rounded-md overflow-auto max-h-96 whitespace-pre-wrap break-words">
            {candidate.final_code}
          </pre>
        )}
        <div className="flex gap-2">
          {/* Same guard as the writer's: a cut-short candidate has no code, and
              a 0-byte .symboleo in a folder of contracts reads as one. */}
          {candidate.final_code && (
            <Button size="sm" variant="outline" onClick={downloadSl}>
              Download .symboleo
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={downloadReport}>
            Download report.json
          </Button>
        </div>
      </AccordionContent>
    </AccordionItem>
  )
}
