# Trivia — Multiplayer Quiz Engine

**Status**: Partial design spec. Settled sections are described in depth; open questions are
marked **TBD** with notes on what still needs to be decided.

---

## 1. Vision

A self-hosted, browser-based, real-time multiplayer trivia game for small groups of friends
(2–8 players). Quizzes are **LLM-authored** from a topic and/or source material, then stored
as **static, reusable artifacts** that can be replayed and leaderboarded.

What differentiates this from existing trivia apps:

- **Heterogeneous sessions**: a single match composes any mix of round structures
  (meta-strategy point-betting, Sporcle-style list races, buzz-in, synchronized open-answer).
  The engine's central abstraction is a schema that expresses these as composable rounds.
- **LLM-authored content with real depth**: the LLM authors the quiz at creation time,
  generating questions, answer keys, and acceptable-answer variants. Authors can ground
  the LLM in their own source material (notes, PDFs, etc.) to escape the "shallow stock
  trivia" failure mode of general-purpose trivia apps.
- **LLM-as-judge for open answers (opt-in)**: per-question, the author can choose between
  fast pre-cached fuzzy matching (default) or live LLM judging (for conceptual/explanatory
  answers where variants can't be enumerated).
- **Generative-UI authoring protocol**: quizzes are edited via a structured protocol that
  both an LLM (via chat) and a form-based editor speak. The LLM has no special powers —
  it just emits the same operations a human would.
- **Active browser-native anti-cheat**: hybrid soft/hard signals; intended for competitive
  play between friends who trust each other but still want fair matches.

Non-goals for v1:
- Kahoot-scale (host + N participants) classroom mode.
- Solo "investigation mode" inspired by Sapolsky lectures. This is a separate product;
  the multiplayer engine focuses on competitive play.
- Mobile-native apps. Browser-only.

---

## 2. Core Concepts

| Concept | Definition |
|---|---|
| **Quiz** | A static, reusable artifact authored once. Contains an ordered list of Rounds. Has a visibility (private / public). |
| **Round** | One segment of a Quiz with a single round-type (meta-strategy, list race, buzz-in, sync open-answer). Has its own config and an ordered list of Questions. |
| **Question** | A single interactive challenge with prompt content, an answer widget, a canonical answer, acceptable variants, and a judge mode (fuzzy / llm). It is not assumed to be plain text. |
| **Prompt Block** | A renderable piece of question content: text, image, table, code/math, diagram placeholder, audio/video embed, or source excerpt. The frontend renders known block types; the LLM can only emit blocks from the schema. |
| **Answer Widget** | The player's interaction surface: text input, list-entry input, multiple choice, ordering, matching, image choice, hotspot/click target, slider, or future custom widgets. |
| **Source Material** | Optional grounding text/PDF/URL the LLM uses at authoring time. Stored alongside the Quiz so re-authoring is reproducible. |
| **Session** | A live multiplayer play of a Quiz. Has 2–8 Players, a status (lobby / playing / finished), and a sequence of recorded events. |
| **Player** | A participant in a Session. May be an anonymous guest (display name only) or a signed-in User. |
| **User** | A persistent account. Owns authored Quizzes and accumulates play history & leaderboard entries. |

---

## 3. Round Structures (v1)

All four are supported in v1. A Session composes them in any order.

Round structures define timing, sequencing, multiplayer state, and scoring. They do **not**
force questions to be text-only. Each question carries its own `prompt_blocks` and
`answer_widget`, so a synchronized open-answer round can show a diagram, a meta-strategy
question can include an image after reveal, and a future flag quiz can use image prompts
without changing the multiplayer engine.

### 3.1 Meta-Strategy (point-betting)

The mode the user already enjoyed in the existing app. Flow per question:

1. Player sees a **category hint** (one short phrase) but not the question.
2. Player commits a **bet** between `min_bet` and `max_bet` (default 1–10) within a
   short timer (default ~10s).
3. The question is revealed; player has `answer_timeout_s` to answer (default ~20s).
4. Correct answer awards the bet; wrong/no answer awards 0 or `−bet` per config
   (`wrong_penalty: "zero" | "negative"`).

Config:
```
{
  "category_hint": "Foundations of QM",
  "bet_window_s": 10,
  "answer_timeout_s": 20,
  "min_bet": 1,
  "max_bet": 10,
  "wrong_penalty": "zero",
  "answer_format": "open" | "multiple_choice"
}
```

Scoring within the round: raw points = sum of (bet × correctness). Normalized to 0–100
by dividing by the theoretical max (sum of `max_bet × num_questions`).

### 3.2 List Race (Sporcle-style)

Flow per round:

1. A single prompt appears: "Name all 30 MLB stadiums."
2. Shared timer starts (default 5 minutes).
3. Both players type into their own input box; each accepted entry strikes through that
   item on a hidden master list and increments their own score.
4. Live side-by-side counters. Round ends when the timer hits 0 or one player completes
   the list.

Config:
```
{
  "prompt": "Name all 30 MLB stadiums",
  "time_limit_s": 300,
  "items": [
    {"canonical": "Yankee Stadium", "acceptable": ["yankees", "yankee", "yankee stadium"]},
    ...
  ],
  "case_sensitive": false
}
```

Scoring within the round: raw points = number of items correctly named. Normalized to
0–100 by dividing by total item count (so getting all items = 100, none = 0).

### 3.3 Buzz-In

Flow per question:

1. Question is broadcast to all players simultaneously.
2. Any player can "buzz" by hitting a hotkey or button. First buzz locks out the others.
3. Buzzing player has `answer_window_s` to answer (default ~7s).
4. Correct: scores the question's points. Wrong: lockout penalty (player can't buzz for
   the next question, or a fixed cooldown). Other players can buzz once the wrong
   answer resolves.
