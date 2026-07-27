import '@testing-library/jest-dom'
import { beforeAll, afterEach, afterAll } from 'vitest'
import { cleanup } from '@testing-library/react'
import { server } from './server'
import { resetOptionsCache } from '@/hooks/useOptions'

beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetOptionsCache()
})
afterAll(() => server.close())
