import type { HealthResponse, LiveSession, Quiz, SessionJoinResponse } from "./types";

export type QuizOp =
  | {
      op: "quiz.update_metadata";
      patch: Partial<
        Pick<
          Quiz,
          | "title"
          | "description"
          | "category"
          | "topic"
          | "difficulty"
          | "status"
          | "visibility"
          | "anticheat_strictness"
          | "metadata"
        >
      >;
    }
  | {
      op: "question.update";
      question_id: string;
      patch: Record<string, unknown>;
    }
  | {
      op: "round.update_config";
      round_id: string;
      patch: Record<string, unknown>;
    }
  | {
      op: "items.bulk_set";
      round_id: string;
      items: Array<Record<string, unknown>>;
    };

const jsonHeaders = {
  "Content-Type": "application/json",
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers: {
      ...jsonHeaders,
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getHealth() {
  return request<HealthResponse>("/api/health/", { method: "GET" });
}

export function generateQuiz(input: { prompt: string; source_text?: string }) {
  return request<Quiz>("/api/authoring/generate/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function sendAuthoringChat(input: {
  messages: Array<{ role: "user" | "assistant"; content: string }>;
  mode?: string;
  current_quiz?: Record<string, unknown> | null;
  recent_quizzes?: Array<Record<string, unknown>>;
  source_text?: string;
}) {
  return request<{ reply: string }>("/api/authoring/chat/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function applyQuizOp(quizId: string, op: QuizOp) {
  return request<Quiz>(`/api/authoring/quizzes/${encodeURIComponent(quizId)}/ops/`, {
    method: "POST",
    body: JSON.stringify(op),
  });
}

export function listQuizzes(input?: { scope?: "play" | "authoring" }) {
  const params = new URLSearchParams();
  if (input?.scope) {
    params.set("scope", input.scope);
  }
  const query = params.toString();
  return request<Quiz[]>(`/api/quizzes/${query ? `?${query}` : ""}`, { method: "GET" });
}

export function createSession(input: {
  quiz_id: string;
  display_name?: string;
  question_count?: number;
}) {
  return request<SessionJoinResponse>("/api/sessions/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function joinSession(input: {
  invite_code?: string;
  session_id?: string;
  display_name: string;
}) {
  return request<SessionJoinResponse>("/api/sessions/join/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getSession(sessionId: string) {
  return request<LiveSession>(`/api/sessions/${encodeURIComponent(sessionId)}/`, {
    method: "GET",
  });
}

export function getSessionSocketUrl(sessionId: string, playerId?: string | null) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const params = new URLSearchParams();
  if (playerId) {
    params.set("player_id", playerId);
  }
  const query = params.toString();
  return `${protocol}//${window.location.host}/ws/session/${encodeURIComponent(sessionId)}/${query ? `?${query}` : ""}`;
}

export function setSessionPlayerReady(sessionId: string, playerId: string, isReady: boolean) {
  return request<LiveSession>(
    `/api/sessions/${encodeURIComponent(sessionId)}/players/${encodeURIComponent(playerId)}/ready/`,
    {
      method: "POST",
      body: JSON.stringify({ is_ready: isReady }),
    },
  );
}

export function startSession(sessionId: string, playerId: string) {
  return request<LiveSession>(`/api/sessions/${encodeURIComponent(sessionId)}/start/`, {
    method: "POST",
    body: JSON.stringify({ player_id: playerId }),
  });
}

export function submitSessionAnswer(
  sessionId: string,
  playerId: string,
  input: { submitted_text?: string; submitted_payload?: Record<string, unknown> },
) {
  return request<LiveSession>(
    `/api/sessions/${encodeURIComponent(sessionId)}/players/${encodeURIComponent(playerId)}/answer/`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function placeSessionWager(sessionId: string, playerId: string, points: number) {
  return request<LiveSession>(
    `/api/sessions/${encodeURIComponent(sessionId)}/players/${encodeURIComponent(playerId)}/wager/`,
    {
      method: "POST",
      body: JSON.stringify({ points }),
    },
  );
}

export function sendSessionChat(sessionId: string, playerId: string, message: string) {
  return request<LiveSession>(
    `/api/sessions/${encodeURIComponent(sessionId)}/players/${encodeURIComponent(playerId)}/chat/`,
    {
      method: "POST",
      body: JSON.stringify({ message }),
    },
  );
}

export function continueSessionQuestion(sessionId: string, playerId: string) {
  return request<LiveSession>(
    `/api/sessions/${encodeURIComponent(sessionId)}/players/${encodeURIComponent(playerId)}/continue/`,
    {
      method: "POST",
    },
  );
}

export function advanceSessionQuestion(sessionId: string, playerId: string) {
  return request<LiveSession>(`/api/sessions/${encodeURIComponent(sessionId)}/next/`, {
    method: "POST",
    body: JSON.stringify({ player_id: playerId }),
  });
}
