import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders without crashing', async () => {
    render(<App />)
    expect(await screen.findByText('Symboleo LLM Tool')).toBeInTheDocument()
  })
})