5. If no one buzzes within `buzz_timeout_s` (default ~15s), the question is skipped.

**Solo (N=1) behavior**: with only one player, the buzz race degenerates — the round
behaves as a synchronized open-answer round (§3.4). The player must answer within
`answer_window_s`; an optional speed bonus scales the points by time-to-answer.

Config:
```
{
  "answer_window_s": 7,
  "buzz_timeout_s": 15,
  "wrong_penalty": "lockout_next_question" | "cooldown_s",
  "lockout_cooldown_s": 10,
  "points_per_question": 10
}
```

Scoring: raw = sum of points won. Normalized to 0–100 by dividing by total points
available.

**Latency note**: buzz-in is the round structure most sensitive to network latency.
Implementation must use authoritative server-side timestamps (client claims a buzz time,
server verifies/resolves with its own monotonic clock). See §7.

### 3.4 Synchronized Open-Answer

Flow per question:

1. Question appears for all players simultaneously.
2. All players have `answer_timeout_s` to type an answer (default ~20s).
3. Answers are revealed/scored after the timer.
4. Both players can score independently — it's not "first wins."

Config:
```
{
  "answer_timeout_s": 20,
  "points_per_question": 10,
  "speed_bonus": true,
  "speed_bonus_curve": "linear"
}
```

If `speed_bonus` is on, points scale from a floor (e.g., 50% of `points_per_question`)
at the last second to full points at the first second.

Scoring: raw = sum of points won. Normalized as above.

---

## 4. Session Composition & Scoring

A Quiz declares an ordered list of Rounds. A Session plays them in declared order.

**Solo (N=1) sessions are allowed in v1.** A player can open any Quiz alone — for
authoring play-tests, practice, or solo leaderboard climbing. The engine doesn't
require N≥2. Round types that depend on multiplayer dynamics (buzz-in) degenerate
gracefully (see §3.3). Solo plays write to the same leaderboard as multiplayer plays —
your normalized score is your normalized score regardless of opponent count.

### Per-round scoring

Each round normalizes to a **0–100 round score per player** as defined in §3.

### Session winner

Session score per player = **arithmetic mean of round scores**. Highest mean wins.

Two scoreboards are surfaced in the UI:
- **Round-internal raw points** during play (preserves the "I bet 10 and won!" drama).
- **Session-level normalized 0–100** at round transitions and game end (the actual win
  condition).

Tie-breaking: if mean scores tie, the player who won the most individual rounds wins. If
still tied, the player with the highest single-round normalized score wins. Else,
declared a draw.

---

## 5. Question Judging

Every question carries a `judge_mode`:

