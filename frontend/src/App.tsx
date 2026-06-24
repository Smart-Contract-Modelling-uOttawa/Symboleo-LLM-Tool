import { BrowserRouter, Routes, Route } from 'react-router-dom'
import ConfigPage from '@/pages/ConfigPage'
import ResultsPage from '@/pages/ResultsPage'
import ExperimentsPage from '@/pages/ExperimentsPage'
import SuiteResultsPage from '@/pages/SuiteResultsPage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background text-foreground">
        <Routes>
          <Route path="/" element={<ConfigPage />} />
          <Route path="/runs/:runId" element={<ResultsPage />} />
          <Route path="/experiments" element={<ExperimentsPage />} />
          <Route path="/suites/:suiteId" element={<SuiteResultsPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
