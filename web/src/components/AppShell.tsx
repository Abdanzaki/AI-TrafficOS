"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  Car,
  ChevronLeft,
  ChevronRight,
  FileText,
  LayoutDashboard,
  LogOut,
  Map as MapIcon,
  Menu,
  Radio,
  Route,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  TrendingUp,
  Users as UsersIcon,
  X,
  Bell,
  Cpu,
  Sparkles,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth, type UserRole } from "@/lib/auth";
import { useApiQuery } from "@/lib/use-api";
import { useTopic } from "@/lib/realtime";
import { Badge, type BadgeVariant } from "./ui/Badge";
import { Button } from "./ui/Button";
import { ConnectionStatus } from "./ConnectionStatus";

interface NavItem {
  name: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  requiredRoles?: UserRole[];
  writeAction?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Operations",
    items: [
      { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { name: "Traffic", href: "/traffic", icon: Car },
      { name: "Map", href: "/map", icon: MapIcon },
      { name: "Signals", href: "/signals", icon: Radio },
      { name: "Control", href: "/control", icon: SlidersHorizontal, writeAction: true },
    ],
  },
  {
    title: "Response & Routing",
    items: [
      { name: "Incidents", href: "/incidents", icon: AlertTriangle },
      { name: "Emergency", href: "/emergency", icon: Siren, writeAction: true },
      { name: "Routing", href: "/routing", icon: Route },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { name: "Predictions", href: "/predictions", icon: TrendingUp },
      { name: "Decisions", href: "/decisions", icon: BrainCircuit },
      { name: "Analytics", href: "/analytics", icon: BarChart3 },
      // Server is the authority for permissions; do not preemptively role-gate client navigation
      { name: "AI Assistant", href: "/assistant", icon: Sparkles },
    ],
  },
  {
    title: "System & Governance",
    items: [
      { name: "Notifications", href: "/notifications", icon: Bell },
      { name: "Audit Logs", href: "/audit-logs", icon: FileText, requiredRoles: ["admin"] },
      { name: "Health", href: "/health", icon: Activity },
      { name: "Users", href: "/users", icon: UsersIcon, requiredRoles: ["admin"] },
    ],
  },
];

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const pathname = usePathname();
  const { user, logout, isAdmin, isOfficer } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const queryClient = useQueryClient();

  useTopic("notification.created", () => {
    queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
  });

  const { data: unreadData } = useApiQuery<{ items: unknown[]; total: number }>({
    queryKey: ["notifications-unread-count"],
    endpoint: "/notifications/me",
    params: { is_read: false, per_page: 1 },
    queryOptions: {
      enabled: !!user,
      refetchInterval: 60000,
    },
  });

  const unreadCount = unreadData?.total ?? 0;

  const roleVariant: Record<UserRole, BadgeVariant> = {
    admin: "teal",
    traffic_officer: "amber",
    analyst: "muted",
  };

  const roleLabel: Record<UserRole, string> = {
    admin: "Admin",
    traffic_officer: "Officer",
    analyst: "Analyst",
  };

  const userRole = user?.role || "analyst";

  // Filter sections by roles
  const filteredSections = NAV_SECTIONS.map((sec) => ({
    ...sec,
    items: sec.items.filter((item) => {
      if (!item.requiredRoles) return true;
      return user && item.requiredRoles.includes(user.role);
    }),
  })).filter((sec) => sec.items.length > 0);

  return (
    <div className="min-h-screen bg-ink text-text flex">
      {/* Mobile Backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink/80 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* SIDEBAR */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex flex-col bg-surface/95 border-r border-white/10 transition-all duration-300 backdrop-blur-md lg:static ${
          mobileOpen ? "translate-x-0 w-64" : "-translate-x-full lg:translate-x-0"
        } ${sidebarCollapsed ? "lg:w-20" : "lg:w-64"}`}
      >
        {/* Brand Header */}
        <div className="h-16 flex items-center justify-between px-4 border-b border-white/10 shrink-0">
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-lg"
          >
            <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/40 flex items-center justify-center text-accent shrink-0 shadow-sm">
              <Cpu className="w-5 h-5" />
            </div>
            {(!sidebarCollapsed || mobileOpen) && (
              <div className="flex flex-col truncate">
                <span className="font-display font-bold text-base tracking-tight text-text leading-none">
                  AI TrafficOS
                </span>
                <span className="text-[10px] text-muted font-mono uppercase tracking-wider mt-0.5">
                  Command
                </span>
              </div>
            )}
          </Link>

          {/* Close on mobile */}
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="lg:hidden p-1.5 rounded-lg text-muted hover:text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Close sidebar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation list */}
        <nav
          className="flex-1 overflow-y-auto px-3 py-4 space-y-6"
          aria-label="Sidebar Navigation"
        >
          {filteredSections.map((section) => (
            <div key={section.title} className="space-y-1">
              {(!sidebarCollapsed || mobileOpen) && (
                <div className="px-3 pb-1 text-[11px] font-semibold text-muted uppercase tracking-wider">
                  {section.title}
                </div>
              )}
              {section.items.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMobileOpen(false)}
                    title={sidebarCollapsed && !mobileOpen ? item.name : undefined}
                    className={`group flex items-center gap-3 px-3 py-2 rounded-xl text-xs sm:text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                      isActive
                        ? "bg-accent/15 text-accent border border-accent/30 font-semibold shadow-sm"
                        : "text-muted hover:text-text hover:bg-surface/70 border border-transparent"
                    } ${sidebarCollapsed && !mobileOpen ? "justify-center px-0" : ""}`}
                  >
                    <Icon
                      className={`w-4 h-4 shrink-0 transition-transform ${
                        isActive ? "text-accent scale-110" : "text-muted group-hover:text-text"
                      }`}
                    />

                    {(!sidebarCollapsed || mobileOpen) && (
                      <div className="flex-1 flex items-center justify-between truncate">
                        <span className="truncate">{item.name}</span>
                        {item.writeAction && (
                          <span
                            className={`text-[9px] uppercase px-1.5 py-0.2 rounded font-mono border ${
                              isAdmin() || isOfficer()
                                ? "bg-amber/10 text-amber border-amber/20"
                                : "bg-muted/10 text-muted border-muted/20"
                            }`}
                            title={
                              isAdmin() || isOfficer()
                                ? "Write access active"
                                : "Read-only for analysts"
                            }
                          >
                            Write
                          </span>
                        )}
                      </div>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Sidebar Footer / Desktop Collapse Toggle */}
        <div className="p-3 border-t border-white/10 shrink-0 hidden lg:flex items-center justify-between">
          <button
            type="button"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-xs text-muted hover:text-text hover:bg-surface/70 transition-colors"
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <ChevronRight className="w-4 h-4" />
            ) : (
              <>
                <ChevronLeft className="w-4 h-4" />
                <span>Collapse menu</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* MAIN CONTENT WRAPPER */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* TOPBAR */}
        <header className="sticky top-0 z-30 h-16 bg-ink/80 backdrop-blur-md border-b border-white/10 flex items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            {/* Mobile menu trigger */}
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="lg:hidden p-2 rounded-lg text-muted hover:text-text hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label="Open sidebar"
            >
              <Menu className="w-5 h-5" />
            </button>

            {/* Breadcrumb / Section context */}
            <div className="hidden sm:flex items-center gap-2 text-xs">
              <span className="text-muted">AI TrafficOS</span>
              <span className="text-white/20">/</span>
              <span className="text-text font-medium capitalize">
                {pathname.replace(/^\//, "").split("/")[0] || "Dashboard"}
              </span>
            </div>
          </div>

          {/* Right items: Connection Status, Notification Bell, Environment Badge, User Details, Logout */}
          <div className="flex items-center gap-2.5 sm:gap-4">
            <ConnectionStatus />

            {/* Notification Bell with unread-count badge */}
            <Link
              href="/notifications"
              data-testid="desktop-notification-bell"
              className="relative p-2 rounded-lg text-muted hover:text-text hover:bg-surface transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
              title="Notifications"
            >
              <Bell className="w-5 h-5" />
              {unreadCount > 0 && (
                <span
                  data-testid="unread-notification-badge"
                  className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-accent text-[10px] font-bold text-ink ring-2 ring-ink"
                >
                  {unreadCount > 99 ? "99+" : unreadCount}
                </span>
              )}
            </Link>

            <Badge variant="teal" dot className="hidden md:inline-flex">
              FastAPI v1
            </Badge>

            <div className="h-4 w-px bg-white/10 hidden md:block" />

            {/* User Info & Role Badge */}
            {user && (
              <div className="flex items-center gap-2.5">
                <div className="text-right hidden sm:block">
                  <div className="text-xs font-semibold text-text leading-tight truncate max-w-[140px]">
                    {user.full_name || user.email}
                  </div>
                  <div className="text-[10px] text-muted truncate max-w-[140px]">
                    {user.email}
                  </div>
                </div>

                <Badge variant={roleVariant[userRole]} className="text-[10px]">
                  {roleLabel[userRole]}
                </Badge>
              </div>
            )}

            {/* Logout button */}
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={logout}
              title="Sign out of TrafficOS"
              className="text-muted hover:text-danger hover:bg-danger/10 p-2 sm:px-3 sm:py-1.5 focus-visible:ring-2 focus-visible:ring-danger"
            >
              <LogOut className="w-4 h-4 sm:mr-1.5" />
              <span className="hidden sm:inline">Sign out</span>
            </Button>
          </div>
        </header>

        {/* Page view container */}
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 sm:p-6 lg:p-8 overflow-y-auto focus:outline-none">
          {children}
        </main>
      </div>
    </div>
  );
};
