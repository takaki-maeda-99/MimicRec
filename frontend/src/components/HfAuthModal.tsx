import { useEffect, useState } from "react";
import { postLogin, postLogout, type AuthStatus } from "../api/cloud";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

const AUTH_CHANGED_EVENT = "hf-auth-changed";

interface Props {
  auth: AuthStatus | null;
  onAuthChange: (next: AuthStatus) => void;
  onClose: () => void;
}

type Mode = "idle" | "saving" | "loggingOut";

function humanReadable(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong. Please try again.";
}

export function HfAuthModal({ auth, onAuthChange, onClose }: Props) {
  const [mode, setMode] = useState<Mode>("idle");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);

  // unmount guarantee: never leave the token in memory beyond this modal's lifetime
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
      onAuthChange(next);
      setToken("");
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
      onClose();
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
      onAuthChange({
        authenticated: false,
        username: null,
        env_locked: false,
        checked_at: new Date().toISOString(),
      });
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
      onClose();
    } catch (e) {
      setError(humanReadable(e));
    } finally {
      setMode("idle");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
      onClick={onClose}
    >
      <div
        className="w-[440px] max-w-full bg-canvas rounded-lg border border-hairline p-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-heading-5 text-ink mb-md">Hugging Face</h3>

        {envLocked ? (
          <div className="flex flex-col gap-md">
            <p className="text-body-sm text-charcoal">
              A token is provided via the <code>HF_TOKEN</code> environment
              variable. Unset it (and restart the backend) to manage
              authentication from this UI.
            </p>
            {authenticated && auth?.username && (
              <p className="text-body-sm text-steel">
                Currently signed in as{" "}
                <span className="font-mono text-brand-green-deep">
                  @{auth.username}
                </span>
              </p>
            )}
            <div className="mt-md flex justify-end">
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
            </div>
          </div>
        ) : authenticated ? (
          <div className="flex flex-col gap-md">
            <p className="text-body-sm text-charcoal">
              Signed in as{" "}
              <span className="font-mono text-brand-green-deep">
                @{auth?.username ?? "—"}
              </span>
            </p>
            {error && (
              <div className="text-body-sm text-brand-error" role="alert">
                {error}
              </div>
            )}
            <div className="mt-md flex justify-end gap-xs">
              <Button variant="secondary" onClick={onClose}>
                Close
              </Button>
              <Button onClick={onLogout} disabled={mode !== "idle"}>
                {mode === "loggingOut" ? "Logging out…" : "Logout"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-md">
            <label className="text-body-sm-medium text-charcoal">
              Access token
              <Input
                className="mt-1 font-mono"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="hf_xxxxxxxxxxxxxxxxxxxx"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onSave()}
                disabled={mode !== "idle"}
                autoFocus
              />
            </label>
            <a
              href="https://huggingface.co/settings/tokens"
              target="_blank"
              rel="noreferrer noopener"
              className="text-micro text-brand-tag underline"
            >
              Get a token at huggingface.co/settings/tokens →
            </a>
            {error && (
              <div className="text-body-sm text-brand-error" role="alert">
                {error}
              </div>
            )}
            <div className="mt-md flex justify-end gap-xs">
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={onSave}
                disabled={mode !== "idle" || !token.trim()}
              >
                {mode === "saving" ? "Saving…" : "Sign in"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
