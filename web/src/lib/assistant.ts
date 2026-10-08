/**
 * AI TrafficOS - AI Assistant Client & Primitives
 *
 * Contract Assumptions (Phase 9 backend track):
 * Endpoint: POST {API_BASE}/api/v1/assistant/chat
 * Auth: Bearer JWT in Authorization header
 *
 * Request format:
 *   {
 *     "message": "string",
 *     "history": [{ "role": "user" | "assistant", "content": "string" }],
 *     "conversation_id": "optional-uuid"
 *   }
 *
 * Response 200 format:
 *   {
 *     "answer": "markdown string",
 *     "conversation_id": "uuid",
 *     "tool_calls": [{ "tool": "name", "arguments": {...}, "result_summary": "string" }],
 *     "provenance": [{ "segment": "quote/paraphrase", "label": "observed" | "predicted" | "recommended" }],
 *     "insufficient_data": false,
 *     "suggested_followups": ["..."]
 *   }
 *
 * HTTP Error mappings:
 *   - 401: AssistantAuthError -> Trigger logout via auth context / redirect to sign in
 *   - 403: AssistantForbiddenError -> Permission-restriction panel (role not authorized)
 *   - 429 / 5xx: AssistantServerError -> Retryable error state
 *   - Network error: AssistantNetworkError -> Retryable error state
 *   - Request timeout (default 60s): AssistantTimeoutError -> Cancel + retry state
 *   - insufficient_data=true: 200 OK with limited answer -> "Limited data" amber banner
 */

import React from "react";
import { getBaseUrl, getStoredTokens } from "./api-client";

// ============================================================================
// Core Types & Interfaces
// ============================================================================

export type AssistantRole = "user" | "assistant";

export interface ChatHistoryEntry {
  role: AssistantRole;
  content: string;
}

export interface AssistantChatRequest {
  message: string;
  history: ChatHistoryEntry[];
  conversation_id?: string;
}

export interface ToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  result_summary: string;
}

export type ProvenanceLabel = "observed" | "predicted" | "recommended";

export interface ProvenanceSegment {
  segment: string;
  label: ProvenanceLabel;
}

export interface AssistantChatResponse {
  answer: string;
  conversation_id: string;
  tool_calls: ToolCall[];
  provenance: ProvenanceSegment[];
  insufficient_data: boolean;
  suggested_followups: string[];
}

export interface ChatMessage {
  id: string;
  role: AssistantRole;
  content: string;
  timestamp: string; // ISO string
  conversationId?: string;
  toolCalls?: ToolCall[];
  provenance?: ProvenanceSegment[];
  insufficientData?: boolean;
  suggestedFollowups?: string[];
  isError?: boolean;
  errorType?: "auth" | "forbidden" | "server" | "timeout" | "network";
  errorMessage?: string;
}

export interface ConversationSession {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

// ============================================================================
// Typed Error Classes
// ============================================================================

export class AssistantError extends Error {
  status: number;
  retryable: boolean;

  constructor(message: string, status: number = 0, retryable: boolean = false) {
    super(message);
    this.name = "AssistantError";
    this.status = status;
    this.retryable = retryable;
  }
}

export class AssistantAuthError extends AssistantError {
  constructor(message: string = "Session expired. Please sign in again.") {
    super(message, 401, false);
    this.name = "AssistantAuthError";
  }
}

export class AssistantForbiddenError extends AssistantError {
  role?: string;

  constructor(message: string = "Your role cannot access the assistant.", role?: string) {
    super(message, 403, false);
    this.name = "AssistantForbiddenError";
    this.role = role;
  }
}

export class AssistantServerError extends AssistantError {
  constructor(
    message: string = "Assistant service error. Please try again.",
    status: number = 500
  ) {
    super(message, status, true);
    this.name = "AssistantServerError";
  }
}

export class AssistantTimeoutError extends AssistantError {
  constructor(message: string = "Request timed out after 60 seconds.") {
    super(message, 408, true);
    this.name = "AssistantTimeoutError";
  }
}

export class AssistantNetworkError extends AssistantError {
  constructor(message: string = "Network failure. Please check your connection.") {
    super(message, 0, true);
    this.name = "AssistantNetworkError";
  }
}

// ============================================================================
// Chat Client API
// ============================================================================

export interface PostChatMessageOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  baseUrl?: string;
  token?: string | null;
}