### `fuzzy` (default)

At authoring time, the LLM generates an `acceptable_answers` list including:
- The canonical answer
- Common synonyms / paraphrases
- Likely typos and casing variants
- Domain-specific aliases (e.g., "JFK" for "John F. Kennedy")

At play time, the player's typed answer is:
1. Lowercased and stripped.
2. Compared via case-insensitive exact match, then Levenshtein distance ≤ N (configurable
   per question), against each item in `acceptable_answers`.
3. Match → accepted. No match → rejected.

Verdict latency: <50ms, no external calls.

### `llm` (opt-in)

For conceptual/explanatory answers where variants can't be enumerated (e.g., "Why doesn't
this experiment actually prove X?"). At play time:

1. Player's answer is shipped to the configured fast/cheap judge model with the question,
   canonical answer, and a strictness prompt.
2. Judge returns `{accepted: bool, confidence: float, reasoning: string}`.
3. Verdict latency: typically 0.5–2s.

Per-session, identical answer strings to the same question are cached (so retries during
a session don't re-pay).

### When to use which

- List race: **always fuzzy** (latency would destroy the typing flow).
- Buzz-in: **fuzzy** unless the answer is conceptual.
- Synchronized open-answer: **either**, per question.
- Meta-strategy: **either**, per question.

The author picks per-question; a round-level default is settable in the editor.

---

## 6. Authoring Protocol

The Quiz is a JSON document. Both the chat-LLM authoring flow and the form-based editor
emit operations against the same protocol, ensuring symmetry.

### 6.1 Quiz schema (illustrative)

```json
{
  "id": "qz_abc123",
  "schema_version": 1,
  "title": "Quantum Mechanics — Hard",
  "description": "Focus on the Schrödinger equation and core formalism.",
  "topic": "quantum mechanics",
  "difficulty": "hard",
  "visibility": "private",
  "author_id": "usr_xyz",
  "source_material_id": "src_456",
  "rounds": [
    {
      "id": "rd_1",
      "type": "list_race",
      "config": { "prompt": "Name all six quarks", "time_limit_s": 60 },
      "items": [
        { "canonical": "up",      "acceptable": ["up", "u"] },
        { "canonical": "down",    "acceptable": ["down", "d"] },
        { "canonical": "charm",   "acceptable": ["charm", "c"] },
        { "canonical": "strange", "acceptable": ["strange", "s"] },
        { "canonical": "top",     "acceptable": ["top", "t", "truth"] },
        { "canonical": "bottom",  "acceptable": ["bottom", "b", "beauty"] }
      ]
    },
    {
      "id": "rd_2",
      "type": "meta_strategy",
      "config": {
        "bet_window_s": 10,
        "answer_timeout_s": 20,
        "min_bet": 1,
        "max_bet": 10,
        "wrong_penalty": "zero"
      },
      "questions": [
        {
          "id": "q_1",
          "category_hint": "Foundations",
          "prompt_blocks": [
            {
              "type": "text",
              "text": "What does the time-dependent Schrödinger equation describe?"
            }
          ],
          "answer_widget": {
            "type": "text_input",
            "placeholder": "Type a concise conceptual answer"
          },
          "canonical_answer": "the time evolution of a quantum system's wavefunction",
          "acceptable_answers": [
            "time evolution of the wavefunction",
            "how wavefunctions evolve in time",
            "evolution of a quantum state over time"
          ],
          "judge_mode": "llm",
          "judge_config": { "strictness": "lenient" }
        }
      ]
    }
  ]
}
```

### 6.2 Operations

Both the LLM (via tool calls) and the form-editor (via UI actions) emit these operations.
Server validates each against the schema and applies it transactionally to the Quiz.

| Operation | Purpose |
|---|---|
| `quiz.update_metadata(patch)` | Title, description, topic, difficulty, visibility. |
| `quiz.set_source_material(material_id)` | Attach/detach source. |
| `round.create(type, config, position)` | Add a new round. |
| `round.delete(round_id)` | Remove a round. |
| `round.reorder(round_id, new_position)` | Move a round. |
| `round.update_config(round_id, patch)` | Patch the round's config. |
| `question.create(round_id, question, position)` | Add a question to a round. |
| `question.delete(question_id)` | Remove a question. |
| `question.update(question_id, patch)` | Patch question fields. |
| `question.regenerate(question_id, instructions)` | Ask the LLM to redo this question. |
| `question.regenerate_acceptable_answers(question_id)` | Refresh the variants list. |
| `items.bulk_set(round_id, items)` | For list-race: replace the items list. |

The LLM has access to all of these as tool calls. Form actions trigger them via REST
endpoints.

### 6.3 Authoring flow

AI-assisted authoring is the default product path. Django admin/manual entry exists for
debugging and emergency repair, not as the intended user workflow.

1. User opens "New Quiz" → chat panel + live structured preview/form side by side.
2. User describes what they want; the LLM emits a sequence of operations to construct the
   quiz. Form view updates reactively as each op is applied.
3. User can edit any field directly in the form (emits the same ops). Can also ask the
   LLM to revise: "make round 3 harder," "regenerate question 7," "swap round 1 and 2."
4. Quiz is saved. Author can mark public/private.

### 6.4 Interactive content schema

To keep the UI from becoming a text-only app, questions are authored as renderable
blocks plus an explicit interaction widget.

Initial prompt block types:
- `text` — rich-enough text with optional Markdown/math rendering.
- `image` — uploaded, generated, or externally referenced image with alt text.
- `table` — structured rows/columns, useful for science/history/comparison prompts.
- `math` — LaTeX block for equations.
- `source_excerpt` — quoted material from uploaded/pasted source.
- `diagram_spec` — structured instruction for a frontend-rendered diagram/canvas
  component. The LLM does not emit arbitrary HTML.

Initial answer widget types:
- `text_input` — single answer, fuzzy or LLM judged.
- `list_input` — many accepted answers, Sporcle-style.
- `multiple_choice` — fixed choices, single or multi-select.
- `ordering` — drag items into sequence.
- `matching` — pair terms with definitions/images.
- `image_choice` — select one or more images.
- `hotspot` — click a region on an image/diagram.

The frontend renders only known block/widget types. If the LLM wants a new interaction,
it must compose these primitives or the operation is rejected. This keeps the product
generative without letting the model invent unsafe or unimplemented UI.

### 6.5 LLM models & prompts (TBD details)

- **Authoring**: a strong structured-output model from the configured provider
  (OpenAI or Anthropic). Prompt caching/reuse should be enabled where the provider
  supports it for the system prompt + source material + schema definition.
- **Judge (live)**: a fast/cheap model from the configured provider. Short prompt, low
  temperature, JSON output.

Exact model IDs are selected and verified during implementation so the code follows the
current provider APIs rather than freezing stale names in the spec.

Prompt design and few-shot examples are **TBD** — to be drafted in a separate
`prompts/` directory during implementation.

---

## 7. Multiplayer Flow

### 7.1 Lobby

1. Host creates a Session by picking a Quiz; gets a session URL.
2. Host shares URL out-of-band (Discord, SMS).
3. Joiners open URL → enter display name → land in lobby as a **player**.
4. Lobby shows: quiz preview (title, round summary, estimated duration, anti-cheat
   strictness), connected participants (players + spectators), per-player ready states,
   and a chat panel.
5. **Start mechanism (hybrid)**: each player has a "Ready" button. Once *all* players
   are ready, the session auto-starts after a brief countdown. The host additionally
   has a **"Start now"** override button to force-start even if not everyone is ready.
6. **Host role**: the session creator is the host. The host's only privileges are the
   force-start button (lobby) and any future host-only actions (none defined for v1).
7. **Host drops in lobby**: if the host disconnects from the lobby and doesn't return
   within **60 seconds**, the host role auto-migrates to the longest-tenured remaining
   player. They inherit the force-start button.
8. **Idle lobby**: if a lobby sits with no participants for 5 minutes, it's
   auto-abandoned.

### 7.2 Late joiners → spectators

Once the session enters the `playing` state, the URL stops accepting new **players**.
Anyone opening the URL after start is admitted as a **spectator**.

Spectators:
- See live game state (current question, scores, timers).
- Cannot submit answers, buzz, or affect scoring.
- Can read and post in chat (same chat as players).
- Appear in the participant panel with a clear "spectator" label.

Spectators can join in the lobby phase too — anyone who joins by clicking the URL is
defaulted to "player" while in lobby; they can opt down to spectator. There's no
spectator cap in v1 (generous; we can add one later if abuse is an issue).

### 7.3 In-session synchronization

All clients are stateless thin renderers. The server (Django Channels) holds the
authoritative Session state. Every state transition (round started, question revealed,
answer submitted, buzz received, timer expired) is computed server-side, persisted, and
broadcast over WebSocket.

**Authoritative timestamps**: the server uses its monotonic clock for all timing
decisions (buzz-in resolution, answer timeouts, list-race timer). Clients send their
own local timestamps for latency measurement but never as the source of truth.

### 7.4 Disconnect & reconnect

The session **never pauses** for a disconnect. Question timers and round timers continue
to run normally. Reconnect behavior follows from this single rule:

- **Mid-question**: if the player reconnects before the current question's timer
  expires, they can still submit an answer. If they reconnect after the timer expires,
  the question has already auto-forfeited (treated as silence → wrong / 0 points), and
  they rejoin at whatever the session has progressed to.
- **Mid-list-race**: list-race rounds have their own multi-minute timer. Server holds
  the authoritative per-player list of accepted entries. On reconnect, the client
  receives the current accepted set and the player resumes typing.
- **Between questions / between rounds**: the reconnecting client receives a state
  snapshot and is caught up instantly.
- **Buzz-in**: if disconnected during a buzz-in question, the player simply can't buzz
  during that window. Other players play normally.
- **Meta-strategy**: if disconnected during the bet window, the player's bet defaults to
  the minimum bet for that question. If they reconnect before `answer_timeout_s`
  expires, they can still answer; otherwise the question auto-forfeits.

This rule means no special pause-and-resume state machine is required — the timer-driven
scoring handles drops correctly on its own.

**Host drops mid-session**: same rule as any other player. The host privilege (force-
start in lobby) is irrelevant once the session has started.

### 7.5 End of session: post-game review

When the final round ends:

1. Players are taken to a **post-game review** screen showing:
   - Final session scoreboard (normalized 0–100 per round, mean for session winner).
   - Per-round breakdown with raw and normalized scores.
   - **Per-question results**: each question shown with what each player typed, whether
     it was accepted, how long it took, and which judge mode was used. (Especially
     useful for "wait, that was right" arguments after LLM-judged questions.)
   - **Anti-cheat summary**: counts of soft signals, list of hard penalties applied.
2. A **"Play again"** button starts a new Session against the same Quiz, with all
   current players returned to a fresh lobby.

Scrubbable timeline-style replays (watch the session play back like a video) are
out of v1 scope and deferred to v2.

---

## 8. Anti-Cheat

Hybrid model:
- **Soft signals** are visible to all players in real time but carry no automatic
  penalty. Social pressure is the consequence.
- **Hard signals** trigger automatic penalties enforced by the engine.

### Signal catalog

| Signal | Severity | Default consequence |
|---|---|---|
| Tab/window blur during active question | **Hard** | Answer for that question forfeited |
| Tab/window blur between questions | Soft | Indicator on opponent panel ("Player B left for 12s") |
| Paste event on answer input | **Hard** | Answer rejected with "pasted answer" flag |
| Suspiciously fast correct answer on hard question | Soft | Flagged in post-game review |
| Keystroke cadence inconsistent with claimed typing | Soft | Logged, surfaced in post-game review |
| Multiple rapid focus changes | Soft | Counter visible on opponent panel |

### Configuration

The Quiz schema includes an `anticheat_strictness` field with three presets:
- `strict` — all signals enforced as listed.
- `friendly` — hard signals downgrade to soft (visible only).
- `off` — no signals collected.

### Display

Each player has an "anti-cheat indicator" panel for every opponent, showing:
- Current focus state (live)
- Cumulative blur events this session
- Last action (typing / blurred / pasted)

### Implementation

Browser APIs:
- `document.visibilityState` + `visibilitychange` event
- `window.blur` / `window.focus` events
- `onpaste` handler on answer inputs
- `keydown` / `keyup` for cadence tracking

Events are batched and sent over the same WebSocket as game events. Server records them
on the Session.

---

## 9. Data Model

PostgreSQL via Django ORM. Tables:

### `users` (Django built-in)
Standard Django `auth_user` plus a profile table for display name.

### `quizzes`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| title | text |  |
| description | text |  |
| topic | text |  |
| difficulty | text | enum: easy/medium/hard |
| visibility | text | enum: private/public |
| author_id | FK users | nullable (guest-authored quizzes can persist if claimed later) |
| source_material_id | FK source_materials | nullable |
| anticheat_strictness | text | enum: strict/friendly/off |
| schema_version | int | for future migrations |
| created_at, updated_at | timestamp |  |

### `rounds`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| quiz_id | FK quizzes |  |
| order | int |  |
| type | text | enum: meta_strategy/list_race/buzz_in/sync_open |
| config | jsonb | round-type-specific (see §3) |

### `questions`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| round_id | FK rounds |  |
| order | int |  |
| prompt_blocks | jsonb | renderable prompt content blocks |
| answer_widget | jsonb | answer interaction definition |
| canonical_answer | text |  |
| acceptable_answers | jsonb | list of strings |
| judge_mode | text | enum: fuzzy/llm |
| judge_config | jsonb |  |
| metadata | jsonb | category hints, point values, etc. |

(For `list_race` rounds, the round itself holds an `items` array in its config — there's
no separate Question row per item. This keeps the list-race authoring ergonomic.)

### `source_materials`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| kind | text | enum: topic/text/pdf/url |
| content | text | extracted/normalized text |
| original_url | text | nullable |
| uploaded_by | FK users | nullable |
| created_at | timestamp |  |

### `sessions`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| quiz_id | FK quizzes |  |
| status | text | enum: lobby/playing/finished/abandoned |
| host_id | FK users | nullable (guest host) |
| created_at, started_at, ended_at | timestamp |  |
| current_round_idx | int |  |
| current_question_idx | int |  |

### `session_players`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| session_id | FK sessions |  |
| user_id | FK users | nullable (guest) |
| display_name | text |  |
| is_host | bool |  |
| joined_at, left_at | timestamp |  |

### `answer_submissions`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| session_id | FK sessions |  |
| question_id | FK questions | nullable for list-race items |
| round_id | FK rounds |  |
| player_id | FK session_players |  |
| submitted_text | text |  |
| submitted_payload | jsonb | nullable; structured answers for non-text widgets |
| accepted | bool |  |
| points_awarded | int |  |
| judge_mode_used | text |  |
| judge_latency_ms | int |  |
| judge_metadata | jsonb |  |
| submitted_at | timestamp |  |

### `round_results`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| session_id | FK sessions |  |
| round_id | FK rounds |  |
| player_id | FK session_players |  |
| raw_score | float |  |
| normalized_score | float | 0–100 |
| completed_at | timestamp |  |

### `anticheat_events`
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| session_id | FK sessions |  |
| player_id | FK session_players |  |
| kind | text | tab_blur / paste / fast_answer / cadence_anomaly |
| severity | text | soft / hard |
| question_id | FK questions | nullable |
| payload | jsonb |  |
| occurred_at | timestamp |  |

### `leaderboard_entries` (denormalized for fast catalog queries)
| Column | Type | Notes |
|---|---|---|
| quiz_id | FK quizzes |  |
| user_id | FK users |  |
| best_normalized_score | float |  |
| plays_count | int |  |
| last_played_at | timestamp |  |
| PK | (quiz_id, user_id) |  |

---

## 10. Tech Stack & Deployment

### Backend
- **Django** + **Django Channels** (ASGI, WebSocket support)
- **Django REST Framework** for the REST surface (quiz CRUD, catalog, auth, leaderboards)
- **django-allauth** for optional sign-in (light accounts)
- **Provider-neutral LLM layer** backed by either the OpenAI Python SDK or Anthropic
  Python SDK. Use a stronger model for authoring and a cheaper/faster model for live
  judging. Prompt caching/reuse should be enabled where supported. Exact model IDs are
  verified during implementation.
- Async views for LLM calls (inline; add `django-rq` later if quiz authoring needs
  background execution).

### Frontend
- **Vite + React + TypeScript**
- **Tailwind CSS** + **shadcn/ui** primitives
- WebSocket client speaking the same JSON protocol as Channels consumers
- Reactive state via Zustand or similar (TBD — pick during implementation)

### Database
- **PostgreSQL** (single instance, no read replicas needed for v1)

### Real-time layer
- **Redis** as the Channels layer (and incidental cache)

### Reverse proxy / TLS
- **Caddy** in front, serves the built React bundle as static files and proxies API +
  WebSocket to the Django ASGI server

### Deployment
- `docker-compose.yml` with services: `django`, `postgres`, `redis`, `caddy`,
  `cloudflared` (Cloudflare Tunnel sidecar). All run on the user's self-hosted desktop.
- Cloudflare Tunnel terminates HTTPS at Cloudflare's edge; internal traffic is HTTP.

### External dependencies
- OpenAI or Anthropic API — only external service for runtime LLM calls
- Cloudflare Tunnel — only external service for network exposure

---

## 11. Phasing / Roadmap

### v1 (target for first playable build with friends)
- All four round structures
- Static quizzes, AI-assisted authoring as the default creation path, with **topic
  string** and **pasted text** source inputs
- Interactive prompt/content schema with text, image, table, math/source excerpt blocks
  and text/list/multiple-choice/ordering/matching/image-choice/hotspot answer widgets
- Pre-cached fuzzy judging + opt-in live LLM judging per question
- Light accounts (guest + optional sign-in)
- Public/private toggle + a minimal browsable catalog page (degraded availability:
  catalog up only when host is up; accepted limitation of self-hosting)
- Hybrid anti-cheat (browser-native signals)
- Hybrid lobby start (all-ready + host force-start); host migration after 60s drop
- No-pause disconnect/reconnect model (§7.4)
- Late-joiner spectator mode (minimal: watch + chat, no playing)
- Solo play (N=1) supported — same engine, no special mode
- Static post-game review (per-question results, anti-cheat summary)
- Quiz edits are in-place (no versioning machinery)
- Lobby + in-session chat for all participants
- Self-hosted via docker-compose + Cloudflare Tunnel

### v1.5
- PDF source material upload (with extraction pipeline)
- Catalog: search, categories, tags, sort by popularity
- Per-quiz leaderboards with global + friends-only filters
- Spectator polish (cap, controls, dedicated spectator-chat option)

### v2
- URL source material (Wikipedia, articles, YouTube transcripts)
- Scrubbable timeline replays (full event playback)
- Mobile-responsive polish (responsive UI from v1, but native-quality only in v2)
- Quiz versioning / fork-on-publish (if leaderboard fairness drift becomes a real issue)
- Optional always-on companion service for catalog availability when host is down

### Out of scope (separate product)
- "Investigation mode" — Sapolsky-style guided study from video lectures. Different
  product surface; would reuse the LLM authoring layer but not the multiplayer engine.

---

## 12. Open Questions

Remaining items deferred to implementation. None block the design — they're
parameter-tuning and code-organization choices best made when writing the code:

- **LLM prompt design**: specific prompts for the authoring conversation and the live
  judge call. To be drafted in `prompts/` during implementation, with few-shot examples
  per round type.
- **Fuzzy-match parameters**: Levenshtein threshold per question type, normalization
  rules (punctuation, articles, diacritics, plural forms). Defaults proposed: lowercase
  + strip punctuation + strip leading "the"/"a"/"an" + threshold of 2 for short
  answers, 3 for longer.
- **Anti-cheat thresholds**: how fast is "suspiciously fast"? How many tab-blur events
  trigger a visible indicator vs flagged-in-review? Defaults proposed: "fast answer" =
  &lt;2s on a question with median answer time &gt;10s; tab-blur indicator on first event,
  flag in review at ≥3 events per round.
- **Frontend state library**: Zustand vs Jotai vs Redux Toolkit vs bespoke. Pick during
  implementation; the choice is local to the frontend and doesn't affect the protocol.
- **Lobby idle / abandoned session cleanup policy**: how long until a finished session's
  state is garbage-collected? (Leaderboard entries persist; raw session events can be
  pruned after, e.g., 30 days.)
