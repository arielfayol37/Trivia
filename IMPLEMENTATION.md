# Trivia — Implementation Plan

Companion to `SPEC.md`. The spec is the **what**; this doc is the **how** and the **in
what order**.

---

## Current Status

Development is happening on the Mac laptop with project-local Python and Node
dependencies. The app has moved beyond M1: it now has an AI authoring flow, a playable
multiplayer prototype, WebSocket session snapshots, and a first pass at a player-facing
quiz catalog.

Implemented:

- Backend Django project, local `uv` virtualenv, SQLite fallback, models, migrations,
  admin registration, health endpoint, quiz serializers, and authoring/session APIs.
- Core data model for quizzes, rounds, questions, prompt blocks, answer widgets,
  sessions, players, submissions, round results, anti-cheat events, and leaderboard
  entries.
- Quiz lifecycle and category fields:
  - `status`: `draft`, `ready`, `archived`.
  - `category`: `science`, `tv`, `sports`, `geography`, `history`, `general`.
  - Play Hub only lists `ready` quizzes by default.
  - Authoring can still see drafts and can mark a quiz ready or move it back to draft.
- Frontend split between:
  - Play Hub at `/`: search/filter ready quizzes, open quiz detail, create lobby, join
    by invite code, play.
  - Authoring at `/author`: AI producer/chat, source material input, draft generation,
    recent quizzes, metadata/category/state controls, compact blueprint preview.
- Authoring can generate and save static quizzes through the product UI. Without
  configured OpenAI/Anthropic credentials it uses the deterministic local sample
  generator, but the same schema and persistence path are exercised.
- Authoring chat now calls the backend LLM provider instead of a canned frontend helper.
  OpenAI-backed chat has been verified with the current configured model constraints.
- Prompt blocks and answer widgets are modeled/rendered from the start, so the project is
  not locked into plain text prompts.
- Supported prompt block rendering:
  `text`, `image`, `table`, `math`, `source_excerpt`, `diagram_spec`.
- Image prompt blocks support direct image URLs with `url`, `alt`, and `caption`, and the
  frontend renders a graceful failed-image placeholder if a URL cannot load.
- LaTeX/math prompt blocks render with KaTeX in the frontend.
- Inline and bare LaTeX render across question prose, canonical answers, list prompts,
  and answer choices.
- Authoring has a playability quality gate: generated questions must include usable
  answer keys, common answer-key aliases are normalized, and provider-backed generation
  gets one repair pass before an invalid draft is rejected.
- Basic authoring ops are implemented:
  `quiz.update_metadata`, `question.update`, `round.update_config`, `items.bulk_set`.
- Live play exists through REST mutations + WebSocket session snapshots:
  - Session/lobby creation with invite codes.
  - Join-by-link.
  - Ready states.
  - Host-controlled start.
  - All-ready lobby countdown with host "Start now" override.
  - Sequential authored-question play; no default 10-question sampling.
  - Text input and multiple-choice submission.
  - Fuzzy judging and score updates.
  - Correct-answer reveal after submission/timeout, including each player's submitted
    text for the active question.
  - Basic session finish flow.
  - Post-game actions: play again, browse same-topic quizzes, or return home.
  - Room chat persists in session state and is available in lobby, play, and finished
    views.
  - Minimal list-race live runner.
  - `/ws/session/<session_id>/` broadcasts fresh session snapshots after join, ready,
    start, answer, advance, and finish mutations.
  - Frontend listens over WebSocket and keeps a slower REST snapshot poll as a fallback.
  - Backend schedules automatic progression on question timeout and when all active
    players have submitted. The host browser no longer owns auto-advance.
  - Late answers after the question deadline are rejected.
- Play UI has a first-pass game-show/stage visual direction:
  - Player-facing Play Hub.
  - Lobby room with large invite code and player tiles.
  - Round intro slate.
  - Live question screen with timer, answer panel, verdict reveal, and bottom score
    chyron.
  - Question prompt card now sizes to content instead of stretching into a large empty
    white panel.

Verified locally:

- `uv run python manage.py makemigrations --check --dry-run`
- `uv run python manage.py migrate`
- `uv run python manage.py test apps.authoring apps.quizzes apps.sessions apps.judging`
- `uv run ruff check apps/authoring apps/quizzes apps/sessions`
- `npm run lint`
- `npm run build`
- Browser QA for authoring lifecycle, Play Hub ready-only catalog, selected draft
  blueprint, live question layout, WebSocket lobby updates, and backend-owned question
  auto-advance/countdown, plus post-game action visibility.

