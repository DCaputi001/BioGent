// main.tsx
// Entry point. Mounts the app inside the OIDC provider, which owns the token
// lifecycle (redirect handling, storage, silent renewal) for everything below.

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from 'react-oidc-context'
// Self-hosted, bundled by Vite, rather than loaded from Google Fonts: a
// researcher's page load should not report their IP to a third party, and the
// app deliberately loads nothing from other origins.
import '@fontsource-variable/nunito'
import '@fontsource-variable/source-serif-4/opsz.css'
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
