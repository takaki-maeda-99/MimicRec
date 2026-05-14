import { useInferenceStore } from "../../state/inference-store";
import { useSessionStore } from "../../state/session-store";
import { Button } from "../ui/button";
import { Select } from "../ui/select";
import { Input } from "../ui/input";

interface Props {
  disabled: boolean;
}

export function SessionColumn({ disabled }: Props) {
  const s = useInferenceStore();
  const sessionDataset = useSessionStore((x) => x.dataset);
  const selected = s.configs.find((c) => c.name === s.selectedConfig);
  const selectedHasError = !!selected?.error;

  return (
    <aside className="w-[220px] flex-shrink-0 border-r border-hairline bg-canvas flex flex-col">
      <div className="px-md py-md flex-1 overflow-auto flex flex-col gap-md">
        <Section title="Session">
          <Field label="Config">
            {s.phase === "pre-start" ? (
              <Select
                value={s.selectedConfig}
                onChange={(e) => s.selectConfig(e.target.value)}
                disabled={disabled}
              >
                <option value="">— select —</option>
                {s.configs.map((c) => (
                  <option key={c.name} value={c.name} disabled={!!c.error}>
                    {c.title && c.title !== c.name ? `${c.name} — ${c.title}` : c.name}
                    {c.error ? " (load error)" : ""}
                  </option>
                ))}
              </Select>
            ) : (
              <Readonly>{s.selectedConfig || "—"}</Readonly>
            )}
            {selected?.description && (
              <div className={`text-xs mt-1 ${selectedHasError ? "text-brand-error" : "text-steel"}`}>
                {selected.description}
              </div>
            )}
          </Field>

          <Field label={s.phase === "recording" || s.phase === "review" ? "Instruction (locked)" : "Instruction"}>
            {s.phase === "pre-start" || s.phase === "ready" ? (
              <div className="flex gap-2">
                <Input
                  type="text"
                  value={s.instruction}
                  onChange={(e) => s.setInstruction(e.target.value)}
                  placeholder="pick up the bottle"
                  disabled={disabled}
                />
                {s.phase === "ready" && (
                  <Button variant="outline" size="sm" onClick={() => s.updateInstruction()}>
                    Update
                  </Button>
                )}
              </div>
            ) : (
              <Readonly>{s.lockedInstruction ?? s.instruction}</Readonly>
            )}
          </Field>

          <Field label="Dataset">
            <Readonly>
              <code className="text-ink">{sessionDataset ?? "—"}</code>
            </Readonly>
          </Field>

          {(s.phase === "recording" || s.phase === "review") && s.reviewEpisode && (
            <Field label="Episode">
              <Readonly>
                #{s.reviewEpisode.index} · {s.reviewEpisode.durationSec.toFixed(1)}s
              </Readonly>
            </Field>
          )}
        </Section>
      </div>

      {(s.phase === "ready" || s.phase === "recording") && (
        <div className="px-md pb-md border-t border-hairline-soft pt-md">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => s.stopSession()}
            disabled={s.phase === "recording"}
            title={s.phase === "recording" ? "Stop the episode first" : undefined}
          >
            Stop session
          </Button>
        </div>
      )}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">{title}</div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <div className="text-xs text-slate">{label}</div>
      {children}
    </label>
  );
}

function Readonly({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-sm bg-surface px-2 py-1 text-body-sm text-ink">
      {children}
    </div>
  );
}