export const DEFAULT_TIMEOUT_MS = 60_000;

export async function postChatMessage(
  message: string,
  history: ChatHistoryEntry[] = [],
  conversationId?: string,
  options: PostChatMessageOptions = {}
): Promise<AssistantChatResponse> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const baseUrl = (options.baseUrl ?? getBaseUrl()).replace(/\/+$/, "");
  const url = `${baseUrl}/api/v1/assistant/chat`;

  const controller = new AbortController();
  let timedOut = false;

  // Handle caller signal abort
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort(options.signal.reason);
    } else {
      options.signal.addEventListener(
        "abort",
        () => controller.abort(options.signal?.reason),
        { once: true }
      );
    }
  }

  // Setup timeout abort
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort(new Error("Assistant request timed out"));
  }, timeoutMs);

  const payload: AssistantChatRequest = {
    message,
    history,
  };
  if (conversationId) {
    payload.conversation_id = conversationId;
  }

  const token =
    options.token !== undefined
      ? options.token
      : getStoredTokens().accessToken;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (error: unknown) {
    clearTimeout(timeoutId);

    if (timedOut) {
      throw new AssistantTimeoutError(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    }

    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }

    throw new AssistantNetworkError(
      error instanceof Error ? error.message : "Network failure. Please check your connection."
    );
  } finally {
    clearTimeout(timeoutId);
  }

  // Parse error responses
  if (!response.ok) {
    let detailMessage = "";
    try {
      const errJson = (await response.json()) as { detail?: string | { msg?: string }[]; message?: string };
      if (typeof errJson.detail === "string") {
        detailMessage = errJson.detail;
      } else if (Array.isArray(errJson.detail)) {
        detailMessage = errJson.detail
          .map((item) => (typeof item === "object" && item?.msg ? item.msg : String(item)))
          .join(", ");
      } else if (typeof errJson.message === "string") {
        detailMessage = errJson.message;
      }
    } catch {
      try {
        detailMessage = await response.text();
      } catch {
        detailMessage = "";
      }
    }

    if (response.status === 401) {
      throw new AssistantAuthError(
        detailMessage || "Session expired. Please sign in again."
      );
    }

    if (response.status === 403) {
      throw new AssistantForbiddenError(
        detailMessage || "Your role cannot access the assistant."
      );
    }

    if (response.status === 429) {
      throw new AssistantServerError(
        detailMessage || "Too many requests. Please wait a moment and retry.",
        429
      );
    }

    if (response.status >= 500) {
      throw new AssistantServerError(
        detailMessage || `Assistant service error (${response.status}). Please try again.`,
        response.status
      );
    }

    throw new AssistantServerError(
      detailMessage || `Request failed with status ${response.status}`,
      response.status
    );
  }

  // Parse success response
  const rawData = (await response.json()) as Partial<AssistantChatResponse>;

  return {
    answer: typeof rawData.answer === "string" ? rawData.answer : "",
    conversation_id: rawData.conversation_id || conversationId || `conv-${Date.now()}`,
    tool_calls: Array.isArray(rawData.tool_calls) ? rawData.tool_calls : [],
    provenance: Array.isArray(rawData.provenance) ? rawData.provenance : [],
    insufficient_data: Boolean(rawData.insufficient_data),
    suggested_followups: Array.isArray(rawData.suggested_followups)
      ? rawData.suggested_followups
      : [],
  };
}

// ============================================================================
// Safe Markdown Renderer Helpers
// ============================================================================

/**
 * Escapes HTML characters to prevent XSS.
 */
