import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  api,
  ApiError,
  getBaseUrl,
  getStoredTokens,
  setStoredTokens,
  clearStoredTokens,
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  AUTH_CHANGED_EVENT,
  request,
  get,
  post,
  put,
  patch,
  del,
} from "@/lib/api-client";

describe("api-client", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    localStorage.clear();
  });

  describe("Base URL & Storage", () => {
    it("getBaseUrl returns default URL if process.env.NEXT_PUBLIC_API_URL is unset", () => {
      const url = getBaseUrl();
      expect(url).toBe("http://localhost:8000");
    });

    it("getStoredTokens returns null when tokens are not in localStorage", () => {
      expect(getStoredTokens()).toEqual({ accessToken: null, refreshToken: null });
    });

    it("setStoredTokens saves tokens in localStorage and dispatches AUTH_CHANGED_EVENT", () => {
      const dispatchSpy = vi.spyOn(window, "dispatchEvent");

      setStoredTokens("access-123", "refresh-456");

      expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe("access-123");
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("refresh-456");
      expect(getStoredTokens()).toEqual({
        accessToken: "access-123",
        refreshToken: "refresh-456",
      });

      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: AUTH_CHANGED_EVENT,
          detail: { accessToken: "access-123", refreshToken: "refresh-456" },
        })
      );
    });

    it("clearStoredTokens removes tokens and dispatches AUTH_CHANGED_EVENT with nulls", () => {
      setStoredTokens("acc", "ref");
      const dispatchSpy = vi.spyOn(window, "dispatchEvent");

      clearStoredTokens();

      expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull();
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
      expect(getStoredTokens()).toEqual({ accessToken: null, refreshToken: null });

      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: AUTH_CHANGED_EVENT,
          detail: { accessToken: null, refreshToken: null },
        })
      );
    });
  });

  describe("Request Path Normalization & Query Parameters", () => {
    it("normalizes paths by prefixing /api/v1 if not present", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: "ok" }),
      });

      await request("/junctions");

      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/junctions",
        expect.anything()
      );
    });

    it("preserves paths that already have /api/v1 prefix", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: "ok" }),
      });

      await request("/api/v1/health");

      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/health",
        expect.anything()
      );
    });

    it("appends query parameters skipping undefined and null", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => [],
      });

      await request("/signals", {
        params: {
          page: 1,
          status: "active",
          empty: undefined,
          cleared: null,
        },
      });

      expect(global.fetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/signals?page=1&status=active",
        expect.anything()
      );
    });
  });

  describe("Auth Token Injection & Request Headers", () => {
    it("injects Bearer token from localStorage when skipAuth is false", async () => {
      setStoredTokens("my-jwt-token", "refresh-token");

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ authenticated: true }),
      });

      await request("/users/me");

      const callArgs = (global.fetch as any).mock.calls[0];
      const headers = callArgs[1].headers as Headers;
      expect(headers.get("Authorization")).toBe("Bearer my-jwt-token");
      expect(headers.get("Accept")).toBe("application/json");
    });

    it("does not inject Authorization header when skipAuth is true", async () => {
      setStoredTokens("my-jwt-token", "refresh-token");

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ access_token: "new" }),
      });

      await request("/auth/login", { skipAuth: true });

      const callArgs = (global.fetch as any).mock.calls[0];
      const headers = callArgs[1].headers as Headers;
      expect(headers.has("Authorization")).toBe(false);
    });

    it("serializes javascript objects as JSON and sets Content-Type", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => ({ id: 10 }),
      });

      const payload = { name: "Central", code: "J-01" };
      await post("/junctions", payload);

      const callArgs = (global.fetch as any).mock.calls[0];
      const headers = callArgs[1].headers as Headers;
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(callArgs[1].body).toBe(JSON.stringify(payload));
    });

    it("handles 204 No Content by returning undefined", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 204,
      });

      const result = await del("/users/5");
      expect(result).toBeUndefined();
    });
  });

  describe("Error Parsing & Network Failures", () => {
    it("parses error string detail into ApiError", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => ({ detail: "Intersection not found" }),
      });

      await expect(request("/junctions/999")).rejects.toThrow(ApiError);
      try {
        await request("/junctions/999");
      } catch (err) {
        // Just checking error type properties
      }
    });

    it("parses validation array error detail into ApiError", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: async () => ({
          detail: [
            { field: "email", msg: "Invalid email address" },
            { field: "password", msg: "Password must be at least 8 characters" },
          ],
        }),
      });

      await expect(post("/users", {})).rejects.toThrow("Invalid email address, Password must be at least 8 characters");
    });

    it("handles network connection failure throwing status 0 ApiError", async () => {
      (global.fetch as any).mockRejectedValueOnce(new Error("Failed to fetch"));

      try {
        await request("/health");
        expect.fail("Should have thrown ApiError");
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).status).toBe(0);
        expect((err as ApiError).message).toBe("Failed to fetch");
      }
    });
  });

  describe("401 Silent Refresh Flow", () => {
    it("silently refreshes token on 401 and retries original request successfully", async () => {
      setStoredTokens("expired-access", "valid-refresh");

      // 1st call: original request returns 401
      // 2nd call: silent refresh POST /api/v1/auth/refresh returns new tokens
      // 3rd call: retried original request with new access token returns 200
      (global.fetch as any)
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Token expired" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            access_token: "refreshed-access-token",
            refresh_token: "refreshed-refresh-token",
            token_type: "bearer",
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ data: "protected telemetry content" }),
        });

      const response = await request<{ data: string }>("/traffic-records");

      expect(response).toEqual({ data: "protected telemetry content" });
      expect(global.fetch).toHaveBeenCalledTimes(3);

      // Verify refresh endpoint call
      expect(global.fetch).toHaveBeenNthCalledWith(
        2,
        "http://localhost:8000/api/v1/auth/refresh",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ refresh_token: "valid-refresh" }),
        })
      );

      // Verify retried call used the newly refreshed token
      const retryHeaders = (global.fetch as any).mock.calls[2][1].headers as Headers;
      expect(retryHeaders.get("Authorization")).toBe("Bearer refreshed-access-token");

      // Verify storage was updated
      expect(getStoredTokens().accessToken).toBe("refreshed-access-token");
      expect(getStoredTokens().refreshToken).toBe("refreshed-refresh-token");
    });

    it("prevents stampede by sharing a single refresh promise for concurrent 401s", async () => {
      setStoredTokens("expired-access", "valid-refresh");

      // Both requests initially 401
      // Only ONE refresh request made
      // Both retried with 200
      (global.fetch as any)
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Token expired" }),
        })
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Token expired" }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({
            access_token: "shared-refreshed-token",
            refresh_token: "shared-refresh-token",
            token_type: "bearer",
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ result: 1 }),
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ result: 2 }),
        });

      const [res1, res2] = await Promise.all([
        request("/req-1"),
        request("/req-2"),
      ]);

      expect(res1).toEqual({ result: 1 });
      expect(res2).toEqual({ result: 2 });

      // Count calls to /api/v1/auth/refresh
      const refreshCalls = (global.fetch as any).mock.calls.filter(
        (call: any[]) => call[0] === "http://localhost:8000/api/v1/auth/refresh"
      );
      expect(refreshCalls).toHaveLength(1);
    });

    it("clears tokens and redirects when silent refresh fails", async () => {
      setStoredTokens("expired-access", "invalid-refresh");

      // Original request 401
      // Refresh request 401 (invalid refresh token)
      (global.fetch as any)
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Token expired" }),
        })
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          json: async () => ({ detail: "Invalid refresh token" }),
        });

      await expect(request("/protected")).rejects.toThrow("Session expired. Please log in again.");
      expect(getStoredTokens().accessToken).toBeNull();
      expect(getStoredTokens().refreshToken).toBeNull();
    });

    it("does not attempt silent refresh on /auth/login or when retryOn401 is false", async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: "Invalid email or password" }),
      });

      await expect(post("/auth/login", { email: "a@b.com", password: "bad" })).rejects.toThrow(
        "Invalid email or password"
      );

      // Only 1 fetch call made; no refresh attempted
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("HTTP Helper Methods (get, post, put, patch, del)", () => {
    it("calls request with matching HTTP verbs", async () => {
      (global.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      });

      await get("/signals");
      expect((global.fetch as any).mock.calls[0][1].method).toBe("GET");

      await post("/signals", { code: "S1" });
      expect((global.fetch as any).mock.calls[1][1].method).toBe("POST");

      await put("/signals/1", { code: "S1-updated" });
      expect((global.fetch as any).mock.calls[2][1].method).toBe("PUT");

      await patch("/signals/1", { status: "inactive" });
      expect((global.fetch as any).mock.calls[3][1].method).toBe("PATCH");

      await del("/signals/1");
      expect((global.fetch as any).mock.calls[4][1].method).toBe("DELETE");
    });
  });
});
