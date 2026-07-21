import {
  DEFAULTS,
  buildAdvancedFields,
  buildStageRequest,
  getParamDefault,
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

  it('falls back to the default temperature when the field is blank', () => {
    expect(buildStageRequest({ ...STAGE, temperature: '' }).temperature).toBe(DEFAULTS.temperature)
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
