"use client";

import React, { useState, useMemo } from "react";
import {
  Users as UsersIcon,
  Shield,
  Mail,
  Calendar,
  Check,
  X,
  UserPlus,
  Lock,
  User,
  AlertCircle,
  CheckCircle2,
  Power,
  ShieldAlert,
  Search,
  Filter,
} from "lucide-react";
import { RequireRole } from "@/components/RequireRole";
import { useApiQuery, useApiMutation } from "@/lib/use-api";
import { Card } from "@/components/ui/Card";
import { Badge, type BadgeVariant } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDateTime } from "@/lib/format";

interface UserItem {
  id: number;
  email: string;
  full_name: string;
  role_name: string;
  is_active: boolean;
  created_at: string;
}

interface PaginatedUsers {
  items: UserItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

interface CreateUserPayload {
  email: string;
  password: string;
  full_name: string;
  role_name: string;
}

interface UpdateUserPayload {
  full_name?: string;
  is_active?: boolean;
  role_name?: string;
}

function UsersContent() {
  const [page, setPage] = useState(1);
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Form states for creating a user
  const [formEmail, setFormEmail] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formFullName, setFormFullName] = useState("");
  const [formRole, setFormRole] = useState("analyst");
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  // Status/Role action in-flight state
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  // Fetch paginated user list
  const { data, isLoading, error, refetch } = useApiQuery<PaginatedUsers>({
    queryKey: ["users-list", page],
    endpoint: "/users",
    params: { page, per_page: 20 },
  });

  // Create User Mutation (POST /users)
  const createUserMutation = useApiMutation<UserItem, CreateUserPayload>({
    endpoint: "/users",
    method: "POST",
  });

  // Update User Mutation (PATCH /users/{id})
  const updateUserMutation = useApiMutation<UserItem, { id: number; data: UpdateUserPayload }>({
    endpoint: (vars) => `/users/${vars.id}`,
    method: "PATCH",
  });

  // Soft Delete Mutation (DELETE /users/{id})
  const deleteUserMutation = useApiMutation<UserItem, { id: number }>({
    endpoint: (vars) => `/users/${vars.id}`,
    method: "DELETE",
  });

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setFormSuccess(null);

    if (!formEmail.trim() || !formFullName.trim()) {
      setFormError("Please provide both name and email.");
      return;
    }

    if (formPassword.length < 8) {
      setFormError("Password must be at least 8 characters long.");
      return;
    }

