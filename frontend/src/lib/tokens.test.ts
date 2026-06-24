import { describe, it, expect } from 'vitest'
import { formatTokens, formatCost } from './tokens'

describe('formatTokens', () => {
  it('formats with a thousands separator', () => {
    expect(formatTokens(1500)).toBe('1,500')
  })

  it('formats zero', () => {
    expect(formatTokens(0)).toBe('0')
  })
})

describe('formatCost', () => {
  it('formats a cost to four decimals with a dollar sign', () => {
    expect(formatCost(0.003)).toBe('$0.0030')
  })

  it('renders an unknown (null) cost as an em dash', () => {
    expect(formatCost(null)).toBe('—')
  })

  it('renders a real $0.00 distinctly from unknown', () => {
    expect(formatCost(0)).toBe('$0.0000')
  })
})