Still not done:

- Fully server-authoritative multiplayer. WebSockets now broadcast snapshots and the
  backend owns basic auto-advance, but REST still performs player actions and the
  scheduler is in-process rather than a durable Redis/Celery-style job runner.
- Proper realtime presence, disconnect/reconnect, host migration, and late-join spectator
  mode. Current player-response reveal is UI-gated, not security-redacted per player.
- Full live support for all answer widgets and round types (`list_input`, `ordering`,
  `matching`, `image_choice`, `hotspot`, full `meta_strategy`, full `buzz_in`).
- Post-game review/replay beyond the current final scoreboard and action buttons.
- Anti-cheat instrumentation/enforcement.
- Accounts/auth polish.
- Public leaderboard and play history.
- Robust LLM op-emitting authoring agent; current generation is mostly full-document
  draft/update plus a few manual ops.
- Docker/runtime validation on the Windows desktop host.

Immediate next priorities:

1. **Presence/disconnect flow**: connection tracking, leave/rejoin behavior, host
   migration, and late-join spectator mode.
2. **Play mechanics polish**: improve locked
   answer states, animate score changes, and make host/non-host controls unambiguous.
3. **Playable widget expansion**: finish live behavior for `list_input`, `ordering`,
   `matching`, `image_choice`, and `hotspot`; keep `list_race` as a first-class round
   type rather than a special case.
4. **Post-game review**: final scoreboard plus per-question answer review. This matters
   because friends will argue about answers.
5. **Deployment validation**: after the play engine is WebSocket-backed, validate Docker,
   Redis/Channels, Caddy, and Cloudflare Tunnel on the desktop host.

---

## Repo layout

```
/
├── docker-compose.yml             # prod / unified stack
├── docker-compose.dev.yml         # dev overrides
├── .env.example
├── README.md
├── SPEC.md
├── IMPLEMENTATION.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml             # poetry or just requirements.txt
│   ├── manage.py
│   ├── trivia/                    # Django project (settings, urls, asgi)
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── asgi.py
│   ├── apps/
│   │   ├── accounts/              # users, profiles, allauth integration
│   │   ├── quizzes/               # Quiz, Round, Question, SourceMaterial
│   │   ├── sessions/              # Session, SessionPlayer, AnswerSubmission, RoundResult
│   │   ├── judging/               # fuzzy match + live LLM judge
│   │   ├── authoring/             # LLM authoring orchestration + op protocol
│   │   ├── anticheat/             # event ingest + threshold logic
│   │   └── realtime/              # Channels consumers, routing, presence
│   ├── prompts/                   # versioned LLM prompts (authoring, judge)
│   └── tests/
│
├── frontend/
│   ├── Dockerfile                 # production: build → static files
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── lib/                   # utilities (cn, time, etc.)
│       ├── api/                   # REST client + WS client
│       ├── components/            # generic UI (shadcn/ui)
│       ├── features/
│       │   ├── auth/
│       │   ├── catalog/
│       │   ├── quiz-editor/       # chat + form editor
│       │   ├── lobby/
│       │   ├── play/              # in-session UI; round-type renderers
│       │   └── review/            # post-game
│       └── routes/                # react-router setup
│
├── caddy/
│   └── Caddyfile
└── cloudflared/
    └── config.example.yml         # user fills in tunnel UUID
```

---

## Dev workflow

### Local laptop development

The Mac laptop is a development machine, not the final host. Keep dependencies project
local:

```bash
cd backend
uv sync --dev
uv run python manage.py runserver
```

This creates `backend/.venv`; it does not install Django or other Python packages into
system Python.

```bash
cd frontend
npm install
npm run dev
```

This creates `frontend/node_modules`.

For early M1 authoring/schema work, the backend may use SQLite when Postgres env vars are
absent. Docker/Postgres/Redis/Cloudflare Tunnel are the Windows desktop/self-host path
and become important once the real-time multiplayer slice needs Channels + Redis.

### Docker / hosted development

