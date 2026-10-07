import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import {
  AuthProvider,
  useAuth,
  type User,
  type RegisterData,
  type AuthContextType,
} from "@/lib/auth";
import { RequireAuth } from "@/components/RequireAuth";
import { RequireRole } from "@/components/RequireRole";
import { api, setStoredTokens } from "@/lib/api-client";

// Mock next/navigation
const mockPush = vi.fn();
const mockReplace = vi.fn();
let currentPathname = "/traffic";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
  }),
  usePathname: () => currentPathname,
  useSearchParams: () => new URLSearchParams(),
}));

// Test helper component to consume useAuth
function AuthConsumer({
  onAuth,
}: {
  onAuth: (auth: AuthContextType) => void;
}) {
  const auth = useAuth();
  React.useEffect(() => {
    onAuth(auth);
  }, [auth, onAuth]);

  return (
    <div>
      <span data-testid="loading-status">{String(auth.isLoading)}</span>
      <span data-testid="user-email">{auth.user?.email || "none"}</span>
      <span data-testid="user-role">{auth.user?.role || "none"}</span>
    </div>
  );
}

describe("Auth System & Guards", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn();
    mockPush.mockClear();
    mockReplace.mockClear();
    currentPathname = "/traffic";
  });

  afterEach(() => {
    global.fetch = originalFetch;
    localStorage.clear();
  });

  describe("useAuth outside AuthProvider", () => {
    it("throws an error when useAuth is called without AuthProvider", () => {
      // Prevent React error boundary noise in console
      const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

      expect(() => {
        render(<AuthConsumer onAuth={() => {}} />);
      }).toThrow("useAuth must be used within an AuthProvider");

      consoleError.mockRestore();
    });
  });

  describe("AuthProvider Lifecycle", () => {
    it("initializes to unauthenticated state when no tokens in localStorage", async () => {
      const authRef = { current: null as AuthContextType | null };

      render(
        <AuthProvider>
          <AuthConsumer onAuth={(a) => { authRef.current = a; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("loading-status").textContent).toBe("false");
      });

      expect(authRef.current?.user).toBeNull();
      expect(authRef.current?.accessToken).toBeNull();
      expect(authRef.current?.isAdmin()).toBe(false);
      expect(authRef.current?.isOfficer()).toBe(false);
      expect(authRef.current?.isAnalyst()).toBe(false);
      expect(authRef.current?.canWrite()).toBe(false);
    });

    it("restores user profile from /auth/me when tokens exist in localStorage", async () => {
      setStoredTokens("valid-access-jwt", "valid-refresh-jwt");

      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 42,
        email: "officer.chen@trafficos.internal",
        full_name: "Officer Chen",
        role: "traffic_officer",
        is_active: true,
      });

      render(
        <AuthProvider>
          <AuthConsumer onAuth={() => {}} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("loading-status").textContent).toBe("false");
      });

      expect(screen.getByTestId("user-email").textContent).toBe(
        "officer.chen@trafficos.internal"
      );
      expect(screen.getByTestId("user-role").textContent).toBe("traffic_officer");
    });

    it("login authenticates credentials, persists tokens, and fetches profile", async () => {
      vi.spyOn(api, "post").mockResolvedValueOnce({
        access_token: "jwt-token-123",
        refresh_token: "refresh-token-456",
        token_type: "bearer",
      });

      vi.spyOn(api, "get").mockResolvedValue({
        id: 1,
        email: "admin@trafficos.internal",
        full_name: "System Admin",
        role: "admin",
        is_active: true,
      });

      const authRef = { current: null as AuthContextType | null };

      render(
        <AuthProvider>
          <AuthConsumer onAuth={(a) => { authRef.current = a; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("loading-status").textContent).toBe("false");
      });

      let loggedInUser: User | null = null;
      await act(async () => {
        loggedInUser = await authRef.current!.login(
          "admin@trafficos.internal",
          "password123"
        );
      });

      expect(loggedInUser).toEqual({
        id: 1,
        email: "admin@trafficos.internal",
        full_name: "System Admin",
        role: "admin",
        role_name: "admin",
        is_active: true,
        created_at: undefined,
      });

      expect(authRef.current?.isAdmin()).toBe(true);
      expect(authRef.current?.canWrite()).toBe(true);
      expect(authRef.current?.isOfficer()).toBe(false);
    });

    it("register creates analyst account and automatically logs in", async () => {
      vi.spyOn(api, "post")
        .mockResolvedValueOnce({
          id: 5,
          email: "analyst@trafficos.internal",
          full_name: "Data Analyst",
          role_name: "analyst",
          is_active: true,
        })
        .mockResolvedValueOnce({
          access_token: "jwt-analyst",
          refresh_token: "ref-analyst",
          token_type: "bearer",
        });

      vi.spyOn(api, "get").mockResolvedValue({
        id: 5,
        email: "analyst@trafficos.internal",
        full_name: "Data Analyst",
        role: "analyst",
        is_active: true,
      });

      const authRef = { current: null as AuthContextType | null };

      render(
        <AuthProvider>
          <AuthConsumer onAuth={(a) => { authRef.current = a; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("loading-status").textContent).toBe("false");
      });

      const registerPayload: RegisterData = {
        email: "analyst@trafficos.internal",
        password: "securepassword",
        full_name: "Data Analyst",
      };

      await act(async () => {
        await authRef.current!.register(registerPayload);
      });

      expect(authRef.current?.user?.email).toBe("analyst@trafficos.internal");
      expect(authRef.current?.isAnalyst()).toBe(true);
      expect(authRef.current?.canWrite()).toBe(false);
      expect(authRef.current?.isAdmin()).toBe(false);
    });

    it("logout clears storage and state", async () => {
      setStoredTokens("tok1", "tok2");
      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 1,
        email: "officer@trafficos.internal",
        role: "traffic_officer",
        is_active: true,
      });

      const authRef = { current: null as AuthContextType | null };

      render(
        <AuthProvider>
          <AuthConsumer onAuth={(a) => { authRef.current = a; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("loading-status").textContent).toBe("false");
      });

      act(() => {
        authRef.current!.logout();
      });

      expect(authRef.current?.user).toBeNull();
      expect(authRef.current?.accessToken).toBeNull();
    });
  });

  describe("RequireAuth Guard Component", () => {
    it("redirects unauthenticated users to /login with returnUrl", async () => {
      currentPathname = "/control";

      render(
        <AuthProvider>
          <RequireAuth>
            <div data-testid="protected-content">Secret Signals Area</div>
          </RequireAuth>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith("/login?returnUrl=%2Fcontrol");
      });

      expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
    });

    it("renders children when user is authenticated", async () => {
      setStoredTokens("valid-token", "valid-refresh");
      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 2,
        email: "admin@trafficos.internal",
        role: "admin",
        is_active: true,
      });

      render(
        <AuthProvider>
          <RequireAuth>
            <div data-testid="protected-content">Secret Signals Area</div>
          </RequireAuth>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("protected-content")).toBeInTheDocument();
      });

      expect(mockReplace).not.toHaveBeenCalled();
    });
  });

  describe("RequireRole Guard Component", () => {
    it("renders children when user possesses required role", async () => {
      setStoredTokens("valid-token", "valid-refresh");
      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 3,
        email: "officer@trafficos.internal",
        role: "traffic_officer",
        is_active: true,
      });

      render(
        <AuthProvider>
          <RequireRole allowedRoles={["admin", "traffic_officer"]}>
            <div data-testid="officer-content">Actuate Signal Controller</div>
          </RequireRole>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("officer-content")).toBeInTheDocument();
      });
    });

    it("displays Access Restricted when user role is not permitted", async () => {
      setStoredTokens("valid-token", "valid-refresh");
      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 4,
        email: "analyst@trafficos.internal",
        role: "analyst",
        is_active: true,
      });

      render(
        <AuthProvider>
          <RequireRole allowedRoles={["admin"]}>
            <div data-testid="admin-content">User Management</div>
          </RequireRole>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByText("Access Restricted")).toBeInTheDocument();
      });

      expect(screen.getByText("HTTP 403 Forbidden")).toBeInTheDocument();
      expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
    });

    it("renders custom fallback node when provided and access is denied", async () => {
      setStoredTokens("valid-token", "valid-refresh");
      vi.spyOn(api, "get").mockResolvedValueOnce({
        id: 4,
        email: "analyst@trafficos.internal",
        role: "analyst",
        is_active: true,
      });

      render(
        <AuthProvider>
          <RequireRole
            allowedRoles={["admin"]}
            fallback={<div data-testid="custom-fallback">Read-Only View</div>}
          >
            <div data-testid="admin-content">Admin Surface</div>
          </RequireRole>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("custom-fallback")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("admin-content")).not.toBeInTheDocument();
      expect(screen.queryByText("Access Restricted")).not.toBeInTheDocument();
    });
  });
});
