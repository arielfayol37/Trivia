# Trivia — Visual Personality

**Direction**: **Retro Game Show.** Think *Press Your Luck* + *Jeopardy!* + a hint of
*The Chase*. Theatrical, high-contrast, unapologetically bold. The play surface looks
like you're on a televised stage; the authoring surface looks like the production
booth behind it.

This document is the source of truth for visual personality. SPEC.md owns *what* the
product does; DESIGN.md owns *how it feels*.

---

## Anchoring principles

1. **The play screen is the stage; the authoring screen is the booth.** Two related
   but distinct moods. They share palette and typography, but the booth is muted
   (focused work) and the stage is loud (broadcast).
2. **Type and number are the primary visual elements.** Questions, scores, timers, and
   round titles should be *huge* — they earn the screen. Chrome (buttons, panels) is
   secondary and stays out of the way.
3. **Motion is part of the design.** Round intros, lock-ins, correct/wrong reactions,
   score rolls, timer pulses. Static is wrong; even subtle motion makes it feel alive.
4. **Copy voice is theatrical but tight.** Exclamatory at moments (`ROUND 2!`,
   `LOCKED IN`, `WINNER`), conversational in between. Never wordy. Never apologetic.
5. **The host is implied.** Even though there's no AI-host character (we picked the
   game-show direction, not the AI-as-host direction), the UI should *act* like
   there's a host orchestrating: announces rounds, locks in answers, declares
   results.

---

## Palette

Keep most of what's there; sharpen the roles.

| Token | Hex | Role |
|---|---|---|
| `midnight` | `#101421` | Stage backdrop. Dominant for play surface. |
| `night` | `#22283a` | Secondary surfaces on stage (cards on midnight). |
| `stagegold` | `#f7c948` | Primary CTA, hero numbers, "lock in" affordance. Stage spotlight. |
| `stagegoldHover` | `#ffd95e` | Hover state for stagegold buttons. |
| `electric` | `#3564ff` | Round-2 / energetic accent. Use sparingly. |
| `magenta` | `#e83a8e` | **NEW** — theatrical "now playing" / chyron accent. |
| `aqua` | `#72e0b3` | "Accepted" / correct flash. |
| `coral` | `#f05d5e` | "Not quite" / wrong flash. Also danger. |
| `champagne` | `#e8c87a` | **NEW** — winner / trophy accent (softer than stagegold). |
| `paper` | `#f3f4f8` | Authoring booth background. |
| `softline` | `#d5d8df` | Booth borders. |
| `steel` | `#5d6575` | Booth secondary text. |
| `chip` / `chipHover` | `#f2f4f8` / `#e3e7ef` | Booth chips. |

Add `magenta` and `champagne` to `tailwind.config.ts`. Retire any color tokens that no
longer have a role (`field`, `mint`, `moss`, `gold`, `rust`, `ink` — these were the old
muted authoring palette; replace with the new booth tokens).

---

## Typography

| Role | Font | Notes |
|---|---|---|
| Display (questions, round titles, scores) | **Anton** or **Druk Wide** | Condensed, heavy, all-caps when used at large sizes. Anton is free on Google Fonts. |
| Body / UI | **Inter** (already in use) | Keep. Use tabular numerals where displayed: `font-variant-numeric: tabular-nums`. |
| Tabular numerals | Inter tabular | For scores and timers; prevents wobble during animation. |

**Sizes:**
- Question prompt: `text-3xl` to `text-5xl`, semi-bold. Center-stage on play screen.
- Score numbers (big board): `text-6xl` to `text-7xl`, tabular nums, display font.
- Timer: `text-5xl` to `text-6xl`, tabular nums.
- Round intro slate ("ROUND 2"): `text-6xl` to `text-8xl`, display font, uppercase, tracking-wide.
- Body: `text-sm` / `text-base`. Stays small; chrome doesn't compete with the stage.

Add the display font in `index.html` (via Google Fonts) and reference it in
`tailwind.config.ts` as `fontFamily: { display: ["Anton", "Inter", "sans-serif"] }`.

---

## Voice (UI copy)

| Moment | Copy |
|---|---|
| Lobby waiting | "Studio fills in 30 seconds." / "Waiting on Carlos." |
| Round start slate | `ROUND 2`, subtitle: `BUZZ-IN` or `LIST RACE` |
| Question reveal | (No copy — the question itself is the moment) |
| Submit button | `LOCK IT IN` |
| Just-submitted, waiting on verdict | `Locked` |
| Correct | `THAT'S IT!` or `SPOT ON.` (single-word, big) |
| Wrong | `NOT QUITE.` or `TOUGH ONE.` |
| Timer < 5s | `:04` in pulsing coral |
| Round-end | `END OF ROUND` slate with intermediate scoreboard |
| Final | `THAT'S A WRAP` slate, then winner reveal |
| Winner | `[NAME] TAKES IT.` champagne accent, trophy icon |
| Tie | `IT'S A DRAW.` |

**Tone rules:**
- Never apologetic ("Oops, you got it wrong" → no; "NOT QUITE" → yes).
- Never explanatory ("This is a list race round" → no; the round name slate is enough).
- Uppercase for moments; sentence case for chrome.

---

## Motion language

Pick **Framer Motion** for the React side; light enough to add, expressive enough for
this. Add it as a dependency: `npm install framer-motion`.

**Required motion moments** (in priority order):

1. **Round intro slate** — between session start and round play, and between rounds.
   Full-screen midnight backdrop, the `ROUND N` text scales in from 1.2x to 1x with a
   spring; subtitle slides up below it; 2.5 second hold; then slide off to reveal the
   first question. (Implementing this is what makes the heterogeneous-round design
   actually *feel* like a game show.)
