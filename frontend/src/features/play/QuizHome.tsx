import confetti from "canvas-confetti";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  CheckCircle2,
  Clipboard,
  Crown,
  Home,
  Link,
  Loader2,
  LogIn,
  MessageCircle,
  Play,
  PlusCircle,
  Radio,
  RotateCcw,
  Search,
  SendHorizontal,
  Sparkles,
  Trophy,
  Users,
  XCircle,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  advanceSessionQuestion,
  createSession,
  getSessionSocketUrl,
  getHealth,
  getSession,
  joinSession,
  listQuizzes,
  sendSessionChat,
  setSessionPlayerReady,
  startSession,
  submitSessionAnswer,
} from "../../api/client";
import type { AnswerWidget, HealthResponse, LiveSession, Question, Quiz, SessionChatMessage } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Field";
import { InlineMathText } from "./MathText";
import { PromptBlocksRenderer } from "./PromptBlocksRenderer";
import { RoundIntroSlate } from "./RoundIntroSlate";

type DifficultyFilter = "all" | Quiz["difficulty"];
type QuizCategoryId = "all" | Quiz["category"];

type QuizCategory = {
  id: Exclude<QuizCategoryId, "all">;
  label: string;
  keywords: string[];
};

const quizCategories: QuizCategory[] = [
  {
    id: "science",
    label: "Science",
    keywords: [
      "science",
      "physics",
      "quantum",
      "chemistry",
      "biology",
      "math",
      "schrodinger",
      "equation",
    ],
  },
  {
    id: "tv",
    label: "TV & Movies",
    keywords: ["tv", "show", "movie", "film", "game of thrones", "got", "series"],
  },
  {
    id: "sports",
    label: "Sports",
    keywords: ["sports", "baseball", "mlb", "stadium", "nba", "nfl", "soccer"],
  },
  {
    id: "geography",
    label: "Geography",
    keywords: ["geography", "flag", "flags", "country", "countries", "capital", "map"],
  },
  {
    id: "history",
    label: "History",
    keywords: ["history", "war", "empire", "ancient", "president", "revolution"],
  },
  {
    id: "general",
    label: "General",
    keywords: [],
  },
];

const quizCategoryFilters: Array<{ id: QuizCategoryId; label: string }> = [
  { id: "all", label: "All" },
  ...quizCategories.map(({ id, label }) => ({ id, label })),
];

const playerColors = ["#3564ff", "#f05d5e", "#72e0b3", "#e8c87a", "#8a5cf6", "#f47b20", "#e83a8e", "#72e0b3"];
const localSessionStorageKey = "trivia.localSession.v1";

type StoredLocalSession = {
  invite_code: string;
  player_id: string;
  session_id: string;
};

function initialJoinCode() {
  return new URLSearchParams(window.location.search).get("join") ?? "";
}

function inviteUrl(inviteCode: string) {
  return `${window.location.origin}/?join=${encodeURIComponent(inviteCode)}`;
}

function updateJoinUrl(inviteCode: string) {
  window.history.replaceState(null, "", `?join=${encodeURIComponent(inviteCode)}`);
}

function saveLocalSession(session: LiveSession, playerId: string) {
  try {
    window.localStorage.setItem(
      localSessionStorageKey,
      JSON.stringify({
        invite_code: session.invite_code,
        player_id: playerId,
        session_id: session.id,
      } satisfies StoredLocalSession),
    );
  } catch {
    // Local storage is best-effort; losing it only disables refresh reconnect.
  }
}

function loadLocalSession(inviteCode: string): StoredLocalSession | null {
  if (!inviteCode) {
    return null;
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(localSessionStorageKey) ?? "null") as Partial<StoredLocalSession> | null;
    if (
      parsed &&
      parsed.invite_code === inviteCode &&
      typeof parsed.player_id === "string" &&
      typeof parsed.session_id === "string"
    ) {
      return {
        invite_code: parsed.invite_code,
        player_id: parsed.player_id,
        session_id: parsed.session_id,
      };
    }
  } catch {
    return null;
  }
  return null;
}

function clearLocalSession() {
  try {
    window.localStorage.removeItem(localSessionStorageKey);
  } catch {
    // Nothing to clear.
  }
}

function quizQuestionCount(quiz: Quiz) {
  return quiz.rounds.reduce((sum, round) => sum + round.questions.length, 0);
}

function playerColor(index: number) {
  return playerColors[index % playerColors.length];
}

function quizSearchText(quiz: Quiz) {
  return `${quiz.title} ${quiz.category} ${quiz.topic} ${quiz.description}`.toLowerCase();
}

