import type { components } from './schema'

export type GenerateRequest = components['schemas']['GenerateRequest']
export type StageRequest = components['schemas']['StageRequest']
export type RunCreatedResponse = components['schemas']['RunCreatedResponse']
export type OptionsResponse = components['schemas']['OptionsResponse']

export type SuiteRequest = components['schemas']['SuiteRequest']
export type ExperimentRequest = components['schemas']['ExperimentRequest']
export type SuiteResult = components['schemas']['SuiteResult']
export type ExperimentResult = components['schemas']['ExperimentResult']

export type SymboleoIssue = components['schemas']['SymboleoIssue']
export type TokenUsage = components['schemas']['TokenUsage']
export type IterationRecord = components['schemas']['IterationRecord']
export type CandidateResult = components['schemas']['CandidateResult']
export type PipelineResult = components['schemas']['PipelineResult']
export type ProgressEvent = components['schemas']['ProgressEvent']
export type CompleteEvent = components['schemas']['CompleteEvent']
export type ErrorEvent = components['schemas']['ErrorEvent']

// The schema generates `type` as a shared EventType enum on all three variants,
// which prevents TypeScript narrowing. These wrapper types replace the field
// with a per-variant literal so `data.type === 'progress'` narrows correctly.
type WithLiteralType<T, V extends string> = Omit<T, 'type'> & { type: V }
export type SSEEvent =
  | WithLiteralType<ProgressEvent, 'progress'>
  | WithLiteralType<CompleteEvent, 'complete'>
  | WithLiteralType<ErrorEvent, 'error'>
