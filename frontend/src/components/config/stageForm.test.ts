import type { OptionsResponse } from '@/api/types'
import {
  DEFAULTS,
  buildAdvancedFields,
  buildStageRequest,
  getParamConstraint,
  getParamDefault,
  makeDefaultStage,
  type StageFormValues,
} from './stageForm'

// buildStageRequest is the translation point between raw form strings and the
// typed API request, so every parse and conditional here is a place the request
// could silently go out wrong.
const STAGE: StageFormValues = {
  model: 'gpt-4o-mini',
  strategy: 'zero_shot',
  temperature: '0.2',
  include_grammar: false,
  example_files: ['sale_contract'],
}

describe('buildStageRequest', () => {
  it('parses temperature to a number and carries the stage fields through', () => {
    expect(buildStageRequest(STAGE)).toEqual({
      model: 'gpt-4o-mini',
      strategy: 'zero_shot',
      temperature: 0.2,
      include_grammar: false,
    })
  })

  it('omits strategy_params for a strategy that takes no examples', () => {
    expect(buildStageRequest(STAGE)).not.toHaveProperty('strategy_params')
  })

  it('sends the selected example files for few_shot', () => {
    expect(buildStageRequest({ ...STAGE, strategy: 'few_shot' })).toMatchObject({
      strategy_params: { example_files: ['sale_contract'] },
    })
  })

  it('omits temperature entirely when the field is blank', () => {
    // Blank = unset. Substituting a default here would make reasoning-model
    // configs (which reject the param) inexpressible from the browser.
    // Full-shape strict equality: pins that only temperature drops out on the
    // blank path, and rejects a present-but-undefined key.
    expect(buildStageRequest({ ...STAGE, temperature: '' })).toStrictEqual({
      model: 'gpt-4o-mini',
      strategy: 'zero_shot',
      include_grammar: false,
    })
  })

  it('keeps an explicit temperature of 0', () => {
    // 0 is a valid chosen value (deterministic sampling), distinct from unset.
    // A falsy-guard implementation of the omission would silently drop it.
    expect(buildStageRequest({ ...STAGE, temperature: '0' })).toHaveProperty('temperature', 0)
  })
})

describe('buildAdvancedFields', () => {
  it('parses the numeric fields and passes the toggles through', () => {
    expect(
      buildAdvancedFields({
        num_candidates: '3',
        max_iterations: '5',
        stop_on_first_convergence: true,
        save_intermediates: true,
      })
    ).toEqual({
      num_candidates: 3,
      max_iterations: 5,
      stop_on_first_convergence: true,
      save_intermediates: true,
    })
  })

  it('falls back to defaults when a numeric field cannot be parsed', () => {
    const fields = buildAdvancedFields({
      num_candidates: '',
      max_iterations: 'abc',
      stop_on_first_convergence: false,
      save_intermediates: false,
    })
    expect(fields.num_candidates).toBe(DEFAULTS.num_candidates)
    expect(fields.max_iterations).toBe(DEFAULTS.max_iterations)
  })
})

describe('getParamDefault', () => {
  it('prefers the server-supplied default', () => {
    expect(getParamDefault({ num_candidates: { default: 4 } }, 'num_candidates', 1)).toBe(4)
  })

  it('falls back when the parameter is absent entirely', () => {
    expect(getParamDefault({}, 'num_candidates', 1)).toBe(1)
  })

  it('falls back when the server sends an explicit null default', () => {
    // The real case: temperature has no forced default, since reasoning models
    // reject the parameter outright.
    expect(getParamDefault({ temperature: { default: null } }, 'temperature', 0.7)).toBe(0.7)
  })

  it('keeps a falsy-but-real default such as false', () => {
    // A `val || fallback` shortcut would wrongly return the fallback here.
    expect(getParamDefault({ include_grammar: { default: false } }, 'include_grammar', true)).toBe(
      false
    )
  })
})

describe('getParamConstraint', () => {
  it('returns the server-supplied bound', () => {
    expect(getParamConstraint({ temperature: { min: 0, max: 1.5 } }, 'temperature', 'max')).toBe(
      1.5
    )
  })

  it('keeps a falsy-but-real bound such as 0', () => {
    expect(getParamConstraint({ temperature: { min: 0 } }, 'temperature', 'min')).toBe(0)
  })

  it('returns undefined when the parameter is absent', () => {
    expect(getParamConstraint({}, 'temperature', 'max')).toBeUndefined()
  })

  it('returns undefined when the entry has no such bound', () => {
    expect(
      getParamConstraint({ temperature: { type: 'float' } }, 'temperature', 'max')
    ).toBeUndefined()
  })

  it('returns undefined for a non-numeric bound', () => {
    expect(getParamConstraint({ temperature: { max: '2' } }, 'temperature', 'max')).toBeUndefined()
  })
})

describe('makeDefaultStage', () => {
  // Two providers on purpose: with one, Object.keys()[0] is degenerate and the
  // seed assertion cannot tell "first provider" from "only provider".
  const OPTIONS: OptionsResponse = {
    strategies: ['zero_shot', 'cot'],
    models: { openai: ['gpt-4o-mini', 'gpt-4o'], anthropic: ['claude-opus-4-8'] },
    parameters: {},
    examples: [],
  }

  it('seeds the form from the first model/strategy and the local defaults', () => {
    // The server reports no temperature default (backend default is None —
    // unset), so the 0.2 seed lives only in DEFAULTS. This is the one direct
    // pin on that seed; the page tests exercise it only incidentally.
    expect(makeDefaultStage(OPTIONS)).toStrictEqual({
      model: 'gpt-4o-mini',
      strategy: 'zero_shot',
      temperature: '0.2',
      include_grammar: true,
      example_files: [],
    })
  })

  it('prefers a server-supplied parameter default over the local seed', () => {
    const options = { ...OPTIONS, parameters: { temperature: { default: 0.5 } } }
    expect(makeDefaultStage(options).temperature).toBe('0.5')
  })
})
