// Presentation helpers for token/cost rollups. The numeric rollups themselves
// are @computed_field's on the result models (see symboleo_llm_tool/output/
// models.py), serialized into the API and the generated schema — the frontend
// only formats them.

// Pin the locale so the thousands separator is deterministic across environments.
export function formatTokens(totalTokens: number): string {
  return totalTokens.toLocaleString('en-US')
}

// null means "no cost reported" (e.g. a model missing from LiteLLM's pricing
// map) — rendered as a dash, distinct from a real $0.00.
export function formatCost(costUsd: number | null): string {
  return costUsd == null ? '—' : `$${costUsd.toFixed(4)}`
}
