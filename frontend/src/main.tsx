// main.tsx
// Entry point. Mounts the app inside the OIDC provider, which owns the token
// lifecycle (redirect handling, storage, silent renewal) for everything below.

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
import './index.css'
import App from './App.tsx'
import { oidcConfig } from './auth/oidcConfig'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider {...oidcConfig}>
      <App />
    </AuthProvider>
  </StrictMode>,
)
