"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AUTH_CHANGED_EVENT,
  api,
  clearStoredTokens,
  getStoredTokens,
  setStoredTokens,
} from "./api-client";

export type UserRole = "admin" | "traffic_officer" | "analyst";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  role_name?: string;
  is_active: boolean;
  created_at?: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
}

export interface RegisterData {
  email: string;
  password: string;
  full_name: string;
}

export interface AuthContextType {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (data: RegisterData) => Promise<User>;
  logout: () => void;
  refreshUser: () => Promise<User | null>;
  isAdmin: () => boolean;
  isOfficer: () => boolean;
  isAnalyst: () => boolean;
  canWrite: () => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function normalizeUser(raw: Record<string, unknown>): User {
  const roleValue = (raw.role_name || raw.role || "analyst") as string;
  let normalizedRole: UserRole = "analyst";
  if (roleValue === "admin") {
    normalizedRole = "admin";
  } else if (roleValue === "traffic_officer") {
    normalizedRole = "traffic_officer";
  }

  return {
    id: Number(raw.id),
    email: String(raw.email),
    full_name: String(raw.full_name || ""),
    role: normalizedRole,
    role_name: roleValue,
    is_active: Boolean(raw.is_active),
    created_at: raw.created_at ? String(raw.created_at) : undefined,
  };
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const fetchUserProfile = useCallback(async (): Promise<User | null> => {
    try {
      const data = await api.get<Record<string, unknown>>("/auth/me");
      const normalized = normalizeUser(data);
      setUser(normalized);
      return normalized;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  const userRef = React.useRef<User | null>(user);
  useEffect(() => {
    userRef.current = user;
  }, [user]);

  // Initialize auth state from stored tokens
  useEffect(() => {
    let isMounted = true;

    async function initAuth() {
      const tokens = getStoredTokens();
      if (tokens.accessToken && tokens.refreshToken) {
        setAccessToken(tokens.accessToken);
        setRefreshToken(tokens.refreshToken);
        try {
          const profile = await fetchUserProfile();
          if (!profile && isMounted) {
            clearStoredTokens();
            setAccessToken(null);
            setRefreshToken(null);
            setUser(null);
          }
        } catch {
          if (isMounted) {
            clearStoredTokens();
            setAccessToken(null);
            setRefreshToken(null);
            setUser(null);
          }
        }
      } else {
        clearStoredTokens();
      }

      if (isMounted) {
        setIsLoading(false);
      }
    }

    initAuth();

    // Listen for cross-tab or api-client token mutations
    const handleAuthChange = (event: Event) => {
      const customEvent = event as CustomEvent<{
        accessToken: string | null;
        refreshToken: string | null;
      }>;
      const detail = customEvent.detail;
      if (detail) {
        setAccessToken(detail.accessToken);
        setRefreshToken(detail.refreshToken);
        if (!detail.accessToken) {
          setUser(null);
        } else if (!userRef.current) {
          fetchUserProfile();
        }
      }
    };

    window.addEventListener(AUTH_CHANGED_EVENT, handleAuthChange);

    return () => {
      isMounted = false;
      window.removeEventListener(AUTH_CHANGED_EVENT, handleAuthChange);
    };
  }, [fetchUserProfile]);

  const login = useCallback(
    async (email: string, password: string): Promise<User> => {
      setIsLoading(true);
      try {
        const tokenRes = await api.post<TokenResponse>(
          "/auth/login",
          { email, password },
          { skipAuth: true }
        );

        setStoredTokens(tokenRes.access_token, tokenRes.refresh_token);
        setAccessToken(tokenRes.access_token);
        setRefreshToken(tokenRes.refresh_token);

        // Fetch user profile immediately
        const userRes = await api.get<Record<string, unknown>>("/auth/me", undefined, {
          headers: {
            Authorization: `Bearer ${tokenRes.access_token}`,
          },
        });

        const normalized = normalizeUser(userRes);
        setUser(normalized);
        return normalized;
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const register = useCallback(
    async (data: RegisterData): Promise<User> => {
      setIsLoading(true);
      try {
        await api.post<Record<string, unknown>>("/auth/register", data, {
          skipAuth: true,
        });
        // Automatically authenticate upon successful registration
        return await login(data.email, data.password);
      } finally {
        setIsLoading(false);
      }
    },
    [login]
  );

  const logout = useCallback(() => {
    clearStoredTokens();
    setAccessToken(null);
    setRefreshToken(null);
    setUser(null);
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  const refreshUser = useCallback(async (): Promise<User | null> => {
    return await fetchUserProfile();
  }, [fetchUserProfile]);

  const isAdmin = useCallback((): boolean => {
    return user?.role === "admin";
  }, [user]);

  const isOfficer = useCallback((): boolean => {
    return user?.role === "traffic_officer";
  }, [user]);

  const isAnalyst = useCallback((): boolean => {
    return user?.role === "analyst";
  }, [user]);

  const canWrite = useCallback((): boolean => {
    return user?.role === "admin" || user?.role === "traffic_officer";
  }, [user]);

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      accessToken,
      refreshToken,
      isLoading,
      login,
      register,
      logout,
      refreshUser,
      isAdmin,
      isOfficer,
      isAnalyst,
      canWrite,
    }),
    [
      user,
      accessToken,
      refreshToken,
      isLoading,
      login,
      register,
      logout,
      refreshUser,
      isAdmin,
      isOfficer,
      isAnalyst,
      canWrite,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
