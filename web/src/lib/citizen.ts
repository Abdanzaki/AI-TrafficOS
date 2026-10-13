/**
 * AI TrafficOS - Citizen Assistant Client & Primitives (Batch 3 Brief C)
 *
 * Dedicated client for public citizen traffic assistant interaction:
 * Endpoint: POST {API_BASE}/api/v1/citizen/chat
 * Auth: Optional/Bearer token with 'citizen' or 'admin' role
 * Response: answer, provenance, tools_used, refused flag
 */

import { getBaseUrl, getStoredTokens } from "./api-client";

export interface CitizenChatRequest {
  message: string;
  junction_id?: number | null;
}

export interface CitizenChatResponse {
  answer: string;
  provenance: string;
  tools_used: string[];
  refused: boolean;
  confidence: "high" | "medium" | "low";
}

export interface CitizenChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  provenance?: string;
  toolsUsed?: string[];
  refused?: boolean;
  confidence?: "high" | "medium" | "low";
  isError?: boolean;
  errorMessage?: string;
}

export class CitizenAuthError extends Error {
  constructor(message = "Citizen authentication required.") {
    super(message);
    this.name = "CitizenAuthError";
  }
}

export class CitizenForbiddenError extends Error {
  constructor(message = "Access to citizen assistant is forbidden for this account.") {
    super(message);
    this.name = "CitizenForbiddenError";
  }
}

export class CitizenServerError extends Error {
  constructor(
    public readonly statusCode: number,
    message = "Public traffic service encountered an error."
  ) {
    super(message);
    this.name = "CitizenServerError";
  }
}

export class CitizenNetworkError extends Error {
  constructor(message = "Unable to connect to municipal traffic server.") {
    super(message);
    this.name = "CitizenNetworkError";
  }
}

export class CitizenTimeoutError extends Error {
  constructor(message = "Public traffic request timed out.") {
    super(message);
    this.name = "CitizenTimeoutError";
  }
}

export interface PostCitizenChatOptions {
  token?: string | null;
  timeoutMs?: number;
  baseUrl?: string;
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 20000;

export async function postCitizenChatMessage(
  message: string,
  junctionId?: number | null,
  options: PostCitizenChatOptions = {}
): Promise<CitizenChatResponse> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const baseUrl = (options.baseUrl ?? getBaseUrl()).replace(/\/+$/, "");
  const url = `${baseUrl}/api/v1/citizen/chat`;

  const controller = new AbortController();
  let timedOut = false;

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

  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort(new Error("Citizen request timed out"));
  }, timeoutMs);

  const payload: CitizenChatRequest = {
    message,
  };
  if (junctionId !== undefined && junctionId !== null) {
    payload.junction_id = junctionId;
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
      throw new CitizenTimeoutError();
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw error;
    }
    throw new CitizenNetworkError();
  } finally {
    clearTimeout(timeoutId);
  }

  if (response.status === 401) {
    throw new CitizenAuthError();
  }
  if (response.status === 403) {
    throw new CitizenForbiddenError();
  }
  if (response.status >= 500) {
    throw new CitizenServerError(response.status);
  }
  if (!response.ok) {
    let detailMsg = `Request failed with HTTP ${response.status}`;
    try {
      const errData = await response.json();
      if (errData?.detail) detailMsg = errData.detail;
    } catch {
      // Ignore json parse error
    }
    throw new CitizenServerError(response.status, detailMsg);
  }

  const rawData = (await response.json()) as Partial<CitizenChatResponse>;

  return {
    answer: String(rawData.answer || "No response received."),
    provenance: String(rawData.provenance || "observed"),
    tools_used: Array.isArray(rawData.tools_used) ? rawData.tools_used : [],
    refused: Boolean(rawData.refused),
    confidence: (rawData.confidence as "high" | "medium" | "low") || "high",
  };
}
