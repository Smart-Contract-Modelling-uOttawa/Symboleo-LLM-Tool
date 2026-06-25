import { describe, it, expect } from 'vitest'
import { AXES, expandAxis } from './axisExpand'
import type { ExperimentFormValues } from './stageForm'
import type { OptionsResponse } from '@/api/types'

const STRATEGY_AXIS = AXES.find(a => a.key === 'strategy')!
const MODEL_AXIS = AXES.find(a => a.key === 'model')!

function base(): ExperimentFormValues {
  return {
    id: 'base',
    name: 'Experiment 1',
    generation: {
      model: 'gpt-4o-mini',
      strategy: 'zero_shot',
      temperature: '0.2',
      include_grammar: true,
      example_files: ['sale'],
    },
    correction: {
      model: 'gpt-4o-mini',
      strategy: 'zero_shot',
      temperature: '0.2',
      include_grammar: true,
      example_files: [],
    },
    advanced: {
      num_candidates: '1',
      max_iterations: '3',
      stop_on_first_convergence: false,
      save_intermediates: false,
    },
  }
}

function counter(): () => string {
  let n = 0
  return () => `gen-${n++}`
}

function opts(strategies: string[], models: Record<string, string[]>): OptionsResponse {
  return { strategies, models, parameters: {}, examples: [] }
}

describe('expandAxis', () => {
  it('produces one card per value, auto-named by the value', () => {
    const cards = expandAxis(base(), STRATEGY_AXIS, ['zero_shot', 'cot'], counter())
    expect(cards).toHaveLength(2)
    expect(cards.map(c => c.name)).toEqual(['zero_shot', 'cot'])
    expect(cards.map(c => c.generation.strategy)).toEqual(['zero_shot', 'cot'])
  })

  it('overrides only the axis field; correction and advanced are cloned intact', () => {
    const b = base()
    const [card] = expandAxis(b, MODEL_AXIS, ['gpt-4o'], counter())
    expect(card.generation.model).toBe('gpt-4o')
    expect(card.generation.temperature).toBe('0.2') // untouched
    expect(card.correction).toEqual(b.correction)
    expect(card.advanced).toEqual(b.advanced)
  })

  it('deep-clones arrays so generated cards do not share references with the base', () => {
    const b = base()
    const [card] = expandAxis(b, MODEL_AXIS, ['gpt-4o'], counter())
    expect(card.generation.example_files).not.toBe(b.generation.example_files)
    expect(card.correction.example_files).not.toBe(b.correction.example_files)
  })

  it('assigns a fresh id to each generated card', () => {
    const cards = expandAxis(base(), STRATEGY_AXIS, ['zero_shot', 'cot'], counter())
    expect(cards[0].id).not.toBe(cards[1].id)
  })
})

describe('axis values', () => {
  it('strategy axis excludes few_shot (it needs per-card examples)', () => {
    expect(STRATEGY_AXIS.values(opts(['zero_shot', 'few_shot', 'cot'], {}))).toEqual([
      'zero_shot',
      'cot',
    ])
  })

  it('model axis flattens models across providers', () => {
    const values = MODEL_AXIS.values(
      opts([], { openai: ['gpt-4o-mini'], anthropic: ['claude'] }),
    )
    expect(values).toEqual(['gpt-4o-mini', 'claude'])
  })
})
