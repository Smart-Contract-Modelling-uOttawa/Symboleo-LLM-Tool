import { render, screen } from '@testing-library/react'
import { StageSection } from './StageSection'
import type { StageFormValues } from './stageForm'
import { MOCK_OPTIONS } from '@/test/handlers'

// The disabled state is the visible half of the reasoning-model guard: the
// invisible half (blanking, so the request omits the key) is pinned in
// stageForm.test.ts. Interaction with the Radix Select is deliberately not
// simulated — happy-dom cannot drive its portal — so these render directly
// with the model already selected.
function renderSection(state: StageFormValues) {
  return render(
    <StageSection
      title="Generation"
      id="gen"
      open={true}
      onOpenChange={() => {}}
      state={state}
      options={MOCK_OPTIONS}
      onChange={() => {}}
    />,
  )
}

const BASE: StageFormValues = {
  model: 'gpt-4o-mini',
  strategy: 'zero_shot',
  temperature: '0.2',
  include_grammar: true,
  example_files: [],
}

describe('StageSection temperature gating', () => {
  it('disables the temperature input for a reasoning model', () => {
    renderSection({ ...BASE, model: 'gpt-5-nano', temperature: '' })
    const input = screen.getByLabelText('Temperature')
    expect(input).toBeDisabled()
    expect(input).toHaveAttribute('placeholder', 'Not accepted by this model')
  })

  it('keeps the temperature input enabled for an ordinary model', () => {
    renderSection(BASE)
    const input = screen.getByLabelText('Temperature')
    expect(input).not.toBeDisabled()
    expect(input).toHaveValue(0.2)
  })
})
