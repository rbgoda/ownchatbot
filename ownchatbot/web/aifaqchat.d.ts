// Type definitions for aifaqchat
// Project: https://github.com/rbgoda/aifaqchat

export interface FaqItem {
  /** Unique id (referenced by `suggest` and used to de-dupe chips). */
  id: string;
  /** Question — shown on the suggestion chip and as the user's line. */
  q: string;
  /** Answer — light HTML/markdown allowed; sanitized before render. */
  a: string;
  /** Lowercase keywords for offline matching (multi-word phrases score higher). */
  kw?: string[];
  /** Optional grouping/topic; matching it boosts the entry. */
  topic?: string;
}

/** UI strings — override any subset for i18n / custom wording. */
export interface FaqStrings {
  greeting?: string;
  title?: string;
  subtitle?: string;
  placeholder?: string;
  inputLabel?: string;
  sendLabel?: string;
  closeLabel?: string;
  askLabel?: string;
  helpfulPrompt?: string;
  helpfulYes?: string;
  helpfulNo?: string;
  thanks?: string;
  fallback?: string;
}

export interface AiFaqChatConfig {
  product?: string;
  accent?: string;
  /** Colour scheme. @default "dark" */
  theme?: "dark" | "light" | "auto";
  /** URL to a KB JSON (array or `{ suggest, items }`). */
  kb?: string;
  /** Inline KB array — skips the fetch, works fully offline. */
  items?: FaqItem[];
  /** Inline suggested-question ids (starter chips). */
  suggest?: string[];
  /** POST endpoint for server/LLM answers: `{question, history}` → `{answer, sources, suggestions}`. */
  ask?: string;
  /** SSE endpoint for streamed answers (takes precedence over `ask`). */
  stream?: string;
  /** Support email shown in no-match fallbacks. */
  email?: string;
  position?: "right" | "left";
  /** Small header badge text (derived from `product` if omitted). */
  mark?: string;
  greeting?: string;
  /** Overridable UI strings (i18n). */
  strings?: FaqStrings;
}

export type FaqEvent = "open" | "close" | "ask" | "answer" | "unanswered" | "feedback";

export interface FaqEventPayload {
  question?: string;
  answer?: string | null;
  answered?: boolean;
  source?: "kb" | "server" | "none";
  id?: string;
  helpful?: boolean;
}

export interface AiFaqChatApi {
  open(): void;
  close(): void;
  config: AiFaqChatConfig;
  /** Subscribe to a widget event. Returns the api for chaining. */
  on(event: FaqEvent, cb: (payload: FaqEventPayload) => void): AiFaqChatApi;
}

declare global {
  interface Window {
    aifaqchat?: AiFaqChatConfig;
    AiFaqChat?: AiFaqChatApi;
  }
}

export {};
