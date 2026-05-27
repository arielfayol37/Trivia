# Trivia

Self-hosted multiplayer trivia engine. The product path starts with AI-assisted quiz
authoring, then moves into real-time small-group play.

## Local Mac Development

Backend dependencies stay inside `backend/.venv`:

```bash
cd backend
uv sync --dev
uv run python manage.py migrate
uv run python manage.py runserver
```

Frontend dependencies stay inside `frontend/node_modules`:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

By default `LLM_PROVIDER=sample`, so the authoring endpoint uses a deterministic local
sample generator. That keeps the UI testable without making LLM calls.

When you are ready for real generation, set `LLM_PROVIDER=openai` or
`LLM_PROVIDER=anthropic` in `.env`, then fill the matching API key and model variables.
Do not put API keys in chat or commit them.

## Verification

```bash
cd backend
uv run python manage.py check
uv run python manage.py test apps.authoring apps.judging
```

```bash
cd frontend
npm run lint
npm run build
```

## Hosting Target

The production target is the Windows desktop: Django ASGI, Postgres, Redis, Caddy, and
Cloudflare Tunnel. Docker files are included as templates, but Docker is not required
for the early local Mac workflow.
