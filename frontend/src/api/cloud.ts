import { apiFetch, ApiError } from "./client";

export interface AuthStatus {
  authenticated: boolean;
  username: string | null;
  checked_at: string;
  env_locked: boolean;
}

export interface HubConfig {
  repo_id: string;
  private: boolean;
  auto_push: boolean;
}

export interface HubState {
  last_pushed_at: string | null;
  last_pushed_commit_sha: string | null;
  last_pushed_manifest_hash: string | null;
  last_push_error: string | null;
}

export interface HubProgress {
  status: "idle" | "queued" | "uploading" | "done" | "error";
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
}

export interface HubResponse {
  config: HubConfig | null;
  state: HubState | null;
  progress: HubProgress;
}

export const fetchAuthStatus = (refresh = false) =>
  apiFetch<AuthStatus>(`/api/cloud/auth-status${refresh ? "?refresh=1" : ""}`);

export const fetchHub = (ds: string) =>
  apiFetch<HubResponse>(`/api/datasets/${encodeURIComponent(ds)}/hub`);

export const putHub = (ds: string, body: HubConfig) =>
  apiFetch<HubResponse>(`/api/datasets/${encodeURIComponent(ds)}/hub`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const postHubPush = (ds: string) =>
  apiFetch<{ status: string }>(`/api/datasets/${encodeURIComponent(ds)}/hub/push`, {
    method: "POST",
  });

export const postLogin = (token: string): Promise<AuthStatus> =>
  apiFetch<AuthStatus>("/api/cloud/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

export async function postLogout(): Promise<void> {
  // Logout returns 204 No Content. apiFetch unconditionally calls res.json()
  // on success (see frontend/src/api/client.ts: `return res.json()`), which
  // throws on an empty body — the same pitfall SettingsPage.handleDelete
  // already documents for DELETE 204s. Use raw fetch here.
  const res = await fetch("/api/cloud/logout", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
  });
  if (res.status === 204) return;
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = typeof body.detail === "string" ? body.detail : res.statusText;
  throw new ApiError(res.status, detail);
}
