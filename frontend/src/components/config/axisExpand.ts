import type { OptionsResponse } from '@/api/types'
import { FEW_SHOT, type ExperimentFormValues, type StageFormValues } from './stageForm'

export type AxisKey = 'strategy' | 'model'

export interface AxisDef {
  key: AxisKey
  label: string
  // Candidate values for this axis, drawn from GET /options.
  values: (options: OptionsResponse) => string[]
  // Override one generation-stage field with an axis value.
  apply: (generation: StageFormValues, value: string) => StageFormValues
}

// Categorical generation-stage axes. few_shot is excluded from the strategy
// axis: it needs per-card example_files that a bulk generator can't supply, so
// it stays a manually-added card.
export const AXES: AxisDef[] = [
  {
    key: 'strategy',
    label: 'Strategy',
    values: o => o.strategies.filter(s => s !== FEW_SHOT),
    apply: (g, v) => ({ ...g, strategy: v, example_files: [] }),
  },
  {
    key: 'model',
    label: 'Model',
    values: o => Object.values(o.models).flat(),
    apply: (g, v) => ({ ...g, model: v }),
  },
]

// One experiment card per value, cloned from `base`, overriding the axis field
// on the generation stage and auto-named by the value. Correction and advanced
// are held constant (the research control). Pure — see axisExpand.test.ts.
export function expandAxis(
  base: ExperimentFormValues,
  axis: AxisDef,
  values: string[],
  nextId: () => string,
): ExperimentFormValues[] {
  return values.map(value => {
    const generation = axis.apply(base.generation, value)
    return {
      id: nextId(),
      name: value,
      generation: { ...generation, example_files: [...generation.example_files] },
      correction: { ...base.correction, example_files: [...base.correction.example_files] },
      advanced: { ...base.advanced },
    }
  })
}