**Backend stack** runs in Docker:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```
Brings up postgres, redis, django (ASGI, hot-reload), caddy.

**Frontend dev** runs on the host (faster than dockerized hot-reload):
```bash
cd frontend && npm run dev
```
Vite dev server on `http://localhost:5173`, configured to proxy `/api` and `/ws` to the
backend on `http://localhost:8000`.

**Migrations** / management commands:
```bash
docker-compose exec django python manage.py <cmd>
```

**Tests**:
- Backend: `uv run python manage.py test apps.authoring apps.quizzes apps.sessions apps.judging`
  locally, or the equivalent management command inside the Django container.
- Backend lint: `uv run ruff check apps/authoring apps/quizzes apps/sessions`
- Frontend typecheck/build: `npm run lint` and `npm run build`.

**Production build**:
- `npm run build` produces `frontend/dist/`
- Bind-mounted into the Caddy container; Caddy serves it as the SPA fallback and
  proxies `/api` + `/ws` to Django.

---

## Conventions

- **Backend**: Django apps are feature-scoped (not type-scoped). Models, views,
  serializers, URLs all live inside their app.
- **AI-first product path**: quiz creation starts in the authoring UI. Django admin is
  only a debug/repair path, not the intended content workflow.
- **Interaction-first schema**: questions use `prompt_blocks` + `answer_widget`, not a
  single text prompt. Even if the first playable slice mostly renders text, the data
  model and frontend renderer must support non-text blocks/widgets from the beginning.
- **Async**: views that call the LLM are async (`async def`) and use the configured
  provider's async client. Channels consumers are async by default.
- **DB**: UUIDs everywhere for public-facing IDs; let Postgres pick `gen_random_uuid()`.
- **WebSocket protocol**: JSON messages with a `type` discriminator field. The current
  slice broadcasts whole-session snapshots from `/ws/session/<session_id>/`; a stricter
  event protocol should be introduced when the backend owns timers and round transitions.
- **Frontend**: feature folders own their components, hooks, and state. Shared
  primitives live under `components/`. Routes are thin — just compose features.
