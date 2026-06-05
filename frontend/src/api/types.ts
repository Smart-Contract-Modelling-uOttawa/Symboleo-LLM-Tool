import type { components } from './schema'

export type GenerateRequest = components['schemas']['GenerateRequest']
export type StageRequest = components['schemas']['StageRequest']
export type RunCreatedResponse = components['schemas']['RunCreatedResponse']
export type OptionsResponse = components['schemas']['OptionsResponse']

export interface SymboleoIssue {
  severity: string
  code: string | null
  offset: number
  line: number
  column: number
  length: number
  message: string
}

export interface IterationRecord {
  iteration: number
  code: string
  errors: SymboleoIssue[]
}

export interface CandidateResult {
  candidate_id: number
  final_code: string
  converged: boolean
  iterations_used: number
  error_history: IterationRecord[]
}

export interface PipelineResult {
  success: boolean
  timestamp: string
  input_file: string
  candidates: CandidateResult[]
}

export interface ProgressEvent {
  type: 'progress'
  candidate_id: number
  iteration: number
  error_count: number
}

export interface CompleteEvent {
  type: 'complete'
  result: PipelineResult
}

export interface ErrorEvent {
  type: 'error'
  message: string
}

export type SSEEvent = ProgressEvent | CompleteEvent | ErrorEvent
