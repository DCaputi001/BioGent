# BioGent frontend

React + TypeScript + Vite web app for the RAG document-search service. See
`ARCHITECTURE.md` (Frontend) for why this stack, and `PRODUCTION_PLAN.md`
Phase 4 for what it has to prove: a researcher pastes their own Anthropic API
key, asks a question, and gets a grounded answer.

Currently the default Vite scaffold. The UI is built in the next steps.

## Running locally

The backend must be running first, from `services/rag`:

```powershell
uv run uvicorn app.api:app --reload --port 8000
```

Then, from this directory:

```powershell
npm install
npm run dev
```

The dev server serves `http://localhost:5173`, which is the origin the API
already allows (`RAG_CORS_ORIGINS` in `services/rag/.env.example`). Changing
this port means changing that setting too, or the browser will block every
request.

## Configuration

`VITE_API_BASE_URL` points at the backend, including the `/api` prefix every
route is served under. Copy `.env.example` to `.env.local` and edit it there;
`.env.local` is git-ignored.

In production this is just `/api`: one CloudFront distribution serves this app
from S3 and routes `/api/*` to the backend, so the request is same-origin and
CORS does not apply at all.

Only `VITE_`-prefixed variables reach the browser, and they are embedded in the
built JavaScript as plain text, so none of them may hold a secret. The
researcher's Anthropic key is entered in the UI at runtime, held in the browser
session, sent with each request, and never persisted server-side or baked into
a build.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check and produce the production build in `dist/` |
| `npm run lint` | Lint with oxlint |
| `npm run preview` | Serve the built `dist/` locally |
