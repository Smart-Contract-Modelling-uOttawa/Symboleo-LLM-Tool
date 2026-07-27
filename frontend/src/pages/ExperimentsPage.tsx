import { useState, useEffect, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Plus, Copy, Trash2, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ContractUpload } from '@/components/config/ContractUpload'
import { StageSection } from '@/components/config/StageSection'
import { AdvancedSection } from '@/components/config/AdvancedSection'
import {
  type StageFormValues,
  type AdvancedFormValues,
  type ExperimentFormValues,
  DEFAULTS,
  getParamConstraint,
  getParamDefault,
  makeDefaultStage,
  makeDefaultAdvanced,
  buildStageRequest,
  buildAdvancedFields,
} from '@/components/config/stageForm'
import { AxisExpander } from '@/components/config/AxisExpander'
import { expandAxis, type AxisDef } from '@/components/config/axisExpand'
import { useOptions } from '@/hooks/useOptions'
import { createSuite, exportSuite } from '@/api/client'
import { triggerDownload } from '@/components/results/download'
import type { OptionsResponse, SuiteRequest, SuiteSettings } from '@/api/types'

// Stable ids for React keys + add/remove, without depending on crypto in tests.
let _expCounter = 0
const nextId = () => `exp-${_expCounter++}`

function makeDefaultExperiment(options: OptionsResponse, index: number): ExperimentFormValues {
  return {
    id: nextId(),
    name: `Experiment ${index + 1}`,
    generation: makeDefaultStage(options),
    correction: makeDefaultStage(options),
    advanced: makeDefaultAdvanced(options),
  }
}

