import { apiFetch } from "./client";

export interface AuthStatus {
  authenticated: boolean;
  username: string | null;
  checked_at: string;
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