- **Type sharing**: the Django side defines the schema; the frontend's TS types are
  hand-mirrored (small enough that codegen isn't worth it for v1). If they drift,
  the WS protocol module is the canary.

---

## Milestone plan

Each milestone produces working software. Don't move to the next until the acceptance
criteria are met.

---

### M1 — Foundation + AI-first authoring skeleton

**Goal**: stack runs end-to-end; data model is created; I can create a playable static
quiz through the product UI by asking the LLM for it, then refine the generated object
in a basic form preview. Django admin exists for debugging only.

**Tasks**:
1. Initialize repo: `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`,
   `.gitignore`, `README.md` with run instructions.
2. Backend container: `python:3.12-slim` base, install Django, Channels, daphne, DRF,
   psycopg, redis, django-allauth, anthropic, python-Levenshtein, pydantic.
3. Django project `trivia/` with ASGI configured for Channels.
4. Apps: `accounts`, `quizzes`, `sessions`, `authoring`, `judging`. (Other apps
   stubbed empty for now.)
5. Models per §9 of SPEC.md, with migrations:
   - `quizzes.Quiz`, `quizzes.Round`, `quizzes.Question`, `quizzes.SourceMaterial`
   - `sessions.Session`, `sessions.SessionPlayer`, `sessions.AnswerSubmission`,
     `sessions.RoundResult`, `sessions.AntiCheatEvent`
   - `quizzes.LeaderboardEntry` (denorm)
6. Register all models in Django admin with reasonable list views.
7. django-allauth wired with email + password; guest-player path (no account) is just a
   `display_name` on `SessionPlayer` with `user_id=null` — no auth flow needed for
   guests until M2.
8. Frontend scaffold: Vite + React + TS + Tailwind + shadcn/ui. Home screen is a
   "New Quiz" authoring workspace, not a placeholder/admin handoff.
9. Prompt/content renderer primitives:
   - `PromptBlocksRenderer` for `text`, `image`, `table`, `math`, `source_excerpt`,
     `diagram_spec` (diagram can render a structured placeholder in M1).
   - `AnswerWidgetRenderer` for `text_input`, `list_input`, `multiple_choice`,
     `ordering`, `matching`, `image_choice`, `hotspot` (non-text widgets can render in
     disabled/preview mode until their game logic lands).
10. Minimal authoring operation protocol (`apps/authoring/ops.py`):
    `quiz.update_metadata`, `round.create`, `question.create`, `question.update`,
    `items.bulk_set`. Ops validate schema invariants and apply transactionally.
11. Minimal provider-neutral authoring endpoint:
    - Input: topic/prompt string + optional pasted source text.
    - Output: static Quiz using the operation protocol.
    - Target in M1: generate at least one synchronized-open-answer round and optionally
      one list-race round. Full four-round authoring quality is M4.
12. Basic quiz editor UI:
    - Chat/instructions panel on the left.
    - Structured preview/form on the right.
    - User can edit title, description, round config, question text/blocks,
      acceptable answers, and judge mode.
13. Caddyfile: proxy `/api/*` and `/ws/*` to django, serve `/` from `frontend/dist/`.
14. Cloudflared config template (gitignored real config).

**Acceptance**:
- `docker-compose up` brings up the stack with no errors.
- `http://localhost:8000/admin/` works for inspection/debugging.
- `http://localhost:5173/` opens the New Quiz workspace and shows the health check
  response somewhere unobtrusive.
- From the product UI, I can type "make a hard quantum mechanics quiz focused on the
  Schrodinger equation" and receive a saved Quiz with at least one playable round,
  questions, canonical answers, acceptable variants, prompt blocks, and answer widgets.
- I can refine the generated quiz in the form preview without touching Django admin.
- Migrations apply cleanly from scratch.

**Notes**:
- No game logic yet. No WebSocket connections from the frontend yet.
- If no OpenAI/Anthropic API key is configured, M1 should expose a deterministic local
  sample generator so the UI can still be developed and tested. The sample path must use
  the same schema and ops as the real LLM path.
- Use `JSONField` for `config`, `acceptable_answers`, `judge_config`, `metadata`,
  `payload`, `prompt_blocks`, `answer_widget`, and structured answer payloads — keeps
  schema flexible.
- Add Postgres indexes on `Session.quiz_id`, `Session.status`,
  `LeaderboardEntry.(quiz_id, best_normalized_score)`.

---

### M2 — Real-Time Play Engine + Core Game Feel

**Goal**: replace the REST/polling prototype with a real server-authoritative multiplayer
engine. Two browser windows should join a session created from an AI-authored **ready**
quiz, play a synchronized-open-answer round end-to-end with live fuzzy-judged scoring,
and see a final scoreboard. The experience should feel like a game: clear pacing, visible
timer pressure, answer lock-in feedback, score movement, and no manual host babysitting
for every question.

**Already in place from the prototype**:
- Create lobby from quiz detail page.
- Join via invite code / URL.
- Player list and ready state.
- Host start button.
- All-ready lobby countdown with host override.
- WebSocket route `/ws/session/<session_id>/` with initial snapshot and mutation
  broadcasts.
- Frontend WebSocket listener with slower REST snapshot fallback.
- Backend-owned auto-advance on all-submit and timeout.
- REST-backed session state machine: lobby → playing → finished.
- Sequential authored-question play; no default random 10-question sampling.
- Text input and multiple-choice answer submission.
- Fuzzy judging and score updates.
- Basic live question screen, timer display, verdict/correct-answer/player-response
  reveal, and score chyron.
- Room chat in lobby, play, and finished views.
- Final screen actions for replay, same-topic browsing, and home.
- Minimal list-race runner.

**Remaining M2 tasks**:
1. Add socket identity and permissions: signed-in user OR a guest token tied to a
   `SessionPlayer`.
2. Server-authoritative hot state:
   - Current round/question.
   - Question start timestamp.
   - Timer deadline.
   - Submitted/locked players.
   - Scores.
   - Connected/disconnected presence.
   Basic current question, deadline, submitted players, and scores are in state now;
   presence still needs real connection tracking.
3. Replace whole-session snapshot broadcasts with a stricter event protocol where that
   helps bandwidth/debuggability; keep REST snapshot fallback on reconnect.
4. Lobby UX upgrades:
   - Presence updates without polling.
   - Ready changes broadcast instantly.
   - Hybrid start: auto-start countdown when all players are ready, plus host "Start
     now" override.
   - Lobby chat panel.
5. WS protocol message types (exhaustive list in `apps/realtime/protocol.py`):
   - `lobby.state`, `lobby.player_joined`, `lobby.player_left`, `lobby.ready_changed`,
     `lobby.chat_message`, `lobby.start_requested`
   - `session.round_started`, `session.question_revealed`, `session.timer_tick`,
     `session.answer_submitted`, `session.answer_judged`, `session.round_ended`,
     `session.session_ended`
   - `chat.message`
6. Server-driven automatic pacing:
   - Question revealed at the same time for all players.
   - Submissions lock per player.
   - Timer expiry auto-closes the question.
   - Advance automatically when all players have submitted or the timer expires.
   - Host can still manually advance during local testing/debug.
7. Synchronized open-answer polish:
   - Keep prompt-block rendering.
   - Keep text input and multiple-choice support.
   - Add clear waiting state after a player locks in.
   - Score bumps animate when `session.answer_judged` arrives.
8. Scoring persistence:
   - On round end/session end, compute raw + normalized score per player.
   - Persist `RoundResult` rows.
   - Broadcast `session.session_ended` with final scoreboard.
9. Frontend game-feel pass:
   - Timer pressure states.
   - Locked-answer state.
   - Correct/wrong reveal animation.
   - Opponent score movement in the chyron.
   - Host/guest state clarity.

**Acceptance**:
- A quiz generated in authoring, marked `ready`, can be used directly for the
  multiplayer test; no Django-admin content creation is required.
- Two browser windows on the same machine can join the same session URL.
- Both see the lobby with each other present in real time; both can mark ready; all-ready
  countdown starts; host can force-start.
- Round starts simultaneously; question appears; both type answers; server judges them;
  live scoreboard updates without polling.
- Question closes automatically on all-submit or timer expiry.
- Round/session end renders a final scoreboard.
- Lobby chat works in both directions.

**Notes**:
- Server is the source of truth for all timers. Clients display the timer based on
  `server_now` deltas, not local clocks.
- `timer_tick` events fire ~1Hz from the server; clients smooth interpolate.
- Keep reconnect simple in M2: reconnect refetches a snapshot and resumes. Sophisticated
  host migration and spectator mode remain M6.
- For M2, don't worry about anti-cheat or live LLM judging. Both are deferred.

---

### M3 — Full round catalog

**Goal**: heterogeneous sessions composing all four round structures work, using the same
prompt-block and answer-widget rendering layer introduced in M1.

**Already in place from the prototype**:
- Prompt-block renderer supports text, image, table, math, source excerpts, and diagram
  placeholders.
- Preview renderers exist for text input, multiple choice, ordering, matching,
  image choice, hotspot, and list-race data.
- Live runner supports text input and multiple choice through the standard submission
  path.
- A minimal live list-race runner can start, accept fuzzy-matched items, and score them.

**Tasks**:
1. Promote the M1 preview widgets into playable widgets where needed:
   - `list_input` gets a live multi-answer input renderer outside list-race.
   - `multiple_choice` is already playable; polish keyboard navigation and selected/
     locked state.
   - `ordering`, `matching`, `image_choice`, and `hotspot` keep validated payload shapes
     even if only basic scoring is implemented in v1.
2. **List race** (`apps/sessions/rounds/list_race.py` + `features/play/list-race/`):
   - Move current minimal list-race logic into a dedicated state-machine module.
   - Per-player `accepted_items: set` held server-side.
   - On each `answer_submitted`, fuzzy-match against round `items`; if matched and not
     already in the player's set, accept and broadcast `session.list_item_accepted`
     (with `player_id`, `canonical`, `new_count`).
   - Live opponent counters in the UI.
   - End condition: timer expires OR a player gets all items.
3. **Meta-strategy** (`rounds/meta_strategy.py`):
   - Two-phase state: `betting` → `answering`.
   - `betting`: server reveals category hint; each player submits a `place_bet` action
     within `bet_window_s`. Default bet on timeout = `min_bet`.
   - `answering`: question revealed; each player submits an answer within
     `answer_timeout_s`. Fuzzy- or LLM-judged.
   - Score: `bet × correctness` (with `wrong_penalty` policy).
4. **Buzz-in** (`rounds/buzz_in.py`):
   - Authoritative buzz resolution: each `buzz_requested` carries a client timestamp
     for diagnostics, but server orders by server-receive time.
   - First valid buzz → `session.buzz_locked` broadcast; lockout for non-buzzers.
   - Buzzing player gets `answer_window_s`; correct → score; wrong → `lockout_cooldown`
     and others can buzz.
   - Skip on `buzz_timeout_s` with no buzz.
   - N=1: skip the buzz phase, treat as sync open-answer (per SPEC §3.3).
5. Per-round scoring + 0–100 normalization. Session-mean for final winner. Tie-break
   per SPEC §4.
6. UI: round-type-specific renderers under `features/play/<round-type>/`. Shared
   `RoundContainer` handles transitions and the score panel.

**Acceptance**:
- A test quiz with one round of each type runs end-to-end; final scoreboard correctly
  averages normalized scores; tie-break logic is exercised.
- Buzz-in race is consistent under reasonable network conditions (test with browser
  devtools throttle).
- Solo (N=1) play of a buzz-in round degenerates to sync open-answer.

**Notes**:
- Each round type has its own state machine. Keep them in separate modules; share only
  the `RoundResult` write path.

---

### M4 — Authoring depth + live LLM judging

**Goal**: the M1 authoring skeleton becomes a strong creative tool. "Make me a hard
quantum mechanics quiz, 4 rounds, mix of list race and meta-strategy" produces a polished
playable quiz via chat; the form editor stays in sync; live LLM judging works for opt-in
questions.

**Tasks**:
1. LLM provider hardening (`apps/authoring/llm.py`):
   - Configured strong model for authoring; configured fast/cheap model for live judging.
     Exact model IDs are selected and verified at implementation time.
   - Prompt caching on the system prompt + schema definition + source material.
   - Streaming for the chat UI.
2. Complete authoring operation protocol (`apps/authoring/ops.py`):
   - Each op listed in SPEC §6.2 implemented as a function:
     `def apply_op(quiz, op) -> Quiz`.
   - Validation: each op checked against schema invariants before applying.
   - Atomic: ops applied inside a DB transaction.
3. LLM tool definitions matching the op list, fed to the authoring model. The chat agent
   loops until it stops calling tools.
4. Quiz editor UI (`features/quiz-editor/`):
   - Two-pane: chat panel (left) + form editor (right).
   - Both subscribe to the same `Quiz` state (REST + targeted refetch after each op).
   - Form actions call REST endpoints that wrap the same op functions.
5. Source material UX (v1 scope): paste text + topic string only. PDF deferred to v1.5.
6. Live LLM judging (`apps/judging/llm_judge.py`):
   - Called only for questions with `judge_mode = "llm"`.
   - Inputs: question, canonical answer, player's typed answer, strictness setting.
   - Per-session answer cache: `(question_id, normalized_answer) → verdict`.
   - Async; the WS broadcast for `session.answer_judged` waits on the future.
7. Prompts (`backend/prompts/`):
   - `authoring_system.txt` — describes the schema, op palette, design principles.
   - `judge_system.txt` — strict / lenient variants, JSON output spec.
   - Few-shot examples per round type committed to the repo.

**Acceptance**:
- Chat prompt produces a valid, polished quiz with all four round types represented.
- Form edits are reflected in the same underlying quiz (no divergence).
- Live LLM judging works on a question marked `judge_mode: "llm"`; non-trivial
  paraphrases are accepted; clearly-wrong answers are rejected.
- Prompt caching is verified (check API response usage stats — second authoring call
  on the same quiz should show cache hits).

**Notes**:
- Streaming is nice-to-have for chat; if it's a hassle, ship non-streaming first.
- Per-session judge cache survives only as long as the session — no global cache, to
  avoid baked-in mistakes.

---

### M5 — Anti-Cheat, Review, Public Catalog

**Goal**: the product feels like a finished v1.

**Already in place from earlier milestones**:
- Player-facing Play Hub lists `ready` quizzes.
- Authoring exposes category and lifecycle status.
- Drafts are hidden from the Play Hub by default.
- Category filters exist for the local catalog experience.

**Tasks**:
1. Anti-cheat browser instrumentation (`frontend/src/lib/anticheat.ts`):
   - Page Visibility API listener.
   - `onpaste` handler on every answer input.
   - Keystroke cadence recorder (timestamps + deltas) — sent at answer-submit time.
2. Anti-cheat server (`apps/anticheat/`):
   - WS message type `anticheat.event` ingested into `AntiCheatEvent`.
   - Hard-signal enforcement at question scoring time (paste during active question →
     auto-reject; tab blur during active question → forfeit).
   - Soft-signal aggregation broadcast (`session.anticheat_indicator`) for opponent UI.
3. Quiz schema gets `anticheat_strictness`; UI exposes it as a preset selector in the
   editor.
4. Post-game review (`features/review/`):
   - Final scoreboard with normalized + raw scores per round.
   - Per-question results: prompt, each player's answer, accepted/rejected, time-to-
     answer, judge mode.
   - Anti-cheat summary: counts per signal type per player.
   - "Play again" button → new session, same quiz, returns players to a fresh lobby.
5. Public catalog / browse polish (`features/catalog/` or expanded Play Hub):
   - Catalog lists public `ready` quizzes with title, author, category, topic,
     round-type icons, popularity (play count).
   - Per-quiz detail page with leaderboard (top scores, paginated).
   - LeaderboardEntry write at `RoundResult` finalization.
6. Visibility/publishing polish:
   - Existing `visibility` field becomes meaningful in browse surfaces.
   - Private ready quizzes remain playable by direct selection/share but are not public.
   - Public ready quizzes appear in public browse mode.

**Acceptance**:
- Playing with anti-cheat ON: tab-blurring during a question forfeits that question;
  pasting an answer is auto-rejected; opponent sees soft indicators in real time.
- Playing with anti-cheat FRIENDLY: hard signals downgrade to soft; nothing is
  enforced but everything is visible.
- Post-game review renders correctly for a mixed-round session.
- Public catalog lists at least one public test quiz; clicking it shows the
  leaderboard.

---

### M6 — Polish & edge cases

**Goal**: ship to friends with confidence.

**Tasks**:
1. Disconnect/reconnect snapshot logic:
   - WS reconnect handler refetches current session state.
   - Server tolerates rapid reconnects; idempotent join handling.
   - The "no-pause" rule from SPEC §7.4 is already the default behavior; verify it
     holds across all four round types under disconnect tests.
2. Spectator mode (late-join):
   - Joining after `status=playing` admits as `SessionPlayer` with `role="spectator"`.
   - Spectator UI hides answer inputs and shows everything else (questions, scores,
     chat).
3. Solo (N=1) UX polish:
   - "Play solo" button on each quiz detail page.
   - Buzz-in degenerate mode UI explicitly says "buzz-in (solo): answer within Xs".
   - Solo leaderboard entries clearly marked alongside multiplayer ones.
4. Error states:
   - LLM call failure → user-visible error in authoring; partial quiz state rolled back.
   - WS disconnect banners on each client.
   - Quiz with no rounds → cannot create session (validation).
5. Deployment:
   - Production `docker-compose.yml` (no dev overrides).
   - Cloudflare Tunnel: documented setup, sample `config.yml`.
   - `.env` template with all required vars (LLM provider key, Django secret, DB
     password, etc.).
   - README with "first-time setup" + "running" sections.
6. Smoke-test checklist runs cleanly end-to-end before declaring v1 done.

**Acceptance**:
- Friend can hit the Cloudflare Tunnel URL, sign up or guest-join, and play a full
  session of a quiz I made, including all four round types, with anti-cheat on.
- Disconnect mid-session and reconnect within the question timer → can still answer.
- Solo play of any quiz writes a leaderboard entry.

---

## Deferred (v1.5 / v2 — not in this plan)

Listed in SPEC §11 — PDF source material, URL ingestion, scrubbable replays, mobile
polish, quiz versioning, always-on catalog companion. Not addressed in this plan;
revisit once v1 ships.

## Open from SPEC §12

Implementation-time parameter tuning that gets baked in as we build:
- LLM prompt drafts → land in `backend/prompts/` during M4.
- Fuzzy-match thresholds → defaults proposed in M2, tune in M5.
- Anti-cheat thresholds → defaults proposed in M5, tune empirically.
- Frontend state lib → decide at start of M2 (likely Zustand; small surface, no
  Redux ceremony, plays well with WS).
- Session GC policy → decide before deployment in M6 (probably a cron task that prunes
  finished `Session.events` older than 30 days; leaderboard rows persist forever).