export default function ExperimentsPage() {
  const navigate = useNavigate()
  const { options, loading, error: optionsError } = useOptions()

  const [contractText, setContractText] = useState('')
  const [fileName, setFileName] = useState('')
  const [experiments, setExperiments] = useState<ExperimentFormValues[] | null>(null)
  const [maxConcurrency, setMaxConcurrency] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [exportWarnings, setExportWarnings] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (options && !experiments) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExperiments([makeDefaultExperiment(options, 0)])
      setMaxConcurrency(
        String(getParamDefault(options.parameters, 'max_concurrency', DEFAULTS.max_concurrency)),
      )
    }
  }, [options, experiments])

  function updateExperiment(
    id: string,
    updater: (prev: ExperimentFormValues) => ExperimentFormValues,
  ) {
    setExperiments(prev => prev?.map(e => (e.id === id ? updater(e) : e)) ?? prev)
  }

  function addExperiment() {
    setExperiments(prev =>
      prev && options ? [...prev, makeDefaultExperiment(options, prev.length)] : prev,
    )
  }

  function duplicateExperiment(id: string) {
    setExperiments(prev => {
      if (!prev) return prev
      const idx = prev.findIndex(e => e.id === id)
      if (idx === -1) return prev
      const src = prev[idx]
      const clone: ExperimentFormValues = {
        id: nextId(),
        name: `${src.name} copy`,
        generation: { ...src.generation, example_files: [...src.generation.example_files] },
        correction: { ...src.correction, example_files: [...src.correction.example_files] },
        advanced: { ...src.advanced },
      }
      const next = [...prev]
      next.splice(idx + 1, 0, clone)
      return next
    })
  }

  function removeExperiment(id: string) {
    setExperiments(prev => (prev && prev.length > 1 ? prev.filter(e => e.id !== id) : prev))
  }

  // Append one auto-named card per axis value, cloned from the first experiment.
  function expandByAxis(axis: AxisDef, values: string[]) {
    setExperiments(prev =>
      prev ? [...prev, ...expandAxis(prev[0], axis, values, nextId)] : prev,
    )
  }

  // Shared by run and export so the exported file describes the same suite the
  // Run button would submit — the contract is the only difference.
  function buildSuiteFields(cards: ExperimentFormValues[]): SuiteSettings {
    const parsedConcurrency = parseInt(maxConcurrency, 10)
    return {
      experiments: cards.map(exp => ({
        name: exp.name,
        generation: buildStageRequest(exp.generation),
        correction: buildStageRequest(exp.correction),
        ...buildAdvancedFields(exp.advanced),
      })),
      // Omit when blank → backend applies the SuiteConfig default.
      ...(Number.isNaN(parsedConcurrency) ? {} : { max_concurrency: parsedConcurrency }),
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!contractText || !experiments) return
    setFormError(null)
    setSubmitting(true)
    try {
      const request: SuiteRequest = {
        contract_text: contractText,
        ...buildSuiteFields(experiments),
      }
      const { run_id, warnings } = await createSuite(request)
      navigate(`/suites/${run_id}`, { state: { warnings: warnings ?? [] } })
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Submission failed')
    } finally {
      setSubmitting(false)
    }
  }

  // No contract required: it is a CLI argument, and the loader rejects a
  // contract_text key inside the file.
  async function handleExport() {
    if (!experiments) return
    setFormError(null)
    setExportWarnings([])
    setExporting(true)
    try {
      const { filename, content, warnings } = await exportSuite(buildSuiteFields(experiments))
      triggerDownload(content, filename, 'application/yaml')
      // Shown after the download rather than blocking it: the file is valid, but
      // a param in it may be one the model rejects at run time.
      setExportWarnings(warnings ?? [])
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setExporting(false)
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

  if (!options || !experiments) return null

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">Experiment Suite</h1>
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← Single run
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

        <div className="space-y-4">
          <div className="flex items-end justify-between">
            <div>
              <Label className="text-base">
                Experiments ({experiments.length})
              </Label>
              <p className="text-xs text-muted-foreground">
                One contract, compared across each configuration
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Label
                htmlFor="max-concurrency"
                className="text-xs text-muted-foreground font-normal whitespace-nowrap"
              >
                Concurrency
              </Label>
              <Input
                id="max-concurrency"
                type="number"
                min={getParamConstraint(options.parameters, 'max_concurrency', 'min') ?? 1}
                max={getParamConstraint(options.parameters, 'max_concurrency', 'max') ?? 8}
                value={maxConcurrency}
                onChange={e => setMaxConcurrency(e.target.value)}
                className="w-16 h-8"
                title="Max experiments/candidates running at once"
              />
            </div>
          </div>

          {experiments.map(exp => (
            <ExperimentCard
              key={exp.id}
              value={exp}
              options={options}
              onChange={updater => updateExperiment(exp.id, updater)}
              onDuplicate={() => duplicateExperiment(exp.id)}
              onRemove={() => removeExperiment(exp.id)}
              canRemove={experiments.length > 1}
            />
          ))}

          <Button type="button" variant="outline" className="w-full" onClick={addExperiment}>
            <Plus size={16} /> Add experiment
          </Button>

          <AxisExpander options={options} onGenerate={expandByAxis} />
        </div>

        {formError && (
          <Alert variant="destructive">
            <AlertDescription>{formError}</AlertDescription>
          </Alert>
        )}

        {exportWarnings.length > 0 && (
          <Alert>
            <AlertDescription>
              <p className="font-medium">Downloaded, with warnings:</p>
              <ul className="list-disc pl-4 mt-1">
                {exportWarnings.map(w => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Button type="submit" className="w-full" disabled={!contractText || submitting}>
            {submitting ? 'Submitting...' : `Run ${experiments.length} experiment${experiments.length !== 1 ? 's' : ''}`}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={handleExport}
            disabled={exporting}
            title="Save this suite as a YAML file you can re-run with the CLI"
          >
            <Download size={16} />
            {exporting ? 'Preparing...' : 'Download suite config'}
          </Button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ExperimentCard
// ---------------------------------------------------------------------------

interface ExperimentCardProps {
  value: ExperimentFormValues
  options: OptionsResponse
  onChange: (updater: (prev: ExperimentFormValues) => ExperimentFormValues) => void
  onDuplicate: () => void
  onRemove: () => void
  canRemove: boolean
}

function ExperimentCard({
  value,
  options,
  onChange,
  onDuplicate,
  onRemove,
  canRemove,
}: ExperimentCardProps) {
  const [genOpen, setGenOpen] = useState(true)
  const [corrOpen, setCorrOpen] = useState(false)
  const [advOpen, setAdvOpen] = useState(false)

  const updateGeneration = (u: (prev: StageFormValues) => StageFormValues) =>
    onChange(prev => ({ ...prev, generation: u(prev.generation) }))
  const updateCorrection = (u: (prev: StageFormValues) => StageFormValues) =>
    onChange(prev => ({ ...prev, correction: u(prev.correction) }))
  const updateAdvanced = (u: (prev: AdvancedFormValues) => AdvancedFormValues) =>
    onChange(prev => ({ ...prev, advanced: u(prev.advanced) }))

  return (
    <div className="border rounded-lg p-4 space-y-4 bg-card">
      <div className="flex items-center gap-2">
        <Input
          aria-label="Experiment name"
          value={value.name}
          onChange={e => onChange(prev => ({ ...prev, name: e.target.value }))}
          className="font-medium"
        />
        <Button type="button" variant="ghost" size="icon" onClick={onDuplicate} title="Duplicate">
          <Copy size={16} />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onRemove}
          disabled={!canRemove}
          title="Remove"
        >
          <Trash2 size={16} />
        </Button>
      </div>

      <StageSection
        title="Generation"
        id={`${value.id}-gen`}
        open={genOpen}
        onOpenChange={setGenOpen}
        state={value.generation}
        options={options}
        onChange={updateGeneration}
      />
      <StageSection
        title="Correction"
        id={`${value.id}-corr`}
        open={corrOpen}
        onOpenChange={setCorrOpen}
        state={value.correction}
        options={options}
        onChange={updateCorrection}
      />
      <AdvancedSection
        idPrefix={`${value.id}-adv`}
        value={value.advanced}
        options={options}
        onChange={updateAdvanced}
        open={advOpen}
        onOpenChange={setAdvOpen}
      />
    </div>
  )
}
