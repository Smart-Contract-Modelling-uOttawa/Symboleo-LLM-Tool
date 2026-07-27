import { useState, useEffect, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ContractUpload } from '@/components/config/ContractUpload'
import { StageSection } from '@/components/config/StageSection'
import { AdvancedSection } from '@/components/config/AdvancedSection'
import {
  type StageFormValues,
  type AdvancedFormValues,
  makeDefaultStage,
  makeDefaultAdvanced,
  makeNullableUpdater,
  buildStageRequest,
  buildAdvancedFields,
} from '@/components/config/stageForm'
import { useOptions } from '@/hooks/useOptions'
import { generate } from '@/api/client'

export default function ConfigPage() {
  const navigate = useNavigate()
  const { options, loading, error: optionsError } = useOptions()

  const [contractText, setContractText] = useState('')
  const [fileName, setFileName] = useState('')
  const [generation, setGeneration] = useState<StageFormValues | null>(null)
  const [correction, setCorrection] = useState<StageFormValues | null>(null)
  const [advanced, setAdvanced] = useState<AdvancedFormValues | null>(null)
  const [generationOpen, setGenerationOpen] = useState(true)
  const [correctionOpen, setCorrectionOpen] = useState(true)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (options && !generation) {
      const defaults = makeDefaultStage(options)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setGeneration(defaults)
      setCorrection(defaults)
      setAdvanced(makeDefaultAdvanced(options))
    }
  }, [options, generation])

  const updateGeneration = makeNullableUpdater<StageFormValues>(setGeneration)
  const updateCorrection = makeNullableUpdater<StageFormValues>(setCorrection)
  const updateAdvanced = makeNullableUpdater<AdvancedFormValues>(setAdvanced)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!contractText || !generation || !correction || !advanced) return
    setSubmitError(null)
    setSubmitting(true)
    try {
      const { run_id, warnings } = await generate({
        contract_text: contractText,
        generation: buildStageRequest(generation),
        correction: buildStageRequest(correction),
        ...buildAdvancedFields(advanced),
      })
      navigate(`/runs/${run_id}`, { state: { warnings: warnings ?? [] } })
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-muted-foreground">
        Loading options...
      </div>
    )
  }

  if (optionsError) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Alert variant="destructive" className="max-w-md">
          <AlertDescription>{optionsError}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!options || !generation || !correction || !advanced) return null

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">Symboleo LLM Tool</h1>
        <Link to="/experiments" className="text-sm text-muted-foreground hover:text-foreground">
          Run an experiment suite →
        </Link>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <ContractUpload
          contractText={contractText}
          fileName={fileName}
          onFile={(text, name) => {
            setContractText(text)
            setFileName(name)
          }}
        />

        <StageSection
          title="Generation"
          id="generation"
          open={generationOpen}
          onOpenChange={setGenerationOpen}
          state={generation}
          options={options}
          onChange={updateGeneration}
        />

        <StageSection
          title="Correction"
          id="correction"
          open={correctionOpen}
          onOpenChange={setCorrectionOpen}
          state={correction}
          options={options}
          onChange={updateCorrection}
        />

        <AdvancedSection
          idPrefix="advanced"
          value={advanced}
          options={options}
          onChange={updateAdvanced}
          open={advancedOpen}
          onOpenChange={setAdvancedOpen}
        />

        {submitError && (
          <Alert variant="destructive">
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" className="w-full" disabled={!contractText || submitting}>
          {submitting ? 'Submitting...' : 'Generate'}
        </Button>
      </form>
    </div>
  )
}