function categoryForQuiz(quiz: Quiz) {
  const explicitCategory = quizCategories.find((category) => category.id === quiz.category);
  if (explicitCategory) {
    return explicitCategory;
  }
  const searchText = quizSearchText(quiz);
  return (
    quizCategories.find((category) =>
      category.keywords.some((keyword) => searchText.includes(keyword)),
    ) ?? quizCategories[quizCategories.length - 1]
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function chatMessages(session: LiveSession): SessionChatMessage[] {
  const messages = asRecord(session.state).chat_messages;
  if (!Array.isArray(messages)) {
    return [];
  }
  return messages
    .map((message) => asRecord(message))
    .filter(
      (message) =>
        typeof message.id === "string" &&
        typeof message.player_id === "string" &&
        typeof message.display_name === "string" &&
        typeof message.message === "string" &&
        typeof message.created_at === "string",
    )
    .map((message) => ({
      id: message.id as string,
      player_id: message.player_id as string,
      display_name: message.display_name as string,
      message: message.message as string,
      created_at: message.created_at as string,
    }));
}

function currentQuestion(session: LiveSession): Question | null {
  const questionId = asRecord(session.state).question_id;
  if (typeof questionId !== "string") {
    return null;
  }

  for (const round of session.quiz.rounds) {
    const question = round.questions.find((item) => item.id === questionId);
    if (question) {
      return question;
    }
  }
  return null;
}

function currentRound(session: LiveSession) {
  const question = currentQuestion(session);
  if (!question) {
    return null;
  }
  return session.quiz.rounds.find((round) =>
    round.questions.some((item) => item.id === question.id),
  ) ?? null;
}

function questionProgress(session: LiveSession) {
  const state = asRecord(session.state);
  const index = typeof state.question_index === "number" ? state.question_index : session.current_question_idx;
  const count = typeof state.question_count === "number" ? state.question_count : 0;
  return { index, count };
}

function questionDeadlineMs(session: LiveSession) {
  const state = asRecord(session.state);
  const rawStartedAt = state.question_started_at;
  const timeoutS = typeof state.question_timeout_s === "number" ? state.question_timeout_s : 25;
  if (typeof rawStartedAt !== "string" || timeoutS <= 0) {
    return null;
  }
  const startedAtMs = Date.parse(rawStartedAt);
  if (!Number.isFinite(startedAtMs)) {
    return null;
  }
  return startedAtMs + timeoutS * 1000;
}

function questionHasClosed(session: LiveSession, nowMs: number) {
  const deadlineMs = questionDeadlineMs(session);
  return deadlineMs !== null && nowMs >= deadlineMs;
}

function lobbyCountdownRemaining(session: LiveSession, nowMs: number) {
  const state = asRecord(session.state);
  const rawStartedAt = state.lobby_countdown_started_at;
  const countdownS = typeof state.lobby_countdown_s === "number" ? state.lobby_countdown_s : null;
  if (typeof rawStartedAt !== "string" || countdownS === null) {
    return null;
  }
  const startedAtMs = Date.parse(rawStartedAt);
  if (!Number.isFinite(startedAtMs)) {
    return null;
  }
  return Math.max(0, Math.ceil((startedAtMs + countdownS * 1000 - nowMs) / 1000));
}

function scoreFor(session: LiveSession, playerId: string) {
  const scores = asRecord(asRecord(session.state).scores);
  const score = scores[playerId];
  return typeof score === "number" ? score : 0;
}

function submissionFor(session: LiveSession, questionId: string, playerId: string) {
  const submissions = asRecord(asRecord(session.state).submissions);
  return asRecord(asRecord(submissions[questionId])[playerId]);
}

function playerPresence(session: LiveSession, playerId: string) {
  const presence = asRecord(asRecord(session.state).presence);
  const entry = asRecord(presence[playerId]);
  return {
    online: entry.online === true,
    known: Object.keys(entry).length > 0,
  };
}

const ROUND_LABELS: Record<Quiz["rounds"][number]["type"], string> = {
  meta_strategy: "Meta-strategy",
  list_race: "List race",
  buzz_in: "Buzz-in",
  sync_open: "Open answer",
};

function roundLabel(type: Quiz["rounds"][number]["type"]) {
  return ROUND_LABELS[type];
}

export function QuizHome() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [selectedQuizId, setSelectedQuizId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<QuizCategoryId>("all");
  const [difficulty, setDifficulty] = useState<DifficultyFilter>("all");
  const [playerName, setPlayerName] = useState("");
  const [joinCode, setJoinCode] = useState(initialJoinCode);
  const [liveSession, setLiveSession] = useState<LiveSession | null>(null);
  const [localPlayerId, setLocalPlayerId] = useState<string | null>(null);
  const [isLoadingQuizzes, setIsLoadingQuizzes] = useState(true);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [isJoiningSession, setIsJoiningSession] = useState(false);
  const [isUpdatingSession, setIsUpdatingSession] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    listQuizzes()
      .then(setQuizzes)
      .catch(() => setQuizzes([]))
      .finally(() => setIsLoadingQuizzes(false));
  }, []);

  useEffect(() => {
    const storedSession = loadLocalSession(initialJoinCode());
    if (!storedSession) {
      return;
    }

    let cancelled = false;
    getSession(storedSession.session_id)
      .then((session) => {
        if (cancelled) {
          return;
        }
        const restoredPlayer = session.players.find(
          (player) => player.id === storedSession.player_id,
        );
        if (!restoredPlayer || session.invite_code !== storedSession.invite_code) {
          clearLocalSession();
          return;
        }
        setLiveSession(session);
        setLocalPlayerId(storedSession.player_id);
        setPlayerName(restoredPlayer.display_name);
        setSelectedQuizId(session.quiz.id);
        setJoinCode(session.invite_code);
        updateJoinUrl(session.invite_code);
      })
      .catch(() => clearLocalSession());

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!liveSession) {
      return;
    }

    let isClosed = false;
    const socket = new WebSocket(getSessionSocketUrl(liveSession.id, localPlayerId));
    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data) as { session?: LiveSession };
        if (!isClosed && payload.session) {
          setLiveSession(payload.session);
        }
      } catch {
        // Ignore malformed socket payloads; the REST fallback will resync state.
      }
    });

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ type: "ping" }));
    });

    const timer = window.setInterval(() => {
      getSession(liveSession.id)
        .then(setLiveSession)
        .catch(() => undefined);
    }, 10000);

    return () => {
      isClosed = true;
      window.clearInterval(timer);
      socket.close();
    };
  }, [liveSession?.id, localPlayerId]);

  const baseFilteredQuizzes = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return quizzes.filter((quiz) => {
      const matchesSearch =
        !normalizedSearch ||
        quizSearchText(quiz).includes(normalizedSearch);
      const matchesDifficulty = difficulty === "all" || quiz.difficulty === difficulty;
      return matchesSearch && matchesDifficulty;
    });
  }, [difficulty, quizzes, search]);

  const filteredQuizzes = useMemo(
    () =>
      baseFilteredQuizzes.filter(
        (quiz) => category === "all" || categoryForQuiz(quiz).id === category,
      ),
    [baseFilteredQuizzes, category],
  );

  const categoryCounts = useMemo(() => {
    const counts: Record<QuizCategoryId, number> = {
      all: baseFilteredQuizzes.length,
      science: 0,
      tv: 0,
      sports: 0,
      geography: 0,
      history: 0,
      general: 0,
    };
    for (const quiz of baseFilteredQuizzes) {
      counts[categoryForQuiz(quiz).id] += 1;
    }
    return counts;
  }, [baseFilteredQuizzes]);

  const selectedQuiz = quizzes.find((quiz) => quiz.id === selectedQuizId) ?? null;
  const relatedQuizzes = selectedQuiz
    ? quizzes
        .filter((quiz) => quiz.id !== selectedQuiz.id && quiz.topic === selectedQuiz.topic)
        .slice(0, 4)
    : [];

  async function handleCreateLobby(quizToPlay: Quiz | null = selectedQuiz) {
    if (!quizToPlay) {
      return;
    }
    const displayName = playerName.trim();
    if (!displayName) {
      setSessionError("Choose a player name before starting a lobby");
      return;
    }

    setIsCreatingSession(true);
    setSessionError(null);
    try {
      const response = await createSession({
        quiz_id: quizToPlay.id,
        display_name: displayName,
      });
      saveLocalSession(response.session, response.player_id);
      setLiveSession(response.session);
      setLocalPlayerId(response.player_id);
      setSelectedQuizId(response.session.quiz.id);
      setJoinCode(response.session.invite_code);
      updateJoinUrl(response.session.invite_code);
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not create lobby");
    } finally {
      setIsCreatingSession(false);
    }
  }

  async function handleJoinLobby(event: FormEvent) {
    event.preventDefault();
    const displayName = playerName.trim();
    if (!displayName) {
      setSessionError("Choose a player name before joining");
      return;
    }

    setIsJoiningSession(true);
    setSessionError(null);
    try {
      const response = await joinSession({
        invite_code: joinCode.trim(),
        display_name: displayName,
      });
      saveLocalSession(response.session, response.player_id);
      setLiveSession(response.session);
      setLocalPlayerId(response.player_id);
      setSelectedQuizId(response.session.quiz.id);
      setJoinCode(response.session.invite_code);
      updateJoinUrl(response.session.invite_code);
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not join lobby");
    } finally {
      setIsJoiningSession(false);
    }
  }

  async function handleReadyChange(isReady: boolean) {
    if (!liveSession || !localPlayerId) {
      return;
    }

    setIsUpdatingSession(true);
    setSessionError(null);
    try {
      setLiveSession(await setSessionPlayerReady(liveSession.id, localPlayerId, isReady));
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not update ready state");
    } finally {
      setIsUpdatingSession(false);
    }
  }

  async function handleStartSession() {
    if (!liveSession) {
      return;
    }

    setIsUpdatingSession(true);
    setSessionError(null);
    try {
      setLiveSession(await startSession(liveSession.id));
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not start session");
    } finally {
      setIsUpdatingSession(false);
    }
  }

  async function handleSubmitAnswer(input: {
    submitted_text?: string;
    submitted_payload?: Record<string, unknown>;
  }) {
    if (!liveSession || !localPlayerId) {
      return;
    }

    setIsUpdatingSession(true);
    setSessionError(null);
    try {
      setLiveSession(await submitSessionAnswer(liveSession.id, localPlayerId, input));
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not submit answer");
    } finally {
      setIsUpdatingSession(false);
    }
  }

  async function handleSendChat(message: string) {
    if (!liveSession || !localPlayerId) {
      return;
    }

    setSessionError(null);
    try {
      setLiveSession(await sendSessionChat(liveSession.id, localPlayerId, message));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Could not send chat";
      setSessionError(errorMessage);
      throw new Error(errorMessage);
    }
  }

  async function handleAdvanceQuestion() {
    if (!liveSession) {
      return;
    }

    setIsUpdatingSession(true);
    setSessionError(null);
    try {
      setLiveSession(await advanceSessionQuestion(liveSession.id));
    } catch (err) {
      setSessionError(err instanceof Error ? err.message : "Could not advance question");
    } finally {
      setIsUpdatingSession(false);
    }
  }

  function handleBackHome() {
    clearLocalSession();
    setLiveSession(null);
    setLocalPlayerId(null);
    setSelectedQuizId(null);
    setJoinCode("");
    window.history.replaceState(null, "", "/");
  }

  function handleFindSimilar(quiz: Quiz) {
    clearLocalSession();
    setLiveSession(null);
    setLocalPlayerId(null);
    setSelectedQuizId(null);
    setJoinCode("");
    setSearch(quiz.topic || quiz.title);
    setCategory(categoryForQuiz(quiz).id);
    setDifficulty("all");
    window.history.replaceState(null, "", "/");
  }

  const isGameActive = liveSession?.status === "playing" || liveSession?.status === "finished";

  return (
    <main className="min-h-screen bg-midnight text-white">
      {isGameActive ? null : <TopBar health={health} dark />}

      {liveSession?.status === "playing" || liveSession?.status === "finished" ? (
        <GameRoom
          isUpdatingSession={isUpdatingSession}
          localPlayerId={localPlayerId}
          onAdvanceQuestion={handleAdvanceQuestion}
          onBackHome={handleBackHome}
          onFindSimilar={handleFindSimilar}
          onPlayAgain={() => handleCreateLobby(liveSession.quiz)}
          onSendChat={handleSendChat}
          onSubmitAnswer={handleSubmitAnswer}
          session={liveSession}
          sessionError={sessionError}
        />
      ) : liveSession ? (
        <LobbyRoom
          isUpdatingSession={isUpdatingSession}
          localPlayerId={localPlayerId}
          onReadyChange={handleReadyChange}
          onSendChat={handleSendChat}
          onStartSession={handleStartSession}
          session={liveSession}
          setSessionError={setSessionError}
          sessionError={sessionError}
        />
      ) : selectedQuiz ? (
        <QuizDetail
          isCreatingSession={isCreatingSession}
          onBack={() => setSelectedQuizId(null)}
          onCreateLobby={() => handleCreateLobby(selectedQuiz)}
          onOpenQuiz={setSelectedQuizId}
          onPlayerNameChange={setPlayerName}
          playerName={playerName}
          quiz={selectedQuiz}
          relatedQuizzes={relatedQuizzes}
          sessionError={sessionError}
        />
      ) : (
        <PlayLobbyFinder
          category={category}
          categoryCounts={categoryCounts}
          difficulty={difficulty}
          filteredQuizzes={filteredQuizzes}
          isJoiningSession={isJoiningSession}
          isLoadingQuizzes={isLoadingQuizzes}
          joinCode={joinCode}
          onCategoryChange={setCategory}
          onDifficultyChange={setDifficulty}
          onJoinCodeChange={setJoinCode}
          onJoinLobby={handleJoinLobby}
          onOpenQuiz={setSelectedQuizId}
          onPlayerNameChange={setPlayerName}
          onSearchChange={setSearch}
          playerName={playerName}
          search={search}
          sessionError={sessionError}
        />
      )}
    </main>
  );
}

