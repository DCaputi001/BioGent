// setup.ts
// Global test setup: jest-dom matchers (toBeInTheDocument and friends) and a
// clean sessionStorage between tests, since useApiKey persists there and a
// leaked key would make tests pass or fail depending on their order.

import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'

afterEach(() => {
  sessionStorage.clear()
})
