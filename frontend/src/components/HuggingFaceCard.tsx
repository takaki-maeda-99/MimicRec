import { useEffect, useState } from "react";
import {
  fetchAuthStatus,
  postLogin,
  postLogout,
  type AuthStatus,
} from "../api/cloud";

const AUTH_CHANGED_EVENT = "hf-auth-changed";

type Mode = "idle" | "saving" | "loggingOut";

function humanReadable(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong. Please try again.";
}

export function HuggingFaceCard() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchAuthStatus()
      .then((s) => alive && setAuth(s))
      .catch(() => alive && setAuth(null));
    return () => {
      alive = false;
    };
  }, []);

  // unmount guarantee: never leave the token in memory beyond this card's lifetime
  useEffect(() => () => setToken(""), []);

  const envLocked = auth?.env_locked ?? false;
  const authenticated = auth?.authenticated ?? false;

  const onSave = async () => {
    const t = token.trim();
    if (!t) {
      setError("Please paste a token.");
      return;
    }
    setMode("saving");
    setError(null);
    try {
      const next = await postLogin(t);
      setAuth(next);
      setToken("");
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
    } catch (e) {
      setError(humanReadable(e));
    } finally {
      setMode("idle");
    }
  };

  const onLogout = async () => {
    setMode("loggingOut");
    setError(null);
    try {
      await postLogout();
      setAuth({
        authenticated: false,
        username: null,
        env_locked: false,
        checked_at: new Date().toISOString(),
      });
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
    } catch (e) {
      setError(humanReadable(e));
    } finally {
      setMode("idle");
    }
  };

  return (
    <section className="rounded-md border border-hairline bg-surface-soft p-md flex flex-col gap-sm">
      <header className="flex items-baseline justify-between">
        <h2 className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
          Cloud / Hugging Face
        </h2>
        <span className="text-micro font-mono text-steel">
          {authenticated ? (
            <span className="text-brand-green-deep">
              ● connected as @{auth?.username ?? "—"}
              {envLocked && " (via HF_TOKEN env)"}
            </span>
          ) : envLocked ? (
            <span className="text-brand-warn">env-locked</span>
          ) : (
            <span>not signed in</span>
          )}
        </span>
      </header>

      {envLocked && (
        <p className="text-sm text-steel">
          A token is provided via the <code>HF_TOKEN</code> environment variable.
          Unset it (and restart the backend) to manage authentication from this UI.
        </p>
      )}

      {!envLocked && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-steel">Access token</span>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="hf_xxxxxxxxxxxxxxxxxxxx"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              disabled={mode !== "idle"}
              className="px-sm py-1 rounded border border-hairline bg-canvas font-mono text-sm"
            />
            <a
              href="https://huggingface.co/settings/tokens"
              target="_blank"
              rel="noreferrer noopener"
              className="text-micro text-brand-tag underline"
            >
              Get a token →
            </a>
          </label>

          {error && (
            <div className="text-sm text-brand-error" role="alert">
              {error}
            </div>
          )}

          <div className="flex items-center gap-sm">
            <button
              type="button"
              onClick={onSave}
              disabled={mode !== "idle" || !token.trim()}
              className="px-md py-1 rounded bg-brand-green text-on-primary disabled:opacity-50"
            >
              {mode === "saving" ? "Saving…" : "Save"}
            </button>
            {authenticated && (
              <button
                type="button"
                onClick={onLogout}
                disabled={mode !== "idle"}
                className="px-md py-1 rounded border border-hairline disabled:opacity-50"
              >
                {mode === "loggingOut" ? "Logging out…" : "Logout"}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