function TopBar({ health, dark }: { health: HealthResponse | null; dark: boolean }) {
  return (
    <header
      className={`border-b ${
        dark ? "border-white/10 bg-midnight" : "border-softline bg-white"
      }`}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
        <a className="flex items-center gap-3" href="/">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-stagegold text-midnight">
            <Sparkles className="h-5 w-5" />
          </span>
          <span>
            <span className={`block font-display text-2xl leading-none tracking-wide ${dark ? "text-white" : "text-midnight"}`}>
              TRIVIA
            </span>
            <span
              className={`text-[10px] font-bold uppercase tracking-[0.3em] ${
                dark ? "text-white/55" : "text-steel"
              }`}
            >
              Play with friends
            </span>
          </span>
        </a>
        <div className="flex items-center gap-3">
          <span
            className={`hidden items-center gap-2 text-xs sm:flex ${
              dark ? "text-white/65" : "text-steel"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${health?.ok ? "bg-aqua" : "bg-coral"}`}
            />
            {health?.ok ? "online" : "offline"}
          </span>
          <a
            className={`inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-bold uppercase tracking-wider transition ${
              dark
                ? "bg-white text-midnight hover:bg-pale"
                : "bg-midnight text-white hover:bg-midnightHover"
            }`}
            href="/author"
          >
            <PlusCircle className="h-4 w-4" />
            Author
          </a>
        </div>
      </div>
    </header>
  );
}

