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

When you are ready for real generation and live LLM answer judging, set
`LLM_PROVIDER=openai` or `LLM_PROVIDER=anthropic` in `.env`, then fill the matching API
key and model variables. `OPENAI_JUDGE_MODEL` / `ANTHROPIC_JUDGE_MODEL` are used for
typed-answer judge fallback; if omitted, the app falls back to the matching authoring
model. Do not put API keys in chat or commit them.

## Same-Network Phone Testing

Use your laptop's LAN IP, then run the dev servers on all interfaces:

```bash
cd backend
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,[::1],YOUR_LAN_IP" uv run python manage.py runserver 0.0.0.0:8000
```

```bash
cd frontend
npm run dev:lan
```

Open `http://YOUR_LAN_IP:5173` from the phone. If Vite picks another port, use the port
shown in the frontend terminal.

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