    try {
      await createUserMutation.mutateAsync({
        email: formEmail.trim(),
        password: formPassword,
        full_name: formFullName.trim(),
        role_name: formRole,
      });

      setFormSuccess(`User ${formEmail} created successfully.`);
      refetch();
      setTimeout(() => {
        setShowCreateModal(false);
        setFormEmail("");
        setFormPassword("");
        setFormFullName("");
        setFormRole("analyst");
        setFormSuccess(null);
      }, 1200);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create user account";
      setFormError(msg);
    }
  };

  const handleRoleChange = async (userId: number, newRole: string) => {
    setActionLoadingId(userId);
    try {
      await updateUserMutation.mutateAsync({
        id: userId,
        data: { role_name: newRole },
      });
      refetch();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to change user role");
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleToggleActive = async (user: UserItem) => {
    setActionLoadingId(user.id);
    try {
      if (user.is_active) {
        // Soft-delete/deactivate via DELETE /users/{id}
        await deleteUserMutation.mutateAsync({ id: user.id });
      } else {
        // Reactivate via PATCH /users/{id}
        await updateUserMutation.mutateAsync({
          id: user.id,
          data: { is_active: true },
        });
      }
      refetch();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to update account active status");
    } finally {
      setActionLoadingId(null);
    }
  };

  const getRoleVariant = (role: string): BadgeVariant => {
    switch (role) {
      case "admin":
        return "teal";
      case "traffic_officer":
        return "amber";
      default:
        return "muted";
    }
  };

  // Filtered items (client-side query & role filtering on current page)
  const userItems = data?.items;
  const filteredUsers = useMemo(() => {
    if (!userItems) return [];
    return userItems.filter((item) => {
      const matchesRole = roleFilter === "all" || item.role_name === roleFilter;
      const query = searchQuery.toLowerCase().trim();
      const matchesQuery =
        !query ||
        item.email.toLowerCase().includes(query) ||
        item.full_name.toLowerCase().includes(query);
      return matchesRole && matchesQuery;
    });
  }, [userItems, roleFilter, searchQuery]);

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 rounded-2xl bg-surface/70 border border-white/10 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h1 className="text-2xl font-display font-bold text-text">
              User Management
            </h1>
            <Badge variant="teal">Admin Clearance</Badge>
          </div>
          <p className="text-xs sm:text-sm text-muted">
            Provision accounts, assign operational role privileges, and toggle active status per /api/v1/users.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="text-xs text-muted font-mono bg-ink/60 px-3 py-1.5 rounded-lg border border-white/10">
            Total Accounts: {data?.total ?? "..."}
          </div>

          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setFormError(null);
              setFormSuccess(null);
              setShowCreateModal(true);
            }}
          >
            <UserPlus className="w-4 h-4 mr-1.5" />
            Create Account
          </Button>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl bg-surface/40 border border-white/5">
        <div className="flex items-center gap-2 w-full sm:w-72 bg-ink/60 border border-white/10 rounded-xl px-3 py-1.5">
          <Search className="w-4 h-4 text-muted shrink-0" />
          <input
            type="text"
            placeholder="Search by name or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-transparent text-xs text-text placeholder:text-muted/60 focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-2 self-end sm:self-auto text-xs text-muted">
          <Filter className="w-3.5 h-3.5 text-accent" />
          <span>Role Filter:</span>
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="bg-ink/60 border border-white/10 rounded-lg px-2.5 py-1 text-xs text-text focus:outline-none"
          >
            <option value="all">All Roles</option>
            <option value="admin">Admin</option>
            <option value="traffic_officer">Traffic Officer</option>
            <option value="analyst">Analyst</option>
          </select>
        </div>
      </div>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/80 backdrop-blur-sm animate-in fade-in">
          <Card className="w-full max-w-md p-6 bg-surface/95 border-white/20 shadow-2xl relative">
            <button
              type="button"
              onClick={() => setShowCreateModal(false)}
              className="absolute top-4 right-4 p-1.5 rounded-lg text-muted hover:text-text hover:bg-white/5"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-2 mb-1">
              <UserPlus className="w-5 h-5 text-accent" />
              <h2 className="text-lg font-display font-bold text-text">
                Create User Account
              </h2>
            </div>
            <p className="text-xs text-muted mb-4">
              Provision a new account with explicit role assignment (POST /api/v1/users).
            </p>

            {formError && (
              <div className="mb-4 p-3 rounded-xl bg-danger/10 border border-danger/30 text-danger text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            {formSuccess && (
              <div className="mb-4 p-3 rounded-xl bg-success/10 border border-success/30 text-success text-xs flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <span>{formSuccess}</span>
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                  Full Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="Officer Jane Doe"
                  value={formFullName}
                  onChange={(e) => setFormFullName(e.target.value)}
                  className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                  Work Email Address
                </label>
                <input
                  type="email"
                  required
                  placeholder="jane.doe@trafficos.internal"
                  value={formEmail}
                  onChange={(e) => setFormEmail(e.target.value)}
                  className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                  Initial Password (min 8 chars)
                </label>
                <input
                  type="password"
                  required
                  minLength={8}
                  placeholder="••••••••••••"
                  value={formPassword}
                  onChange={(e) => setFormPassword(e.target.value)}
                  className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted uppercase tracking-wider mb-1">
                  Assigned Clearance Role
                </label>
                <select
                  value={formRole}
                  onChange={(e) => setFormRole(e.target.value)}
                  className="w-full px-3 py-2 bg-ink/70 border border-white/10 rounded-xl text-xs text-text focus:outline-none focus:border-accent"
                >
                  <option value="analyst">Analyst (Read-Only Telemetry)</option>
                  <option value="traffic_officer">Traffic Officer (Signals & Control)</option>
                  <option value="admin">Administrator (Full System Control)</option>
                </select>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={createUserMutation.isPending}
                >
                  {createUserMutation.isPending ? "Creating..." : "Create Account"}
                </Button>
              </div>
            </form>
          </Card>
        </div>
      )}

      {/* Main Table / State Render */}
      {isLoading ? (
        <div className="min-h-[40vh] flex items-center justify-center">
          <LoadingSpinner size="lg" label="Querying user directory..." />
        </div>
      ) : error ? (
        <ErrorState
          title="Failed to Load Users"
          message={error.message}
          onRetry={() => refetch()}
        />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          icon={<UsersIcon className="w-8 h-8 text-muted" />}
          title="No users found"
          description="There are currently no registered users in the database."
        />
      ) : (
        <Card className="overflow-hidden border-white/10">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs sm:text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-surface/60 text-muted uppercase text-[11px] font-semibold tracking-wider font-mono">
                  <th className="py-3 px-4">User</th>
                  <th className="py-3 px-4">Role Clearance</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Created</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filteredUsers.map((item) => (
                  <tr key={item.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-medium text-text">{item.full_name || "—"}</div>
                      <div className="text-xs text-muted font-mono flex items-center gap-1.5 mt-0.5">
                        <Mail className="w-3 h-3 text-muted/70" />
                        {item.email}
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <Badge variant={getRoleVariant(item.role_name)}>
                          {item.role_name.replace("_", " ")}
                        </Badge>

                        {/* Quick Role Change Selector */}
                        <select
                          value={item.role_name}
                          disabled={actionLoadingId === item.id}
                          onChange={(e) => handleRoleChange(item.id, e.target.value)}
                          className="bg-ink/50 border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-muted hover:text-text focus:outline-none cursor-pointer"
                          aria-label={`Change role for ${item.email}`}
                        >
                          <option value="analyst">analyst</option>
                          <option value="traffic_officer">traffic_officer</option>
                          <option value="admin">admin</option>
                        </select>
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      <span className="inline-flex items-center gap-1.5 text-xs font-mono">
                        {item.is_active ? (
                          <>
                            <span className="w-2 h-2 rounded-full bg-success" />
                            <span className="text-success font-medium">Active</span>
                          </>
                        ) : (
                          <>
                            <span className="w-2 h-2 rounded-full bg-danger" />
                            <span className="text-danger font-medium">Disabled</span>
                          </>
                        )}
                      </span>
                    </td>

                    <td className="py-3 px-4 text-xs text-muted font-mono">
                      {formatDateTime(item.created_at)}
                    </td>

                    <td className="py-3 px-4 text-right">
                      <Button
                        type="button"
                        variant={item.is_active ? "ghost" : "secondary"}
                        size="sm"
                        disabled={actionLoadingId === item.id}
                        onClick={() => handleToggleActive(item)}
                        className={`text-xs ${
                          item.is_active
                            ? "text-muted hover:text-danger hover:bg-danger/10"
                            : "text-success hover:bg-success/10"
                        }`}
                        title={item.is_active ? "Deactivate Account" : "Reactivate Account"}
                      >
                        <Power className="w-3.5 h-3.5 mr-1" />
                        {item.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.pages > 1 && (
            <div className="p-4 border-t border-white/10 flex items-center justify-between text-xs text-muted">
              <span>
                Page {data.page} of {data.pages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="px-3 py-1 rounded bg-surface border border-white/10 disabled:opacity-40 hover:text-text cursor-pointer disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={page >= data.pages}
                  onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
                  className="px-3 py-1 rounded bg-surface border border-white/10 disabled:opacity-40 hover:text-text cursor-pointer disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

export default function UsersPage() {
  return (
    <RequireRole allowedRoles={["admin"]}>
      <UsersContent />
    </RequireRole>
  );
}
