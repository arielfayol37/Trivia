import {
  Bot,
  CheckCircle2,
  Database,
  Flag,
  ImageIcon,
  KeyRound,
  Loader2,
  MessageSquareText,
  Rows3,
  Save,
  SendHorizontal,
  Sparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  applyQuizOp,
  generateQuiz,
  getHealth,
  listQuizzes,
  sendAuthoringChat,
} from "../../api/client";
import type { HealthResponse, Quiz } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Input, Textarea } from "../../components/ui/Field";
import { AnswerWidgetPreview } from "../play/AnswerWidgetPreview";
import { InlineMathText } from "../play/MathText";
import { PromptBlocksRenderer } from "../play/PromptBlocksRenderer";

const starterPrompt = "";

type QuizMetadataForm = Pick<
  Quiz,
  | "title"
  | "description"
  | "category"
  | "topic"
  | "difficulty"
  | "status"
  | "visibility"
  | "anticheat_strictness"
>;

type QuizQuestion = Quiz["rounds"][number]["questions"][number];
type AuthorRole = "assistant" | "user";
type AuthorMessage = {
  id: string;
  role: AuthorRole;
  content: string;
  quizId?: string;
};
type AuthoringMode = "auto" | "classic" | "image_sprint" | "list_race" | "meta_strategy";

const authoringModes: Array<{
  id: AuthoringMode;
  label: string;
  icon: typeof Sparkles;
  instruction: string;
}> = [
  {
    id: "auto",
    label: "Auto",
    icon: Sparkles,
    instruction: "Choose the strongest format for the user's topic.",
  },
  {
    id: "classic",
    label: "Question Set",
    icon: MessageSquareText,
    instruction:
      "Create synchronized question rounds with text_input and multiple_choice widgets where appropriate.",
  },
  {
    id: "image_sprint",
    label: "Image Sprint",
    icon: Flag,
    instruction:
      "Create an image-identification sprint using sync_open rounds, not list_race: each image question should use an image prompt block and the requested answer widget. This can be flags, maps, diagrams, screenshots, logos, landmarks, or specimens.",
  },
  {
    id: "list_race",
    label: "List Race",
    icon: Rows3,
    instruction:
      "Create a list_race round with config.prompt, config.time_limit_s, and config.items. Items need canonical and acceptable variants.",
  },
  {
    id: "meta_strategy",
    label: "Meta Mix",
    icon: ImageIcon,
    instruction:
      "Create mixed rounds, including at least one playable meta_strategy round where players see metadata.category_hint, choose a wager, then see the question.",
  },
];

const blankMetadataForm: QuizMetadataForm = {
  title: "",
  description: "",
  category: "general",
  topic: "",
  difficulty: "medium",
  status: "draft",
  visibility: "private",
  anticheat_strictness: "friendly",
};

const selectClassName =
  "h-10 w-full rounded-md border border-softline bg-white px-3 text-sm outline-none transition focus:border-electric focus:ring-2 focus:ring-softblue";

const categoryOptions: Array<{ value: Quiz["category"]; label: string }> = [
  { value: "science", label: "Science" },
  { value: "tv", label: "TV & Movies" },
  { value: "sports", label: "Sports" },
  { value: "geography", label: "Geography" },
  { value: "history", label: "History" },
  { value: "general", label: "General" },
];

function metadataFromQuiz(quiz: Quiz): QuizMetadataForm {
  return {
    title: quiz.title,
    description: quiz.description,
    category: quiz.category,
    topic: quiz.topic,
    difficulty: quiz.difficulty,
    status: quiz.status,
    visibility: quiz.visibility,
    anticheat_strictness: quiz.anticheat_strictness,
  };
}

function parseAnswerLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function newMessageId() {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

function initialAuthorMessages(): AuthorMessage[] {
  return [
    {
      id: newMessageId(),
      role: "assistant",
      content:
        "Tell me what you want to play, who it is for, and what format you have in mind. I can draft, revise, expand, or change the game mode.",
    },
  ];
}

function summarizeQuizForPrompt(quiz: Quiz | null) {
  if (!quiz) {
    return "No current draft.";
  }

  return JSON.stringify(
    {
      title: quiz.title,
      description: quiz.description,
      category: quiz.category,
      topic: quiz.topic,
      difficulty: quiz.difficulty,
      status: quiz.status,
      rounds: quiz.rounds.map((round) => ({
        type: round.type,
        order: round.order,
        config: round.config,
        questions: round.questions.map((question) => ({
          order: question.order,
          prompt_blocks: question.prompt_blocks,
          answer_widget: question.answer_widget,
          canonical_answer: question.canonical_answer,
          acceptable_answers: question.acceptable_answers,
          judge_mode: question.judge_mode,
          metadata: question.metadata,
        })),
      })),
    },
    null,
    2,
  ).slice(0, 14000);
}

function relatedQuizContext(quizzes: Quiz[], currentQuiz: Quiz | null) {
  return quizzes
    .filter((quiz) => quiz.id !== currentQuiz?.id)
    .slice(0, 12)
    .map((quiz) => ({
      title: quiz.title,
      topic: quiz.topic,
      difficulty: quiz.difficulty,
      rounds: quiz.rounds.length,
      questions: quiz.rounds.reduce((sum, round) => sum + round.questions.length, 0),
    }));
}

function buildConversationPrompt({
  currentQuiz,
  messages,
  mode,
  recentQuizzes,
}: {
  currentQuiz: Quiz | null;
  messages: AuthorMessage[];
  mode: AuthoringMode;
  recentQuizzes: Quiz[];
}) {
  const modeInstruction =
    authoringModes.find((item) => item.id === mode)?.instruction ?? authoringModes[0].instruction;
  const transcript = messages
    .map((message) => `${message.role.toUpperCase()}: ${message.content}`)
    .join("\n\n");

  return JSON.stringify(
    {
      task: "Continue a multi-turn quiz-authoring conversation and return the best complete quiz draft now.",
      authoring_mode: mode,
      mode_instruction: modeInstruction,
      conversation_transcript: transcript,
      current_draft: summarizeQuizForPrompt(currentQuiz),
      nearby_existing_quizzes: relatedQuizContext(recentQuizzes, currentQuiz),
      product_constraints: [
        "Avoid duplicating nearby existing quizzes unless the user explicitly asks for another version.",
        "Prefer structured prompt_blocks and answer_widget over plain text.",
        "Treat prompt blocks as composable. A quiz may contain multiple round types, and a single sync_open round may mix text-only, image, math, table, and source-excerpt questions.",
        "Support non-text play: image prompts, table prompts, math blocks, source excerpts, list_race rounds, image_choice, ordering, matching, and metadata for future pass/return flows.",
        "Prefer currently playable answer flows unless the user explicitly requests an experimental format: text_input, multiple_choice, image prompt plus text_input, list_race, image_choice, ordering, and matching.",
        "For Image Sprint mode, create sync_open questions with image prompt blocks and the requested answer widget. Do not create list_race rounds unless the user explicitly asks for a list race.",
        "For image or flag quizzes, preserve reliable source image URLs exactly in prompt_blocks[].url; otherwise make the image requirement explicit in metadata and alt/caption fields so assets can be attached later.",
        "For meta_strategy rounds, set min_bet, max_bet, default_bet, bet_window_s, answer_timeout_s, and metadata.category_hint on each question.",
        "If revising a current draft, preserve good material and make only the requested conceptual changes.",
      ],
    },
    null,
    2,
  );
}

export function QuizEditor() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [messages, setMessages] = useState<AuthorMessage[]>(initialAuthorMessages);
  const [chatInput, setChatInput] = useState(starterPrompt);
  const [authoringMode, setAuthoringMode] = useState<AuthoringMode>("auto");
  const [sourceText, setSourceText] = useState("");
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [recentQuizzes, setRecentQuizzes] = useState<Quiz[]>([]);
  const [isChatting, setIsChatting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
    listQuizzes({ scope: "authoring" }).then(setRecentQuizzes).catch(() => setRecentQuizzes([]));
  }, []);

  function handleQuizChange(nextQuiz: Quiz) {
    setQuiz(nextQuiz);
    setRecentQuizzes((current) => [
      nextQuiz,
      ...current.filter((item) => item.id !== nextQuiz.id),
    ]);
  }

  async function handleSendMessage(event: FormEvent) {
    event.preventDefault();
    const userContent = chatInput.trim();
    if (!userContent) {
      return;
    }

    const userMessage: AuthorMessage = {
      id: newMessageId(),
      role: "user",
      content: userContent,
    };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setChatInput("");
    setError(null);
    setIsChatting(true);
    try {
      const response = await sendAuthoringChat({
        messages: nextMessages.map(({ role, content }) => ({ role, content })),
        mode: authoringMode,
        current_quiz: quiz ? (quiz as unknown as Record<string, unknown>) : null,
        recent_quizzes: recentQuizzes.map((item) => item as unknown as Record<string, unknown>),
        source_text: sourceText,
      });
      setMessages((current) => [
        ...current,
        {
          id: newMessageId(),
          role: "assistant",
          content: response.reply,
        },
      ]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not send authoring message";
      setError(message);
      setMessages((current) => [
        ...current,
        {
          id: newMessageId(),
          role: "assistant",
          content: `I could not reach the authoring model. ${message}`,
        },
      ]);
    } finally {
      setIsChatting(false);
    }
  }

  async function handleGenerateDraft() {
    const pendingContent = chatInput.trim();
    const pendingMessage: AuthorMessage | null = pendingContent
      ? {
          id: newMessageId(),
          role: "user",
          content: pendingContent,
        }
      : null;
    const nextMessages = pendingMessage ? [...messages, pendingMessage] : messages;
    if (pendingMessage) {
      setMessages(nextMessages);
      setChatInput("");
    }
    setIsGenerating(true);
    setError(null);
    try {
      const nextQuiz = await generateQuiz({
        prompt: buildConversationPrompt({
          currentQuiz: quiz,
          messages: nextMessages,
          mode: authoringMode,
          recentQuizzes,
        }),
        source_text: sourceText,
      });
      handleQuizChange(nextQuiz);
      setMessages((current) => [
        ...current,
        {
          id: newMessageId(),
          role: "assistant",
          content: `Drafted "${nextQuiz.title}" with ${nextQuiz.rounds.length} round${
            nextQuiz.rounds.length === 1 ? "" : "s"
          }. Tell me what to change next.`,
          quizId: nextQuiz.id,
        },
      ]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not generate quiz";
      setError(message);
      setMessages((current) => [
        ...current,
        {
          id: newMessageId(),
          role: "assistant",
          content: `I could not create a valid draft from that turn. ${message}`,
        },
      ]);
    } finally {
      setIsGenerating(false);
    }
  }

  const selectedQuiz = quiz;

  return (
    <main className="min-h-screen bg-midnight text-white">
      <div className="border-b border-white/10 bg-midnight">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.4em] text-stagegold">
              <Sparkles className="h-4 w-4" />
              The booth
            </div>
            <h1 className="mt-2 font-display text-3xl uppercase tracking-wide text-white">
              Quiz authoring
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <a
              className="inline-flex h-10 items-center justify-center rounded-md bg-white px-4 text-sm font-bold text-midnight transition-colors hover:bg-pale focus:outline-none focus:ring-2 focus:ring-stagegold focus:ring-offset-2 focus:ring-offset-midnight"
              href="/"
            >
              Play hub
            </a>
            <div className="flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/70">
              <Database className="h-4 w-4" />
              API {health?.ok ? "connected" : "not connected"}
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-7xl gap-5 px-5 py-5 lg:grid-cols-[420px_1fr]">
        <section className="rounded-xl border border-white/10 bg-night shadow-stage">
          <div className="border-b border-white/10 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Bot className="h-4 w-4 text-aqua" />
              AI producer
            </div>
          </div>
          <form className="space-y-4 p-4" onSubmit={handleSendMessage}>
            <div>
              <div className="mb-2 text-xs font-bold uppercase tracking-[0.25em] text-white/55">
                Format
              </div>
              <div className="grid grid-cols-2 gap-2">
                {authoringModes.map((mode) => {
                  const Icon = mode.icon;
                  return (
                    <button
                      className={`flex items-center gap-2 rounded-md border px-3 py-2 text-left text-xs font-semibold transition ${
                        authoringMode === mode.id
                          ? "border-stagegold bg-stagegold text-midnight"
                          : "border-white/10 bg-white/5 text-white/70 hover:border-stagegold/70 hover:text-white"
                      }`}
                      key={mode.id}
                      onClick={() => setAuthoringMode(mode.id)}
                      type="button"
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {mode.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="max-h-80 space-y-3 overflow-y-auto rounded-md border border-white/10 bg-midnight/60 p-3">
              {messages.map((message) => (
                <div
                  className={`rounded-md px-3 py-2 text-sm leading-6 ${
                    message.role === "user"
                      ? "ml-6 bg-stagegold text-midnight"
                      : "mr-6 border border-white/10 bg-white/5 text-white/75"
                  }`}
                  key={message.id}
                >
                  <div className="mb-1 text-[10px] font-bold uppercase tracking-[0.3em] opacity-60">
                    {message.role === "user" ? "You" : "AI"}
                  </div>
                  {message.content}
                </div>
              ))}
              {isChatting || isGenerating ? (
                <div className="mr-6 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/60">
                  <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                  {isGenerating ? "Building a validated draft..." : "Thinking..."}
                </div>
              ) : null}
            </div>

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-[0.25em] text-white/55">
                Message
              </span>
              <Textarea
                className="min-h-28"
                placeholder="Ask for a quiz, then revise it: make it harder, add a flag sprint, split this into categories..."
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-[0.25em] text-white/55">
                Source material
              </span>
              <Textarea
                className="min-h-20"
                placeholder="Paste notes, lecture excerpts, image URLs, question banks, or source passages..."
                value={sourceText}
                onChange={(event) => setSourceText(event.target.value)}
              />
            </label>
            {error ? (
              <div className="rounded-md border border-coral/40 bg-coral/10 px-3 py-2 text-sm text-coral">
                {error}
              </div>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                className="w-full bg-white text-midnight hover:bg-pale disabled:bg-white/10 disabled:text-white/35"
                disabled={isChatting || isGenerating || !chatInput.trim()}
                type="submit"
              >
                {isChatting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <SendHorizontal className="h-4 w-4" />
                )}
                Send
              </Button>
              <Button
                className="w-full"
                disabled={isChatting || isGenerating || (messages.length < 2 && !chatInput.trim())}
                onClick={handleGenerateDraft}
                type="button"
                variant="stage"
              >
              {isGenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
                {quiz ? "Update draft" : "Draft now"}
              </Button>
            </div>
          </form>

          <div className="border-t border-white/10 p-4">
            <div className="mb-3 text-xs font-bold uppercase tracking-[0.25em] text-white/55">
              Recent quizzes
            </div>
            <div className="space-y-2">
              {recentQuizzes.length === 0 ? (
                <div className="rounded-md border border-white/10 bg-white/5 px-3 py-3 text-sm text-white/60">
                  Generated quizzes will appear here.
                </div>
              ) : (
                recentQuizzes.slice(0, 5).map((item) => (
                  <button
                    className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-left text-sm text-white hover:border-stagegold/60 hover:bg-white/10"
                    key={item.id}
                    onClick={() => setQuiz(item)}
                    type="button"
                  >
                    <div className="font-medium">{item.title}</div>
                    <div className="text-xs text-white/55">
                      {item.status} · {item.category} · {item.rounds.length} rounds · {item.difficulty}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </section>

        <QuizPreview quiz={selectedQuiz} onQuizChange={handleQuizChange} />
      </div>
    </main>
  );
}

function QuizPreview({
  quiz,
  onQuizChange,
}: {
  quiz: Quiz | null;
  onQuizChange: (quiz: Quiz) => void;
}) {
  const [metadataForm, setMetadataForm] = useState<QuizMetadataForm>(blankMetadataForm);
  const [isSavingMetadata, setIsSavingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const [metadataSaved, setMetadataSaved] = useState(false);
  const [isReviewingQuestions, setIsReviewingQuestions] = useState(false);
  const questionCount = useMemo(
    () => quiz?.rounds.reduce((sum, round) => sum + round.questions.length, 0) ?? 0,
    [quiz],
  );
  useEffect(() => {
    if (!quiz) {
      setMetadataForm(blankMetadataForm);
      return;
    }
    setMetadataForm(metadataFromQuiz(quiz));
    setMetadataError(null);
    setMetadataSaved(false);
    setIsReviewingQuestions(false);
  }, [quiz?.id]);

  function updateMetadataField<Key extends keyof QuizMetadataForm>(
    field: Key,
    value: QuizMetadataForm[Key],
  ) {
    setMetadataForm((current) => ({ ...current, [field]: value }));
    setMetadataSaved(false);
  }

  async function handleSaveMetadata(event: FormEvent) {
    event.preventDefault();
    if (!quiz) {
      return;
    }

    setIsSavingMetadata(true);
    setMetadataError(null);
    setMetadataSaved(false);
    try {
      const updatedQuiz = await applyQuizOp(quiz.id, {
        op: "quiz.update_metadata",
        patch: metadataForm,
      });
      onQuizChange(updatedQuiz);
      setMetadataSaved(true);
    } catch (err) {
      setMetadataError(err instanceof Error ? err.message : "Could not save quiz metadata");
    } finally {
      setIsSavingMetadata(false);
    }
  }

  async function handleSetStatus(nextStatus: Quiz["status"]) {
    if (!quiz) {
      return;
    }

    setIsSavingMetadata(true);
    setMetadataError(null);
    setMetadataSaved(false);
    try {
      const updatedQuiz = await applyQuizOp(quiz.id, {
        op: "quiz.update_metadata",
        patch: { status: nextStatus },
      });
      onQuizChange(updatedQuiz);
      setMetadataForm(metadataFromQuiz(updatedQuiz));
      setMetadataSaved(true);
    } catch (err) {
      setMetadataError(err instanceof Error ? err.message : "Could not update quiz state");
    } finally {
      setIsSavingMetadata(false);
    }
  }

  if (!quiz) {
    return (
      <section className="flex min-h-[520px] items-center justify-center rounded-md border border-softline bg-white p-6 text-midnight shadow-panel">
        <div className="max-w-md text-center">
          <Sparkles className="mx-auto h-8 w-8 text-electric" />
          <h2 className="mt-3 text-xl font-semibold">Generate a quiz draft</h2>
          <p className="mt-2 text-sm leading-6 text-midnight/60">
            The preview will render structured prompt blocks and answer widgets, so this
            starts as an interactive schema rather than a pile of text.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-md border border-softline bg-white text-midnight shadow-panel">
      <form className="border-b border-softline p-5" onSubmit={handleSaveMetadata}>
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="grid flex-1 gap-3">
            <div className="grid gap-3 md:grid-cols-[1.5fr_0.8fr_1fr]">
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">Title</span>
                <Input
                  value={metadataForm.title}
                  onChange={(event) => updateMetadataField("title", event.target.value)}
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                  Category
                </span>
                <select
                  className={selectClassName}
                  value={metadataForm.category}
                  onChange={(event) =>
                    updateMetadataField("category", event.target.value as Quiz["category"])
                  }
                >
                  {categoryOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">Topic</span>
                <Input
                  value={metadataForm.topic}
                  onChange={(event) => updateMetadataField("topic", event.target.value)}
                />
              </label>
            </div>
            <label className="block">
              <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                Description
              </span>
              <Textarea
                className="min-h-20"
                value={metadataForm.description}
                onChange={(event) => updateMetadataField("description", event.target.value)}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-4">
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                  Difficulty
                </span>
                <select
                  className={selectClassName}
                  value={metadataForm.difficulty}
                  onChange={(event) =>
                    updateMetadataField("difficulty", event.target.value as Quiz["difficulty"])
                  }
                >
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                  State
                </span>
                <select
                  className={selectClassName}
                  value={metadataForm.status}
                  onChange={(event) =>
                    updateMetadataField("status", event.target.value as Quiz["status"])
                  }
                >
                  <option value="draft">Draft</option>
                  <option value="ready">Ready</option>
                  <option value="archived">Archived</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                  Visibility
                </span>
                <select
                  className={selectClassName}
                  value={metadataForm.visibility}
                  onChange={(event) =>
                    updateMetadataField("visibility", event.target.value as Quiz["visibility"])
                  }
                >
                  <option value="private">Private</option>
                  <option value="public">Public</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium uppercase text-midnight/60">
                  Anti-cheat
                </span>
                <select
                  className={selectClassName}
                  value={metadataForm.anticheat_strictness}
                  onChange={(event) =>
                    updateMetadataField(
                      "anticheat_strictness",
                      event.target.value as Quiz["anticheat_strictness"],
                    )
                  }
                >
                  <option value="friendly">Friendly</option>
                  <option value="strict">Strict</option>
                  <option value="off">Off</option>
                </select>
              </label>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row xl:flex-col">
            <div
              className={`rounded-md px-3 py-2 text-xs font-bold uppercase tracking-[0.25em] ${
                quiz.status === "ready"
                  ? "bg-aqua text-midnight"
                  : quiz.status === "archived"
                    ? "bg-paper text-midnight/55"
                    : "bg-stagegold/20 text-midnight"
              }`}
            >
              {quiz.status}
            </div>
            <Button disabled={isSavingMetadata || !metadataForm.title.trim()} type="submit">
              {isSavingMetadata ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : metadataSaved ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {metadataSaved ? "Saved" : "Save changes"}
            </Button>
            {quiz.status === "ready" ? (
              <Button
                className="bg-chip text-midnight hover:bg-chipHover"
                disabled={isSavingMetadata}
                onClick={() => handleSetStatus("draft")}
                type="button"
              >
                Move to draft
              </Button>
            ) : (
              <Button
                className="bg-aqua text-midnight hover:bg-aquaHover"
                disabled={isSavingMetadata}
                onClick={() => handleSetStatus("ready")}
                type="button"
              >
                <CheckCircle2 className="h-4 w-4" />
                Mark ready
              </Button>
            )}
          </div>
        </div>
        {metadataError ? (
          <div className="mt-3 rounded-md border border-coral/40 bg-coral/10 px-3 py-2 text-sm text-coral">
            {metadataError}
          </div>
        ) : null}
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <Metric label="State" value={quiz.status} />
          <Metric label="Rounds" value={quiz.rounds.length} />
          <Metric label="Questions" value={questionCount} />
          <Metric label="Anti-cheat" value={quiz.anticheat_strictness} />
        </div>
      </form>

      <div className="border-b border-softline p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold">Quiz blueprint</h3>
            <p className="mt-1 text-sm leading-6 text-midnight/60">
              Use this as the quick sanity check. Open the questions only when you want to inspect
              or patch a specific answer key.
            </p>
          </div>
          <Button
            className="shrink-0 bg-chip text-midnight hover:bg-chipHover"
            onClick={() => setIsReviewingQuestions((current) => !current)}
            type="button"
          >
            <Rows3 className="h-4 w-4" />
            {isReviewingQuestions ? "Hide questions" : "Review questions"}
          </Button>
        </div>

        <div className="mt-4 grid gap-3">
          {quiz.rounds.map((round) => (
            <div
              className="rounded-md border border-softline bg-paper px-4 py-3"
              key={round.id}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="text-xs font-medium uppercase text-midnight/55">
                    Round {round.order}
                  </div>
                  <div className="font-semibold">{roundLabel(round.type)}</div>
                  <div className="mt-1 text-sm text-midnight/60">
                    {roundSummary(round)}
                  </div>
                </div>
                <code className="rounded bg-white px-2 py-1 text-xs text-midnight/60">
                  {round.type}
                </code>
              </div>
            </div>
          ))}
        </div>
      </div>

      {isReviewingQuestions ? (
        <div className="space-y-4 p-5">
          {quiz.rounds.map((round) => (
            <div className="rounded-md border border-softline" key={round.id}>
              <div className="flex flex-col gap-2 border-b border-softline bg-paper px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs font-medium uppercase text-midnight/55">
                    Round {round.order}
                  </div>
                  <div className="font-semibold">{roundLabel(round.type)}</div>
                </div>
                <code className="rounded bg-white px-2 py-1 text-xs text-midnight/60">
                  {round.type}
                </code>
              </div>

              {round.type === "list_race" ? (
                <ListRacePreview config={round.config} />
              ) : (
                <div className="divide-y divide-line">
                  {round.questions.map((question) => (
                    <QuestionDraftEditor
                      key={question.id}
                      onQuizChange={onQuizChange}
                      question={question}
                      quizId={quiz.id}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function QuestionDraftEditor({
  quizId,
  question,
  onQuizChange,
}: {
  quizId: string;
  question: QuizQuestion;
  onQuizChange: (quiz: Quiz) => void;
}) {
  const [canonicalAnswer, setCanonicalAnswer] = useState(question.canonical_answer);
  const [acceptableText, setAcceptableText] = useState(question.acceptable_answers.join("\n"));
  const [isSaving, setIsSaving] = useState(false);
  const [isEditingAnswerKey, setIsEditingAnswerKey] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setCanonicalAnswer(question.canonical_answer);
    setAcceptableText(question.acceptable_answers.join("\n"));
    setIsEditingAnswerKey(false);
    setError(null);
    setSaved(false);
  }, [question.id]);

  async function handleSaveQuestionAnswer(event: FormEvent) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updatedQuiz = await applyQuizOp(quizId, {
        op: "question.update",
        question_id: question.id,
        patch: {
          canonical_answer: canonicalAnswer,
          acceptable_answers: parseAnswerLines(acceptableText),
        },
      });
      onQuizChange(updatedQuiz);
      setSaved(true);
      setIsEditingAnswerKey(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save answer key");
    } finally {
      setIsSaving(false);
    }
  }

  const acceptedAnswerCount = Math.max(1, question.acceptable_answers.length);

  if (!isEditingAnswerKey) {
    return (
      <div className="grid gap-4 p-4 xl:grid-cols-[1fr_280px]">
        <div>
          <div className="mb-2 text-xs font-medium uppercase text-midnight/55">
            Question {question.order} · {question.judge_mode}
          </div>
          <PromptBlocksRenderer blocks={question.prompt_blocks} />
        </div>
        <aside className="space-y-3">
          <AnswerWidgetPreview widget={question.answer_widget} />
          <div className="rounded-md border border-softline bg-paper p-3 text-sm text-midnight/65">
            <div className="flex items-center gap-2 text-xs font-medium uppercase text-midnight/60">
              <KeyRound className="h-4 w-4" />
              Answer key ready
            </div>
            <div className="mt-2">
              {acceptedAnswerCount} accepted {acceptedAnswerCount === 1 ? "answer" : "answers"}
            </div>
            <Button
              className="mt-3 w-full bg-chip text-midnight hover:bg-chipHover"
              onClick={() => setIsEditingAnswerKey(true)}
              type="button"
            >
              Edit answer key
            </Button>
          </div>
        </aside>
      </div>
    );
  }

  return (
    <form className="grid gap-4 p-4 xl:grid-cols-[1fr_320px]" onSubmit={handleSaveQuestionAnswer}>
      <div>
        <div className="mb-2 text-xs font-medium uppercase text-midnight/55">
          Question {question.order} · {question.judge_mode}
        </div>
        <PromptBlocksRenderer blocks={question.prompt_blocks} />
        <div className="mt-3 text-xs text-midnight/60">
          Canonical:{" "}
          <span className="font-medium text-midnight">
            <InlineMathText text={canonicalAnswer} />
          </span>
        </div>
      </div>
      <aside className="space-y-3">
        <AnswerWidgetPreview widget={question.answer_widget} />
        <div className="rounded-md border border-softline bg-paper p-3">
          <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase text-midnight/60">
            <KeyRound className="h-4 w-4" />
            Answer key
          </div>
          <label className="block">
            <span className="mb-2 block text-xs font-medium uppercase text-midnight/55">
              Canonical answer
            </span>
            <Input
              value={canonicalAnswer}
              onChange={(event) => {
                setCanonicalAnswer(event.target.value);
                setSaved(false);
              }}
            />
          </label>
          <label className="mt-3 block">
            <span className="mb-2 block text-xs font-medium uppercase text-midnight/55">
              Acceptable answers
            </span>
            <Textarea
              className="min-h-24"
              value={acceptableText}
              onChange={(event) => {
                setAcceptableText(event.target.value);
                setSaved(false);
              }}
            />
          </label>
          {error ? (
            <div className="mt-3 rounded-md border border-coral/40 bg-coral/10 px-3 py-2 text-sm text-coral">
              {error}
            </div>
          ) : null}
          <Button className="mt-3 w-full" disabled={isSaving || !canonicalAnswer.trim()} type="submit">
            {isSaving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : saved ? (
              <CheckCircle2 className="h-4 w-4" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {saved ? "Saved" : "Save answer"}
          </Button>
        </div>
      </aside>
    </form>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-softline bg-paper px-3 py-2">
      <div className="text-xs font-medium uppercase text-midnight/55">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function roundLabel(type: Quiz["rounds"][number]["type"]) {
  switch (type) {
    case "sync_open":
      return "Synchronized open-answer";
    case "list_race":
      return "List race";
    case "meta_strategy":
      return "Meta-strategy";
    case "buzz_in":
      return "Buzz-in";
  }
}

function roundSummary(round: Quiz["rounds"][number]) {
  if (round.type === "list_race") {
    const items = Array.isArray(round.config.items) ? round.config.items.length : 0;
    return `${items} item${items === 1 ? "" : "s"} in one timed sprint`;
  }

  const questionText = `${round.questions.length} question${round.questions.length === 1 ? "" : "s"}`;
  const widgets = Array.from(
    new Set(round.questions.map((question) => question.answer_widget.type.replace("_", " "))),
  );
  return widgets.length ? `${questionText} · ${widgets.join(", ")}` : questionText;
}

function ListRacePreview({ config }: { config: Record<string, unknown> }) {
  const items = Array.isArray(config.items) ? config.items : [];
  return (
    <div className="p-4">
      <div className="text-sm font-medium">
        <InlineMathText text={String(config.prompt ?? "List race prompt")} />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item, index) => {
          const label =
            typeof item === "object" && item && "canonical" in item
              ? String((item as { canonical: unknown }).canonical)
              : `Item ${index + 1}`;
          return (
            <div className="rounded-md border border-softline bg-paper px-3 py-2 text-sm" key={label}>
              <InlineMathText text={label} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
