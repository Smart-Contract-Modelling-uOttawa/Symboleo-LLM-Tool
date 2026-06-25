import type { OptionsResponse, StageRequest } from '@/api/types'

// ---------------------------------------------------------------------------
// Shared config-form types, defaults, and translation helpers
//
// A single pipeline configuration (one generation stage + one correction stage
// + advanced run options) is the unit reused by both the single-run config page
// and each experiment card in a suite. These helpers are the one place that
// knows how raw form strings map to the typed API request fields.
// ---------------------------------------------------------------------------

export interface StageFormValues {
  model: string
  strategy: string
  temperature: string
  include_grammar: boolean
  example_files: string[]
}

export interface AdvancedFormValues {
  num_candidates: string
  max_iterations: string
  stop_on_first_convergence: boolean
  save_intermediates: boolean
}

// One experiment card in a suite: a name plus a full pipeline config (both
// stages + advanced). The composite reused by ExperimentsPage and the axis
// expander; lives here (the config layer) so neither depends on the page.
export interface ExperimentFormValues {
  id: string
  name: string
  generation: StageFormValues
  correction: StageFormValues
  advanced: AdvancedFormValues
}

export const FEW_SHOT = 'few_shot'

export const DEFAULTS = {
  temperature: 0.7,
  include_grammar: true,
  num_candidates: 1,
  max_iterations: 3,
  stop_on_first_convergence: false,
  save_intermediates: false,
}

export function getParamDefault<T>(
  parameters: Record<string, unknown>,
  key: string,
  fallback: T,
): T {
  const entry = parameters[key]
  if (entry !== null && typeof entry === 'object' && 'default' in entry) {
    const val = (entry as Record<string, unknown>)['default']
    // Fall back when default is absent OR null (temperature has no forced default).
    return val !== undefined && val !== null ? (val as T) : fallback
  }
  return fallback
}

export function makeDefaultStage(options: OptionsResponse): StageFormValues {
  const firstProvider = Object.keys(options.models)[0]
  const firstModel = (firstProvider && options.models[firstProvider]?.[0]) ?? ''
  const firstStrategy = options.strategies[0] ?? ''
  return {
    model: firstModel,
    strategy: firstStrategy,
    temperature: String(getParamDefault(options.parameters, 'temperature', DEFAULTS.temperature)),
    include_grammar: getParamDefault(options.parameters, 'include_grammar', DEFAULTS.include_grammar),
    example_files: [],
  }
}

export function makeDefaultAdvanced(options: OptionsResponse): AdvancedFormValues {
  return {
    num_candidates: String(getParamDefault(options.parameters, 'num_candidates', DEFAULTS.num_candidates)),
    max_iterations: String(getParamDefault(options.parameters, 'max_iterations', DEFAULTS.max_iterations)),
    stop_on_first_convergence: getParamDefault(options.parameters, 'stop_on_first_convergence', DEFAULTS.stop_on_first_convergence),
    save_intermediates: getParamDefault(options.parameters, 'save_intermediates', DEFAULTS.save_intermediates),
  }
}

export function makeNullableUpdater<T>(setter: (fn: (prev: T | null) => T | null) => void) {
  return (updater: (prev: T) => T) =>
    setter(prev => (prev ? updater(prev) : prev))
}

export function buildStageRequest(state: StageFormValues): StageRequest {
  const temp = parseFloat(state.temperature)
  return {
    model: state.model,
    strategy: state.strategy,
    temperature: isNaN(temp) ? DEFAULTS.temperature : temp,
    include_grammar: state.include_grammar,
    ...(state.strategy === FEW_SHOT && {
      strategy_params: { example_files: state.example_files },
    }),
  }
}

export function buildAdvancedFields(advanced: AdvancedFormValues) {
  const numCandidates = parseInt(advanced.num_candidates, 10)
  const maxIterations = parseInt(advanced.max_iterations, 10)
  return {
    num_candidates: isNaN(numCandidates) ? DEFAULTS.num_candidates : numCandidates,
    max_iterations: isNaN(maxIterations) ? DEFAULTS.max_iterations : maxIterations,
    stop_on_first_convergence: advanced.stop_on_first_convergence,
    save_intermediates: advanced.save_intermediates,
  }
}