function PlayLobbyFinder({
  category,
  categoryCounts,
  difficulty,
  filteredQuizzes,
  isJoiningSession,
  isLoadingQuizzes,
  joinCode,
  onCategoryChange,
  onDifficultyChange,
  onJoinCodeChange,
  onJoinLobby,
  onOpenQuiz,
  onPlayerNameChange,
  onSearchChange,
  playerName,
  search,
  sessionError,
}: {
  category: QuizCategoryId;
  categoryCounts: Record<QuizCategoryId, number>;
  difficulty: DifficultyFilter;
  filteredQuizzes: Quiz[];
  isJoiningSession: boolean;
  isLoadingQuizzes: boolean;
  joinCode: string;
  onCategoryChange: (category: QuizCategoryId) => void;
  onDifficultyChange: (difficulty: DifficultyFilter) => void;
  onJoinCodeChange: (code: string) => void;
  onJoinLobby: (event: FormEvent) => void;
  onOpenQuiz: (quizId: string) => void;
  onPlayerNameChange: (name: string) => void;
  onSearchChange: (search: string) => void;
  playerName: string;
  search: string;
  sessionError: string | null;
}) {
  const groupedQuizzes = quizCategories
    .map((quizCategory) => ({
      ...quizCategory,
      quizzes: filteredQuizzes.filter((quiz) => categoryForQuiz(quiz).id === quizCategory.id),
    }))
    .filter((group) => group.quizzes.length > 0);

  return (
    <div className="mx-auto max-w-6xl px-5 py-6">
      <section className="relative overflow-hidden rounded-2xl bg-midnight text-white shadow-stage">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-stagegold/10 via-transparent to-magenta/10" />
        <div className="relative grid gap-0 lg:grid-cols-[1fr_420px]">
          <div className="p-6 sm:p-8">
            <div className="text-[10px] font-bold uppercase tracking-[0.5em] text-stagegold">
              Tonight on Trivia
            </div>
            <h1 className="mt-3 font-display text-5xl uppercase leading-[0.95] tracking-wide sm:text-6xl">
              Pick a quiz.
              <br />
              Start the show.
            </h1>
            <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_180px]">
              <Input
                className="h-14 border-white/15 bg-white/95 px-4 text-base text-midnight placeholder:text-steel"
                placeholder="Search quizzes..."
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
              />
              <select
                className="h-14 rounded-md border border-white/15 bg-white/95 px-3 text-sm font-semibold text-midnight outline-none"
                value={difficulty}
                onChange={(event) => onDifficultyChange(event.target.value as DifficultyFilter)}
              >
                <option value="all">All levels</option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div className="mt-5 flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-wider text-white/70">
              {["game of thrones", "flags", "quantum"].map((tag) => (
                <button
                  className="rounded-full bg-white/10 px-3 py-1.5 hover:bg-white/20"
                  key={tag}
                  onClick={() => onSearchChange(tag)}
                  type="button"
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <form
            className="border-t border-white/10 bg-white/5 p-6 sm:p-8 lg:border-l lg:border-t-0"
            onSubmit={onJoinLobby}
          >
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.4em] text-aqua">
              <LogIn className="h-4 w-4" />
              Join a room
            </div>
            <div className="mt-4 grid gap-3">
              <label className="block">
                <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.35em] text-white/55">
                  Player name
                </span>
                <Input
                  className="h-12 border-white/15 bg-white text-midnight"
                  autoComplete="nickname"
                  placeholder="Your name"
                  value={playerName}
                  onChange={(event) => onPlayerNameChange(event.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.35em] text-white/55">
                  Invite code
                </span>
                <Input
                  className="h-16 border-white/15 bg-white text-center font-display text-3xl uppercase tracking-[0.3em] text-midnight"
                  placeholder="CODE"
                  value={joinCode}
                  onChange={(event) => onJoinCodeChange(event.target.value.toUpperCase())}
                />
              </label>
              <Button
                className="h-12 uppercase tracking-wider"
                disabled={isJoiningSession || !joinCode.trim() || !playerName.trim()}
                type="submit"
                variant="stage"
              >
                {isJoiningSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />}
                Join the show
              </Button>
            </div>
            {sessionError ? (
              <div className="mt-3 text-sm font-semibold text-inviteError">{sessionError}</div>
            ) : null}
          </form>
        </div>
      </section>

      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-display text-2xl uppercase tracking-wide text-white">
            Quizzes
          </h2>
          <span className="text-sm text-white/65">
            {isLoadingQuizzes ? "Loading" : `${filteredQuizzes.length} available`}
          </span>
        </div>
        <div className="mb-5 flex gap-2 overflow-x-auto pb-1">
          {quizCategoryFilters.map((item) => (
            <button
              className={`shrink-0 rounded-full border px-3 py-2 text-xs font-bold uppercase tracking-wider transition ${
                category === item.id
                  ? "border-stagegold bg-stagegold text-midnight"
                  : "border-white/10 bg-white/5 text-white/75 hover:border-stagegold/60 hover:text-white"
              }`}
              key={item.id}
              onClick={() => onCategoryChange(item.id)}
              type="button"
            >
              {item.label}
              <span className="ml-2 opacity-70">{categoryCounts[item.id]}</span>
            </button>
          ))}
        </div>
        {isLoadingQuizzes ? (
          <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-5 text-sm text-white/70">
            Loading quizzes...
          </div>
        ) : filteredQuizzes.length === 0 ? (
          <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-5">
            <div className="font-semibold text-white">No matching quizzes yet.</div>
            <a
              className="mt-2 inline-flex text-sm font-bold uppercase tracking-wide text-stagegold"
              href="/author"
            >
              Create one
            </a>
          </div>
        ) : category === "all" && !search.trim() ? (
          <div className="space-y-7">
            {groupedQuizzes.map((group) => (
              <section key={group.id}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-[10px] font-bold uppercase tracking-[0.45em] text-stagegold">
                    {group.label}
                  </h3>
                  <span className="text-xs text-white/45">{group.quizzes.length}</span>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {group.quizzes.slice(0, 9).map((quiz) => (
                    <QuizResultCard
                      key={quiz.id}
                      onOpen={() => onOpenQuiz(quiz.id)}
                      quiz={quiz}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filteredQuizzes.slice(0, 18).map((quiz) => (
              <QuizResultCard
                key={quiz.id}
                onOpen={() => onOpenQuiz(quiz.id)}
                quiz={quiz}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function QuizResultCard({ onOpen, quiz }: { onOpen: () => void; quiz: Quiz }) {
  const category = categoryForQuiz(quiz);

  return (
    <button
      className="group h-full rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:-translate-y-0.5 hover:border-stagegold/60 hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-stagegold focus:ring-offset-2 focus:ring-offset-midnight"
      onClick={onOpen}
      type="button"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-stagegold">
            {category.label} · {quiz.topic || "general"} · {quiz.difficulty}
          </div>
          <h3 className="mt-2 line-clamp-2 font-display text-2xl uppercase leading-tight tracking-wide text-white">
            {quiz.title}
          </h3>
        </div>
        <span className="shrink-0 rounded-full bg-white/10 px-2 py-1 text-xs font-semibold text-white/80">
          {quizQuestionCount(quiz)} Q
        </span>
      </div>
      <p className="mt-3 line-clamp-2 min-h-10 text-sm leading-5 text-white/65">
        {quiz.description || "Ready to play."}
      </p>
      <div className="mt-4 h-1 overflow-hidden rounded-full bg-white/10">
        <div className="h-full w-0 rounded-full bg-stagegold transition-all group-hover:w-full" />
      </div>
    </button>
  );
}

function QuizDetail({
  isCreatingSession,
  onBack,
  onCreateLobby,
  onOpenQuiz,
  onPlayerNameChange,
  playerName,
  quiz,
  relatedQuizzes,
  sessionError,
}: {
  isCreatingSession: boolean;
  onBack: () => void;
  onCreateLobby: () => void;
  onOpenQuiz: (quizId: string) => void;
  onPlayerNameChange: (name: string) => void;
  playerName: string;
  quiz: Quiz;
  relatedQuizzes: Quiz[];
  sessionError: string | null;
}) {
  return (
    <div className="mx-auto max-w-5xl px-5 py-6">
      <button
        className="mb-4 inline-flex items-center gap-2 rounded-md px-2 py-1 text-xs font-bold uppercase tracking-wider text-stagegold hover:bg-white/5"
        onClick={onBack}
        type="button"
      >
        <ArrowLeft className="h-4 w-4" />
        All quizzes
      </button>

      <section className="relative overflow-hidden rounded-2xl bg-night p-6 text-white shadow-stage sm:p-10">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-stagegold/10 via-transparent to-transparent" />
        <div className="relative">
          <div className="text-[10px] font-bold uppercase tracking-[0.5em] text-stagegold">
            {quiz.topic || "general"} · {quiz.difficulty}
          </div>
          <h1 className="mt-4 max-w-3xl font-display text-5xl uppercase leading-[0.95] tracking-wide sm:text-7xl">
            {quiz.title}
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-white/75">
            {quiz.description || "Ready to play."}
          </p>
          <div className="mt-7 flex flex-wrap gap-6 text-sm">
            <Stat label="Rounds" value={quiz.rounds.length} />
            <Stat label="Questions" value={quizQuestionCount(quiz)} />
            <Stat label="Mode" value="Multiplayer" />
          </div>
          <div className="mt-7 grid max-w-xl gap-3 sm:grid-cols-[1fr_auto]">
            <label className="block">
              <span className="mb-2 block text-[10px] font-bold uppercase tracking-[0.35em] text-white/55">
                Player name
              </span>
              <Input
                className="h-14 border-white/15 bg-white text-base text-midnight"
                autoComplete="nickname"
                onChange={(event) => onPlayerNameChange(event.target.value)}
                placeholder="Your name"
                value={playerName}
              />
            </label>
            <Button
              className="self-end h-14 px-7 uppercase tracking-wider"
              disabled={isCreatingSession || !playerName.trim()}
              onClick={onCreateLobby}
              type="button"
              variant="stage"
            >
              {isCreatingSession ? <Loader2 className="h-5 w-5 animate-spin" /> : <Radio className="h-5 w-5" />}
              Start the show
            </Button>
          </div>
          {sessionError ? (
            <div className="mt-3 text-sm font-semibold text-inviteError">{sessionError}</div>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-3">
            <a
              className="inline-flex h-14 items-center justify-center rounded-md border border-white/20 px-5 text-sm font-bold uppercase tracking-wider text-white transition hover:bg-white/10"
              href="/author"
            >
              Make another quiz
            </a>
          </div>
        </div>
      </section>

      {relatedQuizzes.length ? (
        <section className="mt-6">
          <h2 className="mb-3 font-display text-xl uppercase tracking-wide text-white">
            Related
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {relatedQuizzes.map((relatedQuiz) => (
              <button
                className="rounded-xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-stagegold/60 hover:bg-white/10"
                key={relatedQuiz.id}
                onClick={() => onOpenQuiz(relatedQuiz.id)}
                type="button"
              >
                <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-stagegold">
                  {relatedQuiz.difficulty}
                </div>
                <div className="mt-2 font-display text-xl uppercase tracking-wide text-white">
                  {relatedQuiz.title}
                </div>
                <div className="mt-1 text-sm text-white/65">
                  {quizQuestionCount(relatedQuiz)} questions
                </div>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/55">
        {label}
      </div>
      <div className="mt-1 font-display text-3xl text-white tabular-nums">{value}</div>
    </div>
  );
}

function LobbyRoom({
  isUpdatingSession,
  localPlayerId,
  onReadyChange,
  onSendChat,
  onStartSession,
  session,
  setSessionError,
  sessionError,
}: {
  isUpdatingSession: boolean;
  localPlayerId: string | null;
  onReadyChange: (isReady: boolean) => void;
  onSendChat: (message: string) => Promise<void>;
  onStartSession: () => void;
  session: LiveSession;
  setSessionError: (message: string | null) => void;
  sessionError: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now());
  const localPlayer = session.players.find((player) => player.id === localPlayerId);
  const isLobby = session.status === "lobby";
  const isHost = Boolean(localPlayer?.is_host);
  const url = inviteUrl(session.invite_code);
  const allReady =
    session.players.length > 0 &&
    session.players.filter((p) => p.role === "player").every((p) => p.is_ready);
  const countdownRemaining = lobbyCountdownRemaining(session, nowMs);
  const countdownActive = countdownRemaining !== null;

  useEffect(() => {
    if (!countdownActive) {
      return;
    }
    const timer = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [countdownActive]);

  async function handleCopyInvite() {
    setSessionError(null);
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setSessionError("Copy is unavailable here; use the visible link.");
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-6">
      <section className="relative overflow-hidden rounded-2xl bg-night p-6 text-white shadow-stage sm:p-10">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-stagegold/10 via-transparent to-transparent" />
        <div className="relative grid gap-8 lg:grid-cols-[1fr_360px]">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.5em] text-aqua">
              Studio
            </div>
            <h1 className="mt-2 font-display text-4xl uppercase leading-tight tracking-wide sm:text-5xl">
              {session.quiz.title}
            </h1>
            <div className="mt-8">
              <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/55">
                Invite code
              </div>
              <motion.div
                animate={{ scale: 1 }}
                className="mt-3 inline-flex rounded-xl bg-white px-6 py-4 font-display text-6xl tracking-[0.18em] text-midnight tabular-nums sm:text-7xl"
                initial={{ scale: 0.96 }}
                transition={{ type: "spring", stiffness: 220, damping: 20 }}
              >
                {session.invite_code}
              </motion.div>
            </div>
            <div className="mt-4 flex items-center gap-2 rounded-md border border-white/15 bg-white/5 px-3 py-2 text-sm text-white/75">
              <Link className="h-4 w-4 shrink-0" />
              <span className="truncate">{url}</span>
            </div>
            {sessionError ? (
              <div className="mt-3 text-sm font-semibold text-inviteError">{sessionError}</div>
            ) : null}
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/65">
                  {session.status}
                </span>
                {allReady && isLobby ? (
                  <span className="rounded-full bg-aqua px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-midnight">
                    {countdownRemaining !== null ? `starts in ${countdownRemaining}` : "all ready"}
                  </span>
                ) : null}
              </div>
              {countdownRemaining !== null ? (
                <div className="mt-4 rounded-xl border border-stagegold/30 bg-stagegold/10 p-4 text-center">
                  <div className="text-[10px] font-bold uppercase tracking-[0.35em] text-stagegold">
                    All ready
                  </div>
                  <div className="mt-1 font-display text-5xl text-white tabular-nums">
                    {countdownRemaining}
                  </div>
                  <div className="mt-1 text-xs font-semibold uppercase tracking-[0.25em] text-white/55">
                    starting automatically
                  </div>
                </div>
              ) : null}
              <div className="mt-4 grid gap-2">
                <Button
                  className="bg-white text-midnight hover:bg-pale"
                  onClick={handleCopyInvite}
                  type="button"
                >
                  {copied ? <CheckCircle2 className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
                  {copied ? "Copied" : "Copy invite"}
                </Button>
                <Button
                  className="bg-aqua text-midnight hover:bg-aquaHover"
                  disabled={!isLobby || isUpdatingSession || !localPlayer}
                  onClick={() => onReadyChange(!localPlayer?.is_ready)}
                  type="button"
                >
                  {isUpdatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  {localPlayer?.is_ready ? "Ready ✓" : "Mark ready"}
                </Button>
                <Button
                  className="uppercase tracking-wider"
                  disabled={!isLobby || !isHost || isUpdatingSession}
                  onClick={onStartSession}
                  type="button"
                  variant="stage"
                >
                  {isUpdatingSession ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  {countdownRemaining !== null ? "Start now" : "Start the show"}
                </Button>
              </div>
            </div>
            <RoomChatPanel
              disabled={!localPlayerId}
              localPlayerId={localPlayerId}
              onSendChat={onSendChat}
              session={session}
              tone="dark"
            />
          </div>
        </div>
      </section>

      <section className="mt-7">
        <div className="mb-3 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.4em] text-white/65">
          <Users className="h-4 w-4" />
          Players
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {session.players.map((player, index) => {
            const presence = playerPresence(session, player.id);
            return (
              <article
                className="relative overflow-hidden rounded-xl border border-white/10 bg-white/5 p-4 transition hover:bg-white/10"
                key={player.id}
              >
                <div className="flex items-center gap-3">
                  <motion.div
                    animate={player.is_ready ? { scale: [1, 1.08, 1] } : { scale: 1 }}
                    className="flex h-12 w-12 items-center justify-center rounded-md font-display text-2xl text-midnight"
                    style={{ backgroundColor: playerColor(index) }}
                    transition={{ duration: 1.6, repeat: player.is_ready ? Infinity : 0 }}
                  >
                    {player.display_name.slice(0, 1).toUpperCase()}
                  </motion.div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <div className="truncate font-bold text-white">{player.display_name}</div>
                      {player.is_host ? <Crown className="h-4 w-4 text-stagegold" /> : null}
                    </div>
                    <div
                      className={`mt-0.5 text-[10px] font-bold uppercase tracking-[0.3em] ${
                        player.is_ready ? "text-aqua" : "text-white/55"
                      }`}
                    >
                      {player.is_ready ? "ready" : "not ready"}
                    </div>
                    <div className="mt-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.25em] text-white/45">
                      <span
                        className={`h-2 w-2 rounded-full ${
                          presence.online ? "bg-aqua" : "bg-white/25"
                        }`}
                      />
                      {presence.online ? "online" : presence.known ? "offline" : "connecting"}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function GameRoom({
  isUpdatingSession,
  localPlayerId,
  onAdvanceQuestion,
  onBackHome,
  onFindSimilar,
  onPlayAgain,
  onSendChat,
  onSubmitAnswer,
  session,
  sessionError,
}: {
  isUpdatingSession: boolean;
  localPlayerId: string | null;
  onAdvanceQuestion: () => void;
  onBackHome: () => void;
  onFindSimilar: (quiz: Quiz) => void;
  onPlayAgain: () => void;
  onSendChat: (message: string) => Promise<void>;
  onSubmitAnswer: (input: {
    submitted_text?: string;
    submitted_payload?: Record<string, unknown>;
  }) => void;
  session: LiveSession;
  sessionError: string | null;
}) {
  if (session.status === "finished") {
    return (
      <FinishedRoom
        localPlayerId={localPlayerId}
        onBackHome={onBackHome}
        onFindSimilar={onFindSimilar}
        onPlayAgain={onPlayAgain}
        onSendChat={onSendChat}
        session={session}
      />
    );
  }

  if (asRecord(session.state).phase === "list_race") {
    return (
      <ListRaceRoom
        isUpdatingSession={isUpdatingSession}
        localPlayerId={localPlayerId}
        onAdvanceQuestion={onAdvanceQuestion}
        onSendChat={onSendChat}
        onSubmitAnswer={onSubmitAnswer}
        session={session}
        sessionError={sessionError}
      />
    );
  }

  return (
    <PlayingRoom
      isUpdatingSession={isUpdatingSession}
      localPlayerId={localPlayerId}
      onAdvanceQuestion={onAdvanceQuestion}
      onSendChat={onSendChat}
      onSubmitAnswer={onSubmitAnswer}
      session={session}
      sessionError={sessionError}
    />
  );
}

function ListRaceRoom({
  isUpdatingSession,
  localPlayerId,
  onAdvanceQuestion,
  onSendChat,
  onSubmitAnswer,
  session,
  sessionError,
}: {
  isUpdatingSession: boolean;
  localPlayerId: string | null;
  onAdvanceQuestion: () => void;
  onSendChat: (message: string) => Promise<void>;
  onSubmitAnswer: (input: {
    submitted_text?: string;
    submitted_payload?: Record<string, unknown>;
  }) => void;
  session: LiveSession;
  sessionError: string | null;
}) {
  const [answer, setAnswer] = useState("");
  const state = asRecord(session.state);
  const listRace = asRecord(state.list_race);
  const roundId = typeof state.round_id === "string" ? state.round_id : "";
  const round = session.quiz.rounds.find((item) => item.id === roundId) ?? null;
  const prompt = String(listRace.prompt ?? round?.config.prompt ?? "Name as many as you can.");
  const itemsCount = typeof listRace.items_count === "number" ? listRace.items_count : 0;
  const found = asRecord(listRace.found);
  const playerFound = localPlayerId && Array.isArray(found[localPlayerId]) ? found[localPlayerId] : [];
  const lastSubmission =
    localPlayerId ? asRecord(asRecord(listRace.last_submission)[localPlayerId]) : {};
  const localPlayer = session.players.find((player) => player.id === localPlayerId);
  const isHost = Boolean(localPlayer?.is_host);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = answer.trim();
    if (!trimmed) {
      return;
    }
    onSubmitAnswer({ submitted_text: trimmed });
    setAnswer("");
  }

  return (
    <>
      <div className="mx-auto max-w-6xl px-5 py-6 pb-32">
        <div className="flex items-center justify-between gap-3 pr-14 text-[10px] font-bold uppercase tracking-[0.5em] text-stagegold">
          <span>List race</span>
          <span className="text-white/55">
            {playerFound.length} / {itemsCount || "?"}
          </span>
        </div>

        <section className="relative mt-3 overflow-hidden rounded-2xl bg-night p-6 text-white shadow-stage sm:p-8">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-stagegold/10 via-transparent to-transparent" />
          <div className="relative grid items-start gap-6 lg:grid-cols-[1fr_320px]">
            <div className="rounded-xl bg-white p-6 text-midnight sm:p-8">
              <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-midnight/45">
                Prompt
              </div>
              <h1 className="mt-3 font-display text-4xl uppercase leading-tight tracking-wide sm:text-5xl">
                <InlineMathText text={prompt} />
              </h1>
              <div className="mt-8 rounded-xl border border-softline bg-paper p-4">
                <div className="text-xs font-bold uppercase tracking-[0.3em] text-midnight/55">
                  Found
                </div>
                <div className="mt-2 font-display text-6xl tabular-nums text-midnight">
                  {playerFound.length}
                  <span className="text-2xl text-midnight/40">/{itemsCount || "?"}</span>
                </div>
              </div>
            </div>

            <aside className="space-y-4">
              <QuestionTimer session={session} />

              <form
                className="rounded-xl border border-white/15 bg-white/5 p-4"
                onSubmit={handleSubmit}
              >
                <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/55">
                  Answer
                </div>
                <Input
                  className="mt-3 h-12 border-white/15 bg-white text-midnight"
                  disabled={isUpdatingSession || !localPlayerId}
                  onChange={(event) => setAnswer(event.target.value)}
                  placeholder="Type an item"
                  value={answer}
                />
                <Button
                  className="mt-3 w-full uppercase tracking-wider"
                  disabled={isUpdatingSession || !answer.trim() || !localPlayerId}
                  type="submit"
                  variant="stage"
                >
                  {isUpdatingSession ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <SendHorizontal className="h-4 w-4" />
                  )}
                  Submit
                </Button>

                {lastSubmission.submitted ? (
                  <div
                    className={`mt-3 rounded-md px-3 py-2 text-sm font-semibold ${
                      lastSubmission.accepted
                        ? "bg-aqua text-midnight"
                        : "bg-coral text-white"
                    }`}
                  >
                    {lastSubmission.accepted
                      ? `Accepted: ${lastSubmission.canonical ?? lastSubmission.submitted}`
                      : lastSubmission.duplicate
                        ? "Already found"
                        : "Not on the list"}
                  </div>
                ) : null}

                {sessionError ? (
                  <div className="mt-3 text-sm font-semibold text-inviteError">{sessionError}</div>
                ) : null}
              </form>

              <Button
                className="w-full uppercase tracking-wider"
                disabled={!isHost || isUpdatingSession}
                onClick={onAdvanceQuestion}
                type="button"
                variant="stage"
              >
                End race
              </Button>
            </aside>
          </div>
        </section>
      </div>

      <RoomChatPanel
        disabled={!localPlayerId}
        localPlayerId={localPlayerId}
        mode="drawer"
        onSendChat={onSendChat}
        session={session}
        tone="dark"
      />
      <Chyron session={session} />
    </>
  );
}

function PlayingRoom({
  isUpdatingSession,
  localPlayerId,
  onAdvanceQuestion,
  onSendChat,
  onSubmitAnswer,
  session,
  sessionError,
}: {
  isUpdatingSession: boolean;
  localPlayerId: string | null;
  onAdvanceQuestion: () => void;
  onSendChat: (message: string) => Promise<void>;
  onSubmitAnswer: (input: {
    submitted_text?: string;
    submitted_payload?: Record<string, unknown>;
  }) => void;
  session: LiveSession;
  sessionError: string | null;
}) {
  const question = currentQuestion(session);
  const round = currentRound(session);
  const localPlayer = session.players.find((player) => player.id === localPlayerId);
  const isHost = Boolean(localPlayer?.is_host);
  const [introShownForRoundId, setIntroShownForRoundId] = useState<string | null>(null);
  const [introVisible, setIntroVisible] = useState(false);
  const [nowMs, setNowMs] = useState(Date.now());

  useEffect(() => {
    if (round && round.id !== introShownForRoundId) {
      setIntroShownForRoundId(round.id);
      setIntroVisible(true);
    }
  }, [round?.id, introShownForRoundId]);

  function handleIntroComplete() {
    setIntroVisible(false);
  }

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [question?.id]);

  const progress = questionProgress(session);
  const roundNumber = round?.order ?? session.current_round_idx + 1;

  if (!question) {
    return (
      <div className="mx-auto max-w-6xl px-5 py-10">
        <div className="rounded-2xl border border-white/10 bg-night p-6 text-white shadow-stage sm:p-10">
          <div className="text-[10px] font-bold uppercase tracking-[0.5em] text-aqua">
            Game room
          </div>
          <h1 className="mt-2 font-display text-3xl uppercase">{session.quiz.title}</h1>
          <div className="mt-6 rounded-md border border-white/15 bg-white/5 p-4 text-sm text-white/70">
            Waiting for the next question...
          </div>
        </div>
      </div>
    );
  }

  const submission = localPlayerId ? submissionFor(session, question.id, localPlayerId) : {};
  const hasSubmitted = submission.submitted === true;
  const acceptedVerdict = submission.accepted === true;
  const wrongVerdict = hasSubmitted && submission.accepted === false;
  const pointsAwarded =
    typeof submission.points_awarded === "number" ? submission.points_awarded : 0;
  const questionClosed = questionHasClosed(session, nowMs);
  const shouldRevealAnswers = hasSubmitted || questionClosed;

  return (
    <>
      <AnimatePresence>
        {introVisible && round ? (
          <RoundIntroSlate
            key={round.id}
            onComplete={handleIntroComplete}
            roundNumber={roundNumber}
            roundType={round.type}
          />
        ) : null}
      </AnimatePresence>

      <div className={`mx-auto max-w-6xl px-5 py-5 ${shouldRevealAnswers ? "pb-64" : "pb-32"}`}>
        <div className="flex items-center justify-between gap-3 pr-14 text-[10px] font-bold uppercase tracking-[0.5em] text-stagegold">
          <span>
            Round {roundNumber} · {round ? roundLabel(round.type) : ""}
          </span>
          <span className="text-white/55">
            Q{progress.index + 1}
            {progress.count > 0 ? ` / ${progress.count}` : ""}
          </span>
        </div>

        <section className="relative mt-3 overflow-hidden rounded-2xl bg-night p-6 text-white shadow-stage sm:p-8">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-stagegold/10 via-transparent to-transparent" />
          <div className="relative grid items-start gap-6 lg:grid-cols-[1fr_320px]">
            <motion.div
              animate={{ opacity: 1, y: 0 }}
              className={`rounded-xl bg-white p-5 text-midnight shadow-panel sm:p-7 ${
                wrongVerdict ? "animate-shake" : ""
              }`}
              initial={{ opacity: 0, y: 20 }}
              key={question.id}
              transition={{ duration: 0.25 }}
            >
              <PromptBlocksRenderer blocks={question.prompt_blocks} variant="play" />
            </motion.div>

            <aside className="space-y-4">
              <QuestionTimer session={session} />

              <div className="rounded-xl border border-white/15 bg-white/5 p-4">
                <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/55">
                  Your answer
                </div>
                <div className="mt-3">
                  <AnswerEntry
                    disabled={isUpdatingSession || hasSubmitted || questionClosed || !localPlayerId}
                    hasSubmitted={hasSubmitted}
                    onSubmit={onSubmitAnswer}
                    question={question}
                  />
                </div>

                {hasSubmitted ? (
                  <VerdictReveal
                    accepted={acceptedVerdict}
                    key={`${question.id}:${acceptedVerdict ? "accepted" : "wrong"}`}
                    pointsAwarded={pointsAwarded}
                  />
                ) : null}

                {sessionError ? (
                  <div className="mt-3 text-sm font-semibold text-inviteError">{sessionError}</div>
                ) : null}
              </div>

              <Button
                className="w-full uppercase tracking-wider"
                disabled={!isHost || isUpdatingSession}
                onClick={onAdvanceQuestion}
                type="button"
                variant="stage"
              >
                {isUpdatingSession ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Skip / next
              </Button>
              {!isHost ? (
                <div className="text-xs text-white/55">Questions advance automatically.</div>
              ) : null}
            </aside>
          </div>
        </section>
      </div>

      {shouldRevealAnswers ? (
        <AnswerRevealDock
          question={question}
          session={session}
          showWaiting={!questionClosed}
        />
      ) : null}
      <RoomChatPanel
        disabled={!localPlayerId}
        localPlayerId={localPlayerId}
        mode="drawer"
        onSendChat={onSendChat}
        session={session}
        tone="dark"
      />
      <Chyron session={session} />
    </>
  );
}

function VerdictReveal({
  accepted,
  pointsAwarded,
}: {
  accepted: boolean;
  pointsAwarded: number;
}) {
  return (
    <motion.div
      animate={{ scale: 1, opacity: 1 }}
      className={`mt-4 rounded-xl px-4 py-4 text-midnight ${
        accepted ? "bg-aqua" : "bg-coral text-white"
      }`}
      exit={{ opacity: 0, scale: 0.9 }}
      initial={{ scale: 0.8, opacity: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 18 }}
    >
      <div className="flex items-center gap-2 font-display text-3xl uppercase tracking-wide">
        {accepted ? <CheckCircle2 className="h-7 w-7" /> : <XCircle className="h-7 w-7" />}
        {accepted ? "That's it!" : "Not quite."}
      </div>
      <div className={`mt-1 text-xs font-bold uppercase tracking-[0.3em] ${accepted ? "text-midnight/65" : "text-white/75"}`}>
        +{pointsAwarded} {pointsAwarded === 1 ? "point" : "points"}
      </div>
    </motion.div>
  );
}

function AnswerRevealDock({
  question,
  session,
  showWaiting,
}: {
  question: Question;
  session: LiveSession;
  showWaiting: boolean;
}) {
  const submissions = asRecord(asRecord(session.state).submissions);
  const questionSubmissions = asRecord(submissions[question.id]);
  const acceptableAnswers = question.acceptable_answers.filter(
    (answer) => answer && answer !== question.canonical_answer,
  );
  const playerResponses = session.players
    .filter((player) => player.role === "player")
    .map((player) => {
      const response = asRecord(questionSubmissions[player.id]);
      const submitted = response.submitted === true;
      const accepted = response.accepted === true;
      const submittedText =
        typeof response.submitted_text === "string" && response.submitted_text.trim()
          ? response.submitted_text
          : "No answer";
      return { accepted, player, submitted, submittedText };
    });

  return (
    <motion.section
      animate={{ opacity: 1, y: 0 }}
      className="fixed inset-x-3 bottom-20 z-30 mx-auto max-w-5xl overflow-hidden rounded-2xl border border-stagegold/30 bg-midnight/95 text-white shadow-stage backdrop-blur"
      initial={{ opacity: 0, y: 24 }}
      transition={{ duration: 0.2 }}
    >
      <div className="grid gap-3 p-3 sm:grid-cols-[1fr_auto] sm:items-center sm:p-4">
        <div className="rounded-xl bg-white px-4 py-3 text-midnight">
          <div className="text-[10px] font-bold uppercase tracking-[0.3em] text-midnight/45">
            Correct
          </div>
          <div className="mt-1 text-base font-black leading-snug sm:text-lg">
            <InlineMathText text={question.canonical_answer || "Answer not configured"} />
          </div>
          {acceptableAnswers.length ? (
            <div className="mt-1 line-clamp-1 text-xs font-semibold text-midnight/60">
              Also accepted: {acceptableAnswers.slice(0, 3).join(", ")}
            </div>
          ) : null}
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1 sm:justify-end sm:pb-0">
          {playerResponses.map(({ accepted, player, submitted, submittedText }) => (
            <div
              className={`min-w-40 max-w-60 shrink-0 rounded-xl border px-3 py-2 ${
                submitted
                  ? accepted
                    ? "border-aqua/50 bg-aqua/15"
                    : "border-coral/50 bg-coral/15"
                  : "border-white/10 bg-white/5"
              }`}
              key={player.id}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="truncate text-[10px] font-black uppercase tracking-[0.2em] text-white/55">
                  {player.display_name}
                </div>
                <div
                  className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-black uppercase tracking-[0.16em] ${
                    submitted
                      ? accepted
                        ? "bg-aqua text-midnight"
                        : "bg-coral text-white"
                      : "bg-white/10 text-white/55"
                  }`}
                >
                  {submitted ? (accepted ? "Right" : "Miss") : showWaiting ? "..." : "Time"}
                </div>
              </div>
              <div className="mt-1 truncate text-sm font-semibold text-white">
                {submitted ? <InlineMathText text={submittedText} /> : showWaiting ? "Still answering..." : "No answer"}
              </div>
            </div>
          ))}
        </div>
      </div>
    </motion.section>
  );
}

function QuestionTimer({ session }: { session: LiveSession }) {
  const [now, setNow] = useState(Date.now());
  const state = asRecord(session.state);
  const rawStartedAt = state.question_started_at;
  const startedAtMs = typeof rawStartedAt === "string" ? Date.parse(rawStartedAt) : now;
  const safeStartedAtMs = Number.isFinite(startedAtMs) ? startedAtMs : now;
  const timeoutS = typeof state.question_timeout_s === "number" ? state.question_timeout_s : 25;
  const elapsedS = Math.max(0, (now - safeStartedAtMs) / 1000);
  const remainingS = Math.max(0, Math.ceil(timeoutS - elapsedS));
  const progress = timeoutS > 0 ? Math.max(0, Math.min(100, (remainingS / timeoutS) * 100)) : 0;
  const isUrgent = remainingS <= 5;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="rounded-xl border border-white/15 bg-white/5 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[10px] font-bold uppercase tracking-[0.4em] text-white/55">
          Time
        </span>
        <motion.span
          animate={isUrgent ? { scale: [1, 1.1, 1] } : { scale: 1 }}
          className={`font-display text-5xl leading-none tabular-nums ${
            isUrgent ? "text-coral" : "text-white"
          }`}
          transition={{ duration: 1, repeat: isUrgent ? Infinity : 0 }}
        >
          {remainingS}
        </motion.span>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
        <motion.div
          animate={{ width: `${progress}%` }}
          className={`h-full rounded-full ${isUrgent ? "bg-coral" : "bg-stagegold"}`}
          transition={{ duration: 0.2, ease: "linear" }}
        />
      </div>
    </div>
  );
}

function AnswerEntry({
  disabled,
  hasSubmitted,
  onSubmit,
  question,
}: {
  disabled: boolean;
  hasSubmitted: boolean;
  onSubmit: (input: {
    submitted_text?: string;
    submitted_payload?: Record<string, unknown>;
  }) => void;
  question: Question;
}) {
  const [answer, setAnswer] = useState("");
  const [justLockedIn, setJustLockedIn] = useState(false);

  useEffect(() => {
    setAnswer("");
    setJustLockedIn(false);
  }, [question.id]);

  function flashLockIn() {
    setJustLockedIn(true);
    window.setTimeout(() => setJustLockedIn(false), 400);
  }

  if (question.answer_widget.type === "multiple_choice") {
    const options = multipleChoiceOptions(question.answer_widget);
    return (
      <div className="grid gap-2">
        {options.map((option, index) => (
          <motion.button
            className="rounded-md border border-white/15 bg-white px-3 py-3 text-left text-sm font-semibold text-midnight transition hover:border-stagegold hover:bg-pale disabled:cursor-not-allowed disabled:opacity-60"
            disabled={disabled}
            key={option.id}
            onClick={() => {
              flashLockIn();
              onSubmit({
                submitted_text: option.label,
                submitted_payload: { choice_id: option.id, choice_index: index },
              });
            }}
            type="button"
            whileTap={{ scale: 0.97 }}
          >
            <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-md bg-midnight font-display text-xs text-white">
              {String.fromCharCode(65 + index)}
            </span>
            <InlineMathText text={option.label} />
          </motion.button>
        ))}
      </div>
    );
  }

  if (question.answer_widget.type !== "text_input") {
    return (
      <div className="rounded-md border border-white/15 bg-white/5 p-3 text-sm text-white/70">
        This answer format is in the question bank, but not in the live runner yet.
      </div>
    );
  }

  return (
    <form
      className="grid gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        const trimmed = answer.trim();
        if (trimmed) {
          flashLockIn();
          onSubmit({ submitted_text: trimmed });
        }
      }}
    >
      <motion.div animate={justLockedIn ? { scale: [1, 1.02, 1] } : { scale: 1 }} transition={{ duration: 0.3 }}>
        <Input
          className="h-12 border-white/15 bg-white text-midnight"
          disabled={disabled}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder={question.answer_widget.placeholder ?? "Type your answer"}
          value={answer}
        />
      </motion.div>
      <Button
        className="uppercase tracking-wider"
        disabled={disabled || !answer.trim()}
        type="submit"
        variant="stage"
      >
        {hasSubmitted ? (
          <>
            <CheckCircle2 className="h-4 w-4" />
            Locked
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4" />
            Lock it in
          </>
        )}
      </Button>
    </form>
  );
}

function multipleChoiceOptions(widget: Extract<AnswerWidget, { type: "multiple_choice" }>) {
  const rawOptions = widget.options?.length ? widget.options : widget.choices ?? [];
  return rawOptions.map((option, index) => {
    if (typeof option === "string") {
      return { id: option, label: option };
    }
    const label = option.text ?? option.label ?? option.id ?? `Choice ${index + 1}`;
    return { id: option.id ?? label, label };
  });
}

function RoomChatPanel({
  disabled,
  localPlayerId,
  mode = "panel",
  onSendChat,
  session,
  tone,
}: {
  disabled: boolean;
  localPlayerId: string | null;
  mode?: "panel" | "drawer";
  onSendChat: (message: string) => Promise<void>;
  session: LiveSession;
  tone: "dark" | "light";
}) {
  const messages = chatMessages(session).slice(-8);
  const [message, setMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isOpen, setIsOpen] = useState(mode === "panel");
  const [seenMessageCount, setSeenMessageCount] = useState(messages.length);
  const isDark = tone === "dark";
  const unreadCount = Math.max(0, messages.length - seenMessageCount);
  const panelHeightClass = "max-h-[calc(100vh-5rem)]";

  useEffect(() => {
    if (mode === "panel") {
      setIsOpen(true);
    }
  }, [mode]);

  useEffect(() => {
    if (isOpen) {
      setSeenMessageCount(messages.length);
    }
  }, [isOpen, messages.length]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed || disabled || isSending) {
      return;
    }

    setIsSending(true);
    try {
      await onSendChat(trimmed);
      setMessage("");
    } finally {
      setIsSending(false);
    }
  }

  const panel = (
    <section
      className={`flex ${panelHeightClass} flex-col rounded-xl border p-4 ${
        isDark
          ? "border-white/15 bg-midnight/95 text-white shadow-stage"
          : "border-softline bg-white text-midnight"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.35em] text-stagegold">
          <MessageCircle className="h-4 w-4" />
          Room chat
        </div>
        {mode === "drawer" ? (
          <button
            className="rounded-full p-1 text-white/65 transition hover:bg-white/10 hover:text-white"
            onClick={() => setIsOpen(false)}
            type="button"
          >
            <XCircle className="h-5 w-5" />
          </button>
        ) : null}
      </div>
      <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {messages.length ? (
          messages.map((item) => {
            const mine = item.player_id === localPlayerId;
            return (
              <div
                className={`rounded-lg px-3 py-2 ${
                  mine
                    ? "bg-aqua text-midnight"
                    : isDark
                      ? "bg-white/10 text-white"
                      : "bg-midnight/5 text-midnight"
                }`}
                key={item.id}
              >
                <div className={`text-[10px] font-black uppercase tracking-[0.22em] ${mine ? "text-midnight/55" : "text-stagegold"}`}>
                  {item.display_name}
                </div>
                <div className="mt-1 break-words text-sm font-semibold leading-relaxed">
                  {item.message}
                </div>
              </div>
            );
          })
        ) : (
          <div className={isDark ? "text-sm font-semibold text-white/45" : "text-sm font-semibold text-midnight/45"}>
            No messages yet.
          </div>
        )}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={handleSubmit}>
        <Input
          className={isDark ? "h-10 border-white/15 bg-white text-midnight" : "h-10"}
          disabled={disabled || isSending}
          maxLength={500}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Say something"
          value={message}
        />
        <Button
          className="shrink-0"
          disabled={disabled || isSending || !message.trim()}
          type="submit"
          variant="stage"
        >
          {isSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
          Send
        </Button>
      </form>
    </section>
  );

  if (mode === "drawer") {
    return (
      <>
        <button
          aria-label="Room chat"
          className="fixed right-3 top-3 z-40 inline-flex h-10 w-10 items-center justify-center rounded-full border border-stagegold/45 bg-stagegold text-midnight shadow-stage transition hover:bg-champagne"
          onClick={() => setIsOpen(true)}
          title="Room chat"
          type="button"
        >
          <MessageCircle className="h-5 w-5" />
          {unreadCount > 0 ? (
            <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-coral px-1 text-[10px] font-black text-white">
              {unreadCount}
            </span>
          ) : null}
        </button>
        <AnimatePresence>
          {isOpen ? (
            <motion.div
              animate={{ opacity: 1, y: 0 }}
              className="fixed inset-x-3 top-16 z-50 sm:left-auto sm:right-4 sm:w-[380px]"
              exit={{ opacity: 0, y: 16 }}
              initial={{ opacity: 0, y: 16 }}
              transition={{ duration: 0.18 }}
            >
              {panel}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </>
    );
  }

  return panel;
}

function Chyron({ session }: { session: LiveSession }) {
  return (
    <div className="fixed inset-x-0 bottom-0 z-20 border-t border-white/10 bg-midnight/95 px-4 py-3 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-center gap-3 overflow-x-auto">
        {session.players.map((player, index) => {
          const presence = playerPresence(session, player.id);
          return (
            <div
              className="flex shrink-0 items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5"
              key={player.id}
            >
              <span className={`h-2 w-2 rounded-full ${presence.online ? "bg-aqua" : "bg-white/25"}`} />
              <div
                className="flex h-7 w-7 items-center justify-center rounded-full font-display text-sm text-midnight"
                style={{ backgroundColor: playerColor(index) }}
              >
                {player.display_name.slice(0, 1).toUpperCase()}
              </div>
              <div className="text-xs font-semibold text-white">{player.display_name}</div>
              <ScoreNumber value={scoreFor(session, player.id)} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScoreNumber({ value }: { value: number }) {
  const [displayed, setDisplayed] = useState(value);
  const previousRef = useRef(value);

  useEffect(() => {
    const from = previousRef.current;
    const to = value;
    if (from === to) {
      return;
    }

    const start = performance.now();
    const duration = 600;
    let raf = 0;

    function step(now: number) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayed(Math.round(from + (to - from) * eased));
      if (t < 1) {
        raf = requestAnimationFrame(step);
      } else {
        previousRef.current = to;
      }
    }

    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return (
    <span className="font-display text-base text-stagegold tabular-nums">{displayed}</span>
  );
}

function FinishedRoom({
  localPlayerId,
  onBackHome,
  onFindSimilar,
  onPlayAgain,
  onSendChat,
  session,
}: {
  localPlayerId: string | null;
  onBackHome: () => void;
  onFindSimilar: (quiz: Quiz) => void;
  onPlayAgain: () => void;
  onSendChat: (message: string) => Promise<void>;
  session: LiveSession;
}) {
  const rankedPlayers = useMemo(
    () =>
      [...session.players].sort(
        (a, b) => scoreFor(session, b.id) - scoreFor(session, a.id),
      ),
    [session],
  );
  const winner = rankedPlayers[0] ?? null;
  const hasFiredRef = useRef(false);

  useEffect(() => {
    if (hasFiredRef.current) {
      return;
    }
    hasFiredRef.current = true;
    const fire = () => {
      confetti({
        particleCount: 90,
        spread: 70,
        startVelocity: 35,
        origin: { y: 0.55 },
        colors: ["#f7c948", "#72e0b3", "#e83a8e", "#3564ff", "#e8c87a"],
      });
    };
    fire();
    const t1 = window.setTimeout(fire, 320);
    const t2 = window.setTimeout(fire, 720);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-5 py-6 pb-32">
      <section className="relative overflow-hidden rounded-2xl bg-night p-8 text-white shadow-stage sm:p-12">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-champagne/15 via-transparent to-transparent" />
        <div className="relative text-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-champagne/40 bg-champagne/10 px-4 py-1.5 text-[10px] font-bold uppercase tracking-[0.5em] text-champagne">
            <Trophy className="h-4 w-4" />
            That's a wrap
          </div>
          <motion.div
            animate={{ scale: 1, opacity: 1 }}
            className="mt-6 font-display text-3xl uppercase tracking-wide text-white/85 sm:text-4xl"
            initial={{ scale: 0.8, opacity: 0 }}
            transition={{ type: "spring", stiffness: 240, damping: 18 }}
          >
            {session.quiz.title}
          </motion.div>
          {winner ? (
            <motion.div
              animate={{ scale: 1, opacity: 1 }}
              className="mt-8"
              initial={{ scale: 0.6, opacity: 0 }}
              transition={{ delay: 0.25, type: "spring", stiffness: 220, damping: 16 }}
            >
              <div className="text-[10px] font-bold uppercase tracking-[0.4em] text-champagne">
                Tonight's winner
              </div>
              <div className="mt-3 font-display text-6xl uppercase leading-none tracking-wide text-champagne sm:text-7xl">
                {winner.display_name}
              </div>
              <div className="mt-3 text-xs font-bold uppercase tracking-[0.4em] text-white/65">
                takes it · {scoreFor(session, winner.id)} pts
              </div>
            </motion.div>
          ) : null}
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button
              className="uppercase tracking-wider"
              onClick={onPlayAgain}
              type="button"
              variant="stage"
            >
              <RotateCcw className="h-4 w-4" />
              New lobby
            </Button>
            <Button
              className="bg-white text-midnight hover:bg-pale"
              onClick={() => onFindSimilar(session.quiz)}
              type="button"
            >
              <PlusCircle className="h-4 w-4" />
              Same topic
            </Button>
            <Button
              className="border border-white/20 bg-white/5 text-white hover:bg-white/10"
              onClick={onBackHome}
              type="button"
            >
              <Home className="h-4 w-4" />
              Home
            </Button>
          </div>
        </div>
      </section>

      <div className="mt-7">
        <section className="grid gap-3 sm:grid-cols-2">
          {rankedPlayers.map((player, index) => (
            <article
              className="rounded-xl border border-white/10 bg-white/5 p-4"
              key={player.id}
            >
              <div className="flex items-center gap-3">
                <div
                  className="flex h-12 w-12 items-center justify-center rounded-md font-display text-2xl text-midnight"
                  style={{ backgroundColor: playerColor(session.players.findIndex((p) => p.id === player.id)) }}
                >
                  {player.display_name.slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="truncate font-bold text-white">{player.display_name}</div>
                    {index === 0 ? <Crown className="h-4 w-4 text-champagne" /> : null}
                  </div>
                  <div className="font-display text-3xl tabular-nums text-stagegold">
                    {scoreFor(session, player.id)}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </section>
      </div>
      <RoomChatPanel
        disabled={!localPlayerId}
        localPlayerId={localPlayerId}
        mode="drawer"
        onSendChat={onSendChat}
        session={session}
        tone="dark"
      />
    </div>
  );
}
