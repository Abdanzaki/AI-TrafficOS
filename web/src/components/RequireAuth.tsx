"use client";

import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { LoadingSpinner } from "./ui/LoadingSpinner";

export interface RequireAuthProps {
  children: React.ReactNode;
}

export const RequireAuth: React.FC<RequireAuthProps> = ({ children }) => {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !user) {
      const returnUrl = encodeURIComponent(pathname || "/dashboard");
      router.replace(`/login?returnUrl=${returnUrl}`);
    }
  }, [isLoading, user, router, pathname]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-ink flex items-center justify-center p-6">
        <LoadingSpinner size="lg" label="Authenticating session..." />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-ink flex items-center justify-center p-6">
        <LoadingSpinner size="md" label="Redirecting to login..." />
      </div>
    );
  }

  return <>{children}</>;
};
