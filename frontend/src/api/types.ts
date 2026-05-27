export type PromptBlock =
  | { type: "text"; text: string }
  | { type: "image"; url?: string; alt?: string; caption?: string }
  | { type: "table"; columns: string[]; rows: Array<Array<string | number>> }
  | { type: "math"; latex: string }
  | { type: "source_excerpt"; text: string; citation?: string }
  | { type: "diagram_spec"; title?: string; spec?: Record<string, unknown> };

export type AnswerWidget =
  | { type: "text_input"; placeholder?: string }
  | { type: "list_input"; placeholder?: string }
  | {
      type: "multiple_choice";
      choices?: string[];
      options?: Array<{ id?: string; text?: string; label?: string } | string>;
      multi?: boolean;
    }
  | { type: "ordering"; items: string[] }
  | { type: "matching"; left: string[]; right: string[] }
  | { type: "image_choice"; images: Array<{ url?: string; alt?: string; label?: string }> }
  | { type: "hotspot"; image_url?: string; regions?: Array<{ id: string; label: string }> };

export type Question = {
  id: string;
  order: number;
  prompt_blocks: PromptBlock[];
  answer_widget: AnswerWidget;
  canonical_answer: string;
  acceptable_answers: string[];
  judge_mode: "fuzzy" | "llm";
  judge_config: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

export type Round = {
  id: string;
  order: number;
  type: "meta_strategy" | "list_race" | "buzz_in" | "sync_open";
  config: Record<string, unknown>;
  questions: Question[];
};

export type Quiz = {
  id: string;
  title: string;
  description: string;
  category: "science" | "tv" | "sports" | "geography" | "history" | "general";
  topic: string;
  difficulty: "easy" | "medium" | "hard";
  status: "draft" | "ready" | "archived";
  visibility: "private" | "public";
  anticheat_strictness: "strict" | "friendly" | "off";
  schema_version: number;
  metadata: Record<string, unknown>;
  rounds: Round[];
  created_at: string;
  updated_at: string;
};

export type HealthResponse = {
  ok: boolean;
  service: string;
};

export type SessionPlayer = {
  id: string;
  display_name: string;
  role: "player" | "spectator";
  is_host: boolean;
  is_ready: boolean;
  joined_at: string;
  left_at: string | null;
};

export type SessionChatMessage = {
  id: string;
  player_id: string;
  display_name: string;
  message: string;
  created_at: string;
};

export type LiveSession = {
  id: string;
  invite_code: string;
  quiz: Quiz;
  status: "lobby" | "playing" | "finished" | "abandoned";
  current_round_idx: number;
  current_question_idx: number;
  state: Record<string, unknown>;
  players: SessionPlayer[];
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
};

export type SessionJoinResponse = {
  session: LiveSession;
  player_id: string;
};
