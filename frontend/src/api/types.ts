import type { components } from './schema'

export type GenerateRequest = components['schemas']['GenerateRequest']
export type StageRequest = components['schemas']['StageRequest']
export type RunCreatedResponse = components['schemas']['RunCreatedResponse']
export type OptionsResponse = components['schemas']['OptionsResponse']

export type SymboleoIssue = components['schemas']['SymboleoIssue']
export type IterationRecord = components['schemas']['IterationRecord']
export type CandidateResult = components['schemas']['CandidateResult']
export type PipelineResult = components['schemas']['PipelineResult']
export type ProgressEvent = components['schemas']['ProgressEvent']
export type CompleteEvent = components['schemas']['CompleteEvent']
export type ErrorEvent = components['schemas']['ErrorEvent']

export type SSEEvent = ProgressEvent | CompleteEvent | ErrorEvent
