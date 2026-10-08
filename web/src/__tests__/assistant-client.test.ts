import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  postChatMessage,
  escapeHtml,
  sanitizeUrl,
  renderMarkdownToHtml,
  saveStoredConversation,
  loadStoredConversationsIndex,
  loadStoredMessages,
  deleteStoredConversation,
  AssistantAuthError,
  AssistantForbiddenError,
  AssistantServerError,
  AssistantTimeoutError,
  AssistantNetworkError,
  type ConversationSession,
} from "../lib/assistant";

describe("Assistant Client & Primitives (assistant-client.test.ts)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe("postChatMessage HTTP mappings", () => {
    it("maps 200 OK response correctly into AssistantChatResponse", async () => {
      const mockResponse = {
        answer: "Junction 4 is operating normally with 45 veh/min.",
        conversation_id: "conv-abc-123",
        tool_calls: [
          { tool: "get_junction_status", arguments: { id: 4 }, result_summary: "green" },
        ],
        provenance: [
          { segment: "45 veh/min", label: "observed" },
        ],
        insufficient_data: false,
        suggested_followups: ["Check Junction 5"],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      } as unknown as Response);

      const result = await postChatMessage("What is status of junction 4?", [], "conv-abc-123", {
        baseUrl: "http://api.traffic.local",
        token: "mock-token",
      });

      expect(result.answer).toBe(mockResponse.answer);
      expect(result.conversation_id).toBe("conv-abc-123");
      expect(result.tool_calls.length).toBe(1);
      expect(result.provenance[0].label).toBe("observed");
      expect(result.insufficient_data).toBe(false);
      expect(result.suggested_followups).toEqual(["Check Junction 5"]);
    });

    it("maps 401 Unauthorized to AssistantAuthError", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Token expired" }),
      } as unknown as Response);

      await expect(
        postChatMessage("Hello", [], undefined, { token: "expired", baseUrl: "http://api.local" })
      ).rejects.toThrow(AssistantAuthError);
    });

    it("maps 403 Forbidden to AssistantForbiddenError", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: async () => ({ detail: "Role analyst not permitted" }),
      } as unknown as Response);

      await expect(
        postChatMessage("Preempt signal 5", [], undefined, { token: "analyst-token", baseUrl: "http://api.local" })
      ).rejects.toThrow(AssistantForbiddenError);
    });

    it("maps 429 Rate Limit to AssistantServerError with retryable=true", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        json: async () => ({ detail: "Too Many Requests" }),
      } as unknown as Response);

      try {
        await postChatMessage("Query", [], undefined, { baseUrl: "http://api.local" });
        expect.fail("Expected error");
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(AssistantServerError);
        expect((err as AssistantServerError).status).toBe(429);
        expect((err as AssistantServerError).retryable).toBe(true);
      }
    });

    it("maps 500 / 503 Internal Server Error to AssistantServerError with retryable=true", async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Service Temporarily Unavailable" }),
      } as unknown as Response);

      try {
        await postChatMessage("Query", [], undefined, { baseUrl: "http://api.local" });
        expect.fail("Expected error");
      } catch (err: unknown) {
        expect(err).toBeInstanceOf(AssistantServerError);
        expect((err as AssistantServerError).status).toBe(503);
        expect((err as AssistantServerError).retryable).toBe(true);
      }
    });

    it("maps fetch network failure to AssistantNetworkError", async () => {
      global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

      await expect(
        postChatMessage("Query", [], undefined, { baseUrl: "http://api.local" })
      ).rejects.toThrow(AssistantNetworkError);
    });

    it("maps client timeout to AssistantTimeoutError", async () => {
      vi.useFakeTimers();

      global.fetch = vi.fn().mockImplementation((_url, opts) => {
        return new Promise((_resolve, reject) => {
          opts.signal.addEventListener("abort", () => {
            const err = new Error("Assistant request timed out");
            err.name = "AbortError";
            reject(err);
          });
        });
      });

      const promise = postChatMessage("Slow query", [], undefined, {
        baseUrl: "http://api.local",
        timeoutMs: 500,
      });

      // Advance timers past timeout
      vi.advanceTimersByTime(600);

      await expect(promise).rejects.toThrow(AssistantTimeoutError);
      vi.useRealTimers();
    });
  });

  describe("XSS Escaping & URL Sanitization", () => {
    it("escapes all HTML special characters preventing injection", () => {
      const malicious = '<script>alert("XSS")</script>&<img src="x" onerror="steal()"/>\'';
      const escaped = escapeHtml(malicious);

      expect(escaped).not.toContain("<script>");
      expect(escaped).toContain("&lt;script&gt;");
      expect(escaped).toContain("&quot;XSS&quot;");
      expect(escaped).toContain("&amp;");
      expect(escaped).toContain("&#39;");
    });

    it("sanitizeUrl permits https, http, relative paths and blocks javascript: schemes", () => {
      expect(sanitizeUrl("https://example.com/docs")).toBe("https://example.com/docs");
      expect(sanitizeUrl("http://localhost:8000")).toBe("http://localhost:8000");
      expect(sanitizeUrl("/dashboard")).toBe("/dashboard");

      // Dangerous schemes must be sanitized to '#'
      expect(sanitizeUrl("javascript:alert(1)")).toBe("#");
      expect(sanitizeUrl("JAVASCRIPT:alert(document.cookie)")).toBe("#");
      expect(sanitizeUrl("data:text/html,<script>alert(1)</script>")).toBe("#");
      expect(sanitizeUrl("vbscript:msgbox(1)")).toBe("#");
    });
  });

  describe("Markdown Rendering", () => {
    it("escapes raw HTML tags inside rendered markdown content", () => {
      const raw = 'Normal text with <script>evil()</script> and **bold** and `inline_code`.';
      const html = renderMarkdownToHtml(raw);

      expect(html).not.toContain("<script>evil()</script>");
      expect(html).toContain("&lt;script&gt;evil()&lt;/script&gt;");
      expect(html).toContain("<strong");
      expect(html).toContain("<code");
    });

    it("renders code blocks safely with escaped inner characters", () => {
      const raw = "```javascript\nconst x = 1 < 2 && 3 > 0;\n```";
      const html = renderMarkdownToHtml(raw);

      expect(html).toContain("<pre");
      expect(html).toContain("&lt; 2 &amp;&amp; 3 &gt; 0;");
    });
  });

  describe("LocalStorage Helpers", () => {
    it("saves and loads conversation messages and index", () => {
      const session: ConversationSession = {
        id: "conv-test-1",
        title: "Test Chat",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        messages: [
          {
            id: "m-1",
            role: "user",
            content: "Hello",
            timestamp: new Date().toISOString(),
          },
          {
            id: "m-2",
            role: "assistant",
            content: "Hi there!",
            timestamp: new Date().toISOString(),
          },
        ],
      };

      saveStoredConversation("user-42", session);

      // Check index
      const index = loadStoredConversationsIndex("user-42");
      expect(index.length).toBe(1);
      expect(index[0].id).toBe("conv-test-1");
      expect(index[0].title).toBe("Test Chat");

      // Check messages
      const msgs = loadStoredMessages("user-42", "conv-test-1");
      expect(msgs.length).toBe(2);
      expect(msgs[0].content).toBe("Hello");
      expect(msgs[1].content).toBe("Hi there!");

      // Delete conversation
      deleteStoredConversation("user-42", "conv-test-1");
      expect(loadStoredConversationsIndex("user-42").length).toBe(0);
      expect(loadStoredMessages("user-42", "conv-test-1").length).toBe(0);
    });
  });
});