export function escapeHtml(raw: string): string {
  if (!raw) return "";
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Validates and sanitizes link targets against dangerous schemes (javascript:, vbscript:, data:).
 */
export function sanitizeUrl(url: string): string {
  if (!url) return "#";
  const trimmed = url.trim();
  if (/^(https?:\/\/|\/|#|mailto:|tel:)/i.test(trimmed)) {
    return trimmed;
  }
  return "#";
}

/**
 * Converts a markdown string into safe, sanitized HTML.
 * All raw HTML is strictly escaped. Supports:
 * - Fenced code blocks ```lang
 * - Inline code `code`
 * - Headings #, ##, ###, ####
 * - Bold **text** / __text__
 * - Italic *text* / _text_
 * - Unordered lists (- or *)
 * - Ordered lists (1.)
 * - Links [label](url) with sanitized protocols
 * - Paragraphs with proper line breaks
 */
export function renderMarkdownToHtml(markdown: string): string {
  if (!markdown) return "";

  // Normalize line breaks
  const normalized = markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  // Step 1: Extract fenced code blocks with placeholders so inner code is escaped intact
  const codeBlocks: string[] = [];
  const withoutCodeBlocks = normalized.replace(
    /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g,
    (_match, lang, code) => {
      const escapedCode = escapeHtml(code.trimEnd());
      const langAttr = lang ? ` data-language="${escapeHtml(lang)}"` : "";
      const index = codeBlocks.length;
      codeBlocks.push(
        `<pre class="my-2.5 p-3 rounded-xl bg-black/50 border border-white/10 overflow-x-auto font-mono text-xs text-accent/90 shadow-inner"${langAttr}><code>${escapedCode}</code></pre>`
      );
      return `__CODE_BLOCK_${index}__`;
    }
  );

  const lines = withoutCodeBlocks.split("\n");
  const output: string[] = [];
  let inUl = false;
  let inOl = false;

  const closeList = () => {
    if (inUl) {
      output.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      output.push("</ol>");
      inOl = false;
    }
  };

  const processInline = (text: string): string => {
    // 1. Strict HTML escape first: all raw tags like <script> become inert entities
    let str = escapeHtml(text);

    // 2. Inline code: `code`
    str = str.replace(/`([^`]+)`/g, (_m, code) => {
      return `<code class="px-1.5 py-0.5 rounded bg-white/10 font-mono text-xs text-accent">${code}</code>`;
    });

    // 3. Bold: **text** or __text__
    str = str.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-text">$1</strong>');
    str = str.replace(/__([^_]+)__/g, '<strong class="font-semibold text-text">$1</strong>');

    // 4. Italic: *text* or _text_
    str = str.replace(/\*([^*]+)\*/g, '<em class="italic">$1</em>');
    str = str.replace(/_([^_]+)_/g, '<em class="italic">$1</em>');

    // 5. Links: [label](url)
    str = str.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, linkText, linkUrl) => {
      const safe = sanitizeUrl(linkUrl);
      return `<a href="${safe}" target="_blank" rel="noopener noreferrer" class="text-accent underline underline-offset-2 hover:text-accent/80 transition-colors font-medium">${linkText}</a>`;
    });

    return str;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Fenced code block placeholder check
    const codeMatch = trimmed.match(/^__CODE_BLOCK_(\d+)__$/);
    if (codeMatch) {
      closeList();
      const idx = parseInt(codeMatch[1], 10);
      output.push(codeBlocks[idx] || "");
      continue;
    }

    // Empty lines separate blocks and close open lists
    if (!trimmed) {
      closeList();
      continue;
    }

    // Headings
    if (trimmed.startsWith("#### ")) {
      closeList();
      output.push(
        `<h4 class="text-xs font-semibold font-display text-text uppercase tracking-wider mt-3 mb-1">${processInline(
          trimmed.slice(5)
        )}</h4>`
      );
      continue;
    }
    if (trimmed.startsWith("### ")) {
      closeList();
      output.push(
        `<h3 class="text-sm font-semibold font-display text-text mt-3 mb-1">${processInline(
          trimmed.slice(4)
        )}</h3>`
      );
      continue;
    }
    if (trimmed.startsWith("## ")) {
      closeList();
      output.push(
        `<h2 class="text-base font-semibold font-display text-text mt-3.5 mb-1.5">${processInline(
          trimmed.slice(3)
        )}</h2>`
      );
      continue;
    }
    if (trimmed.startsWith("# ")) {
      closeList();
      output.push(
        `<h1 class="text-lg font-bold font-display text-text mt-4 mb-2">${processInline(
          trimmed.slice(2)
        )}</h1>`
      );
      continue;
    }

    // Unordered list items: - or *
    const ulMatch = line.match(/^(\s*)[-*]\s+(.*)$/);
    if (ulMatch) {
      if (!inUl) {
        closeList();
        output.push('<ul class="list-disc list-inside space-y-1 my-1.5 text-text/90">');
        inUl = true;
      }
      output.push(`<li>${processInline(ulMatch[2])}</li>`);
      continue;
    }

    // Ordered list items: 1.
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      if (!inOl) {
        closeList();
        output.push('<ol class="list-decimal list-inside space-y-1 my-1.5 text-text/90">');
        inOl = true;
      }
      output.push(`<li>${processInline(olMatch[2])}</li>`);
      continue;
    }

    // Regular paragraph
    closeList();
    output.push(`<p class="leading-relaxed my-1.5 text-text/90">${processInline(line)}</p>`);
  }

  closeList();

  return output.join("\n");
}

export interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className = "",
}) => {
  const safeHtml = React.useMemo(() => renderMarkdownToHtml(content), [content]);

  return React.createElement("div", {
    className: `assistant-markdown text-sm leading-relaxed ${className}`,
    dangerouslySetInnerHTML: { __html: safeHtml },
  });
};

// ============================================================================
// LocalStorage Persistence Helpers
// ============================================================================

export function getConversationStorageKey(
  userId: string | number,
  conversationId: string
): string {
  return `ai_trafficos_assistant_${userId}_${conversationId}`;
}

export function getConversationIndexStorageKey(userId: string | number): string {
  return `ai_trafficos_assistant_${userId}_conversations`;
}

export function loadStoredConversationsIndex(
  userId: string | number
): ConversationSummary[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(getConversationIndexStorageKey(userId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function loadStoredMessages(
  userId: string | number,
  conversationId: string
): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(getConversationStorageKey(userId, conversationId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveStoredConversation(
  userId: string | number,
  session: ConversationSession
): void {
  if (typeof window === "undefined") return;
  try {
    // 1. Save messages for this specific conversation
    localStorage.setItem(
      getConversationStorageKey(userId, session.id),
      JSON.stringify(session.messages)
    );

    // 2. Update conversation index
    const index = loadStoredConversationsIndex(userId);
    const existingIdx = index.findIndex((c) => c.id === session.id);
    const summary: ConversationSummary = {
      id: session.id,
      title: session.title || "New Conversation",
      createdAt: session.createdAt,
      updatedAt: session.updatedAt,
      messageCount: session.messages.length,
    };

    let updatedIndex: ConversationSummary[];
    if (existingIdx >= 0) {
      updatedIndex = [...index];
      updatedIndex[existingIdx] = summary;
    } else {
      updatedIndex = [summary, ...index];
    }

    // Sort by updatedAt descending
    updatedIndex.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

    localStorage.setItem(
      getConversationIndexStorageKey(userId),
      JSON.stringify(updatedIndex.slice(0, 50)) // keep 50 most recent
    );
  } catch (error) {
    console.error("Failed to save assistant conversation to localStorage:", error);
  }
}

export function deleteStoredConversation(
  userId: string | number,
  conversationId: string
): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(getConversationStorageKey(userId, conversationId));
    const index = loadStoredConversationsIndex(userId);
    const updated = index.filter((c) => c.id !== conversationId);
    localStorage.setItem(getConversationIndexStorageKey(userId), JSON.stringify(updated));
  } catch (error) {
    console.error("Failed to delete assistant conversation:", error);
  }
}