2. **Question card slide-in** — when a new question appears, the card translates from
   `translateY(20)` and fades in over ~250ms.
3. **Lock-in flash** — when the player hits submit, the submit button briefly flashes
   stagegold and the text changes to `LOCKED`. The answer input pulses once.
4. **Verdict reveal** — `THAT'S IT!` / `NOT QUITE.` scales in from 0.8x with a
   spring; aqua or coral background fades in behind the answer card; 1.5s hold then
   the next-question affordance becomes available.
5. **Score roll** — when a player scores, their score number rolls up from old to new
   (use `react-spring` or just a small `useEffect` interpolation). 800ms.
6. **Timer pulse** — at `t<5s` the timer text pulses scale 1.0 → 1.08 → 1.0 on each
   second. Color shifts from white to coral at `t<3s`.
7. **Wrong-answer shake** — when verdict is wrong, the answer card shakes
   `translateX(-6 → 6 → -3 → 3 → 0)` over 250ms.
8. **Winner reveal** — final scoreboard, then the winner card scales in with a flourish.
   Optional: a 1-second confetti burst (use `canvas-confetti` if cheap).

Anything not in this list: still motion-conscious. No abrupt color flips, no instant
panel swaps.

---

## Key screen layouts

### Lobby (already mostly there, refine)

- Midnight backdrop, hero invite code stays huge.
- Player tiles: keep colored avatar squares but add a **subtle ready-state pulse**
  (the colored square pulses when the player is ready).
- Replace `Mark ready` / `Ready` button with a single big stagegold button labeled
  `READY` / `READY ✓`.
- Replace `Start game` / `Start now` (host-only) with `START THE SHOW`.

### Round intro slate

Brand-new screen. Full midnight. Centered:
```
              ROUND 2
              ─────────
             LIST RACE
              ─────────
          "Name all 30 MLB stadiums"
```
Hold for 2.5s, then transition into the actual round.

### Sync-open / meta-strategy question card

- Question prompt centered, very large (`text-4xl` to `text-5xl`).
- Timer top-right, big tabular numeral.
- Answer input bottom-center, full-width, stagegold border on focus.
- Submit button: `LOCK IT IN`, stagegold, large.
- Verdict layer overlays the input area on submit.

### List-race round (when implemented)

- Single prompt centered: `"Name all 30 MLB stadiums"`.
- Two-column layout: your accepted list (left, scrollable), opponent's count
  (right, big number).
- Input below: one line, auto-clears on accept.
- Each accept triggers an aqua flash and the item slides into your list with the score
  ticking up.

### Buzz-in round (when implemented)

- Question reveals.
- Big `BUZZ` button bottom-center, dramatic spring on hover.
- First buzzer's avatar slides to center; their input gets focus.
- Others see a "locked out" state (greyed buzz button, an indicator showing who
  buzzed).

### Chyron strip (during play)

Bottom-of-screen strip with player chips: colored avatar, name, score in tabular nums.
Looks like a TV game-show lower-third. Replaces the separate scoreboard panel during
play; the panel reappears between rounds and on final screen.

### Winner reveal

Champagne accent. `[NAME] TAKES IT.` Big display font. Trophy icon. 1-second confetti
burst. Below: final scoreboard with normalized 0–100 per round.

---

## Authoring "booth" mood

The editor doesn't need to be theatrical — it's a workshop. But it should *belong* in
the same product:

- Background `paper` (#f3f4f8), surfaces white.
- Same display font available for headings and question previews.
- Same stagegold for primary CTAs (`SAVE DRAFT`, `GENERATE`).
- Use `electric` for in-line action affordances ("regenerate this question").
- Side-by-side chat-with-LLM + form editor (see SPEC §6.3) — the chat side feels like
  talking to a producer, the form side feels like a script editor.
- Drop the muted `bg-field` / `bg-mint` / `text-moss` palette entirely. Inconsistency
  with the play side is the biggest current problem.

---

## Implementation priorities

For the *next* visual-design pass, in this order:

1. **Bring the authoring page into the new visual world.** Same fonts, same palette,
   booth mood. This kills the split-identity problem.
2. **Round intro slate.** This single feature makes the heterogeneous-round design
   actually legible to the player. Without it, you can't tell when one round ends and
   another begins.
3. **Verdict reveal animation.** Currently the accepted/not-quite box is static.
   Adding spring scale-in + aqua/coral flash is a 30-line change with huge payoff.
4. **Score roll animation.** When you get points, the number should roll. Without
   this, scoring feels lifeless even when you're winning.
5. **Display-font system.** Add Anton (or chosen display font) in
   `index.html` + `tailwind.config.ts`. Apply to question prompts, scores, timer,
   round slates.
6. **Lock-in moment.** Submit button text change + flash. Small but tangible.
7. **Chyron strip.** Replace in-play scoreboard with a bottom chyron.
8. **Winner reveal flourish.** Champagne, trophy, optional confetti.

**Out of scope for this design pass** (but listed in SPEC roadmap):
- Sound effects. Add only after the visual feel is locked.
- Round-type-specific gameplay UI (list-race typing flow, buzz-in racing): those need
  the engine work first. Design language is what's described above; the implementation
  happens during M3 of IMPLEMENTATION.md.

---

## Anti-goals

Things this product is *not*:
- Pastel / wholesome / soft (no Wordle vibe).
- Hand-drawn / notebook / quirky.
- Sci-fi terminal / hacker.
- Corporate SaaS dashboard (the old aesthetic).
- AI-companion chat-driven (we picked stage, not booth-with-AI-host).

If a proposed change drifts toward any of these, it's wrong for this direction.
