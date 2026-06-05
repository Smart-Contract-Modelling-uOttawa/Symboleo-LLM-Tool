import { useState, useCallback, useEffect, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { ChevronDown, Upload, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Separator } from '@/components/ui/separator'
import { useOptions } from '@/hooks/useOptions'
import { submitGenerate } from '@/api/client'
import type { OptionsResponse } from '@/api/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StageState {
  model: string
  strategy: string
  temperature: string
  include_grammar: boolean
  example_files: string[]
}

interface AdvancedState {
  num_candidates: string
  max_iterations: string
  stop_on_first_convergence: boolean
  save_intermediates: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getParamDefault<T>(
  parameters: Record<string, unknown>,
  key: string,
  fallback: T,
): T {
  const entry = parameters[key]
  if (entry !== null && typeof entry === 'object' && 'default' in entry) {
    const val = (entry as Record<string, unknown>)['default']
    return val !== undefined ? (val as T) : fallback
  }
  return fallback
}

function makeDefaultStage(options: OptionsResponse): StageState {
  const firstProvider = Object.keys(options.models)[0]
  const firstModel = (firstProvider && options.models[firstProvider]?.[0]) ?? ''
  const firstStrategy = options.strategies[0] ?? ''
  return {
    model: firstModel,
    strategy: firstStrategy,
    temperature: String(getParamDefault(options.parameters, 'temperature', 0.7)),
    include_grammar: getParamDefault(options.parameters, 'include_grammar', true),
    example_files: [],
  }
}

function makeDefaultAdvanced(options: OptionsResponse): AdvancedState {
  return {
    num_candidates: String(getParamDefault(options.parameters, 'num_candidates', 1)),
    max_iterations: String(getParamDefault(options.parameters, 'max_iterations', 3)),
    stop_on_first_convergence: getParamDefault(options.parameters, 'stop_on_first_convergence', false),
    save_intermediates: getParamDefault(options.parameters, 'save_intermediates', false),
  }
}

function buildStageRequest(state: StageState) {
  const temp = parseFloat(state.temperature)
  return {
    model: state.model,
    strategy: state.strategy,
    temperature: isNaN(temp) ? 0.7 : temp,
    include_grammar: state.include_grammar,
    ...(state.strategy === 'few_shot' && {
      strategy_params: { example_files: state.example_files },
    }),
  }
}

// ---------------------------------------------------------------------------
// ConfigPage
// ---------------------------------------------------------------------------

export default function ConfigPage() {
  const navigate = useNavigate()
  const { options, loading, error: optionsError } = useOptions()

  const [contractText, setContractText] = useState('')
  const [fileName, setFileName] = useState('')
  const [generation, setGeneration] = useState<StageState | null>(null)
  const [correction, setCorrection] = useState<StageState | null>(null)
  const [advanced, setAdvanced] = useState<AdvancedState | null>(null)
  const [generationOpen, setGenerationOpen] = useState(true)
  const [correctionOpen, setCorrectionOpen] = useState(true)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (options && !generation) {
      const defaults = makeDefaultStage(options)
      setGeneration(defaults)
      setCorrection(defaults)
      setAdvanced(makeDefaultAdvanced(options))
    }
  }, [options, generation])

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const file = acceptedFiles[0]
    if (!file) return
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = (e) => setContractText((e.target?.result as string) ?? '')
    reader.readAsText(file)
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/plain': ['.txt'] },
    multiple: false,
  })

  function updateGeneration(updater: (prev: StageState) => StageState) {
    setGeneration(prev => (prev ? updater(prev) : prev))
  }

  function updateCorrection(updater: (prev: StageState) => StageState) {
    setCorrection(prev => (prev ? updater(prev) : prev))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!contractText || !generation || !correction || !advanced) return
    setSubmitError(null)
    setSubmitting(true)
    try {
      const numCandidates = parseInt(advanced.num_candidates, 10)
      const maxIterations = parseInt(advanced.max_iterations, 10)
      const { run_id } = await submitGenerate({
        contract_text: contractText,
        generation: buildStageRequest(generation),
        correction: buildStageRequest(correction),
        num_candidates: isNaN(numCandidates) ? 1 : numCandidates,
        max_iterations: isNaN(maxIterations) ? 3 : maxIterations,
        stop_on_first_convergence: advanced.stop_on_first_convergence,
        save_intermediates: advanced.save_intermediates,
      })
      navigate(`/runs/${run_id}`)
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
      <h1 className="text-2xl font-semibold mb-8">Symboleo LLM Tool</h1>

      <form onSubmit={handleSubmit} className="space-y-6">

        {/* Contract file upload */}
        <div className="space-y-2">
          <Label>Contract File</Label>
          <div
            {...getRootProps()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              isDragActive
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-primary/50'
            }`}
          >
            <input {...getInputProps()} />
            <Upload className="mx-auto mb-2 text-muted-foreground" size={24} />
            {fileName ? (
              <p className="text-sm flex items-center justify-center gap-1.5">
                <FileText size={14} />
                {fileName}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                {isDragActive
                  ? 'Drop the file here'
                  : 'Drag and drop a .txt file, or click to browse'}
              </p>
            )}
          </div>
          {contractText && (
            <textarea
              readOnly
              value={contractText}
              rows={6}
              className="w-full text-xs font-mono p-2 rounded-md border bg-muted resize-none"
            />
          )}
        </div>

        {/* Generation section */}
        <StageSection
          title="Generation"
          id="generation"
          open={generationOpen}
          onOpenChange={setGenerationOpen}
          state={generation}
          options={options}
          onChange={updateGeneration}
        />

        {/* Correction section */}
        <StageSection
          title="Correction"
          id="correction"
          open={correctionOpen}
          onOpenChange={setCorrectionOpen}
          state={correction}
          options={options}
          onChange={updateCorrection}
        />

        {/* Advanced options */}
        <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
          <CollapsibleTrigger className="flex items-center gap-2 w-full text-sm font-medium py-1">
            <ChevronDown
              size={16}
              className={`transition-transform ${advancedOpen ? 'rotate-180' : ''}`}
            />
            Advanced Options
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label htmlFor="num_candidates">Candidates</Label>
                <Input
                  id="num_candidates"
                  type="number"
                  min={1}
                  value={advanced.num_candidates}
                  onChange={e =>
                    setAdvanced(a => a ? { ...a, num_candidates: e.target.value } : a)
                  }
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="max_iterations">Max Iterations</Label>
                <Input
                  id="max_iterations"
                  type="number"
                  min={1}
                  value={advanced.max_iterations}
                  onChange={e =>
                    setAdvanced(a => a ? { ...a, max_iterations: e.target.value } : a)
                  }
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="stop_on_first"
                  checked={advanced.stop_on_first_convergence}
                  onCheckedChange={v =>
                    setAdvanced(a => a ? { ...a, stop_on_first_convergence: !!v } : a)
                  }
                />
                <Label htmlFor="stop_on_first" className="font-normal cursor-pointer">
                  Stop on first convergence
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="save_intermediates"
                  checked={advanced.save_intermediates}
                  onCheckedChange={v =>
                    setAdvanced(a => a ? { ...a, save_intermediates: !!v } : a)
                  }
                />
                <Label htmlFor="save_intermediates" className="font-normal cursor-pointer">
                  Save intermediates
                </Label>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {submitError && (
          <Alert variant="destructive">
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          className="w-full"
          disabled={!contractText || submitting}
        >
          {submitting ? 'Submitting...' : 'Generate'}
        </Button>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// StageSection
// ---------------------------------------------------------------------------

interface StageSectionProps {
  title: string
  id: string
  open: boolean
  onOpenChange: (open: boolean) => void
  state: StageState
  options: OptionsResponse
  onChange: (updater: (prev: StageState) => StageState) => void
}

function StageSection({
  title,
  id: titleId,
  open,
  onOpenChange,
  state,
  options,
  onChange,
}: StageSectionProps) {
  const hasFewShotExamples = options.examples.length > 0

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <div className="border rounded-lg">
        <CollapsibleTrigger className="flex items-center justify-between w-full px-4 py-3 text-sm font-medium">
          {title}
          <ChevronDown
            size={16}
            className={`transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Separator />
          <div className="p-4 space-y-4">

            {/* Model */}
            <div className="space-y-1.5">
              <Label>Model</Label>
              <Select
                value={state.model}
                onValueChange={v => onChange(prev => ({ ...prev, model: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(options.models).map(([provider, models]) => (
                    <SelectGroup key={provider}>
                      <SelectLabel className="capitalize">{provider}</SelectLabel>
                      {models.map(m => (
                        <SelectItem key={m} value={m}>{m}</SelectItem>
                      ))}
                    </SelectGroup>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Strategy */}
            <div className="space-y-1.5">
              <Label>Strategy</Label>
              <Select
                value={state.strategy}
                onValueChange={v => onChange(prev => ({ ...prev, strategy: v, example_files: [] }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select strategy" />
                </SelectTrigger>
                <SelectContent>
                  {options.strategies.map(s => (
                    <SelectItem
                      key={s}
                      value={s}
                      disabled={s === 'few_shot' && !hasFewShotExamples}
                    >
                      {s}
                      {s === 'few_shot' && !hasFewShotExamples ? ' (no examples available)' : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Example files — shown only for few_shot */}
            {state.strategy === 'few_shot' && (
              <div className="space-y-2">
                <Label>Example Files</Label>
                <div className="space-y-1.5 pl-1">
                  {options.examples.map(ex => (
                    <div key={ex} className="flex items-center gap-2">
                      <Checkbox
                        id={`${titleId}-ex-${ex}`}
                        checked={state.example_files.includes(ex)}
                        onCheckedChange={checked => {
                          onChange(prev => ({
                            ...prev,
                            example_files: checked
                              ? [...prev.example_files, ex]
                              : prev.example_files.filter(f => f !== ex),
                          }))
                        }}
                      />
                      <Label
                        htmlFor={`${titleId}-ex-${ex}`}
                        className="font-normal cursor-pointer"
                      >
                        {ex}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Temperature */}
            <div className="space-y-1.5">
              <Label htmlFor={`${titleId}-temp`}>Temperature</Label>
              <Input
                id={`${titleId}-temp`}
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={state.temperature}
                onChange={e => onChange(prev => ({ ...prev, temperature: e.target.value }))}
              />
            </div>

            {/* Include grammar */}
            <div className="flex items-center gap-2">
              <Checkbox
                id={`${titleId}-grammar`}
                checked={state.include_grammar}
                onCheckedChange={v =>
                  onChange(prev => ({ ...prev, include_grammar: !!v }))
                }
              />
              <Label
                htmlFor={`${titleId}-grammar`}
                className="font-normal cursor-pointer"
              >
                Include grammar
              </Label>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}
