const BASE = ""; // relative — Vite proxy handles routing

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  opts?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...opts?.headers },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    let detail: string;
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // FastAPI 422: detail is a list of {loc, msg, type} objects.
      detail = body.detail
        .map((e: { loc?: unknown[]; msg?: string }) =>
          e.msg ? `${(e.loc ?? []).join(".")}: ${e.msg}` : JSON.stringify(e))
        .join("; ");
    } else {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}
