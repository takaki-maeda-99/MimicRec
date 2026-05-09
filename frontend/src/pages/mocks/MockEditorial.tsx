import { Link } from "react-router-dom";
import { SAMPLE_DATASETS, MOCK_USER, type MockDataset } from "./sample-data";

// "Editorial Workshop — clean type" revision.
// Same airy editorial layout as the original B (narrow sidebar, big asymmetric
// main column, numbered article-style entries, generous whitespace) but with
// neutral sans-serif throughout. No serifs, no italics — hierarchy comes
// from size, weight, tracking and color instead.

export default function MockEditorial() {
  return (
    <div
      className="min-h-screen text-[14px] leading-relaxed"
      style={{
        ["--ed-bg" as string]: "#f7f1e6",
        ["--ed-paper" as string]: "#fcf8f0",
        ["--ed-ink" as string]: "#1d1a14",
        ["--ed-soft" as string]: "#5b5448",
        ["--ed-rule" as string]: "#d8cdb8",
        ["--ed-rule-soft" as string]: "#e8dfcb",
        // Fluorescent lime accent + soft tint
        ["--ed-accent" as string]: "#5a8516", // readable lime for text/borders
        ["--ed-accent-bright" as string]: "#c2e84f", // highlighter pop
        ["--ed-accent-soft" as string]: "rgba(194,232,79,0.32)",
        // Dedicated danger (kept terracotta)
        ["--ed-danger" as string]: "#a23a2c",
        ["--ed-danger-soft" as string]: "rgba(162,58,44,0.1)",
        ["--ed-pos" as string]: "#3a6b3c",
        background: "var(--ed-bg)",
        color: "var(--ed-ink)",
        fontFamily:
          "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div className="flex min-h-screen">
        {/* Slim sidebar */}
        <aside
          className="w-[180px] flex flex-col px-5 py-6 border-r"
          style={{ borderColor: "var(--ed-rule)" }}
        >
          <div className="mb-10">
            <div
              className="text-[34px] leading-[1] tracking-[-0.04em]"
              style={{ fontWeight: 700, color: "var(--ed-ink)" }}
            >
              MimicRec
            </div>
            <div
              className="mt-2 text-[10px] tracking-[0.4em] uppercase"
              style={{ color: "var(--ed-soft)" }}
            >
              v 0.42
            </div>
          </div>

          <nav className="flex flex-col gap-1 mb-10">
            <NavLink active>Datasets</NavLink>
            <NavLink>Record</NavLink>
            <NavLink>Inference</NavLink>
            <NavLink>Settings</NavLink>
          </nav>

          <div
            className="text-[11px] mt-auto pt-4 border-t flex flex-col gap-1"
            style={{ borderColor: "var(--ed-rule-soft)", color: "var(--ed-soft)" }}
          >
            <div className="text-[10px] tracking-[0.3em] uppercase">Operator</div>
            <div
              className="text-[14px]"
              style={{ color: "var(--ed-ink)", fontWeight: 500 }}
            >
              {MOCK_USER}
            </div>
            <div className="flex items-center gap-1.5 mt-2">
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: "var(--ed-pos)" }}
              />
              <span>Hub authenticated</span>
            </div>
          </div>
        </aside>

        {/* Main reading column */}
        <main className="flex-1">
          <div className="max-w-[1100px] mx-auto px-12 py-12">
            <div className="flex items-end justify-between gap-6 mb-10">
              <div>
                <div
                  className="text-[11px] tracking-[0.4em] uppercase mb-3"
                  style={{ color: "var(--ed-soft)" }}
                >
                  Issue 42 · Datasets
                </div>
                <h1
                  className="text-[72px] leading-[0.95] tracking-[-0.035em]"
                  style={{ fontWeight: 700, color: "var(--ed-ink)" }}
                >
                  The catalogue
                  <span style={{ color: "var(--ed-accent)" }}>.</span>
                </h1>
              </div>
              <button
                className="text-[12px] tracking-[0.18em] uppercase px-6 py-3 self-end"
                style={{
                  background: "var(--ed-ink)",
                  color: "var(--ed-paper)",
                  borderRadius: 999,
                  fontWeight: 500,
                }}
              >
                + new dataset
              </button>
            </div>

            <div className="h-px mb-6" style={{ background: "var(--ed-rule)" }} />

            <div className="flex items-center justify-between text-[12px] mb-12">
              <div className="flex gap-8" style={{ color: "var(--ed-soft)" }}>
                <span>
                  <strong style={{ color: "var(--ed-ink)" }}>{SAMPLE_DATASETS.length}</strong>{" "}
                  datasets
                </span>
                <span>
                  <strong style={{ color: "var(--ed-ink)" }}>
                    {SAMPLE_DATASETS.reduce((s, d) => s + d.episodes, 0)}
                  </strong>{" "}
                  episodes
                </span>
                <span>
                  <strong style={{ color: "var(--ed-ink)" }}>
                    {SAMPLE_DATASETS.reduce((s, d) => s + d.frames, 0).toLocaleString()}
                  </strong>{" "}
                  frames
                </span>
              </div>
              <span style={{ color: "var(--ed-soft)" }}>
                last updated · 2 minutes ago
              </span>
            </div>

            <div className="flex flex-col gap-12">
              {SAMPLE_DATASETS.map((d, i) => (
                <Article key={d.name} d={d} index={i + 1} />
              ))}
            </div>

            <footer
              className="mt-20 pt-6 border-t flex items-baseline justify-between"
              style={{ borderColor: "var(--ed-rule)", color: "var(--ed-soft)" }}
            >
              <span className="text-[11px] tracking-[0.3em] uppercase">end</span>
              <span className="text-[12px]">
                MimicRec — printed at {new Date().toLocaleDateString()}
              </span>
            </footer>
          </div>
        </main>
      </div>

      <Link
        to="/mocks"
        className="fixed bottom-4 left-4 px-3 py-1.5 text-[11px] uppercase tracking-[0.3em]"
        style={{
          background: "var(--ed-paper)",
          border: "1px solid var(--ed-rule)",
          color: "var(--ed-soft)",
          borderRadius: 999,
        }}
      >
        ← mocks
      </Link>
    </div>
  );
}

function NavLink({
  children,
  active,
}: {
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <a
      href="#"
      className="group flex items-center gap-2 text-[14px] py-1.5 transition-colors"
      style={{
        color: active ? "var(--ed-ink)" : "var(--ed-soft)",
        fontWeight: active ? 600 : 400,
      }}
    >
      <span
        className="w-3 h-px transition-all"
        style={{
          background: active ? "var(--ed-accent)" : "var(--ed-rule)",
        }}
      />
      {children}
    </a>
  );
}

function Article({ d, index }: { d: MockDataset; index: number }) {
  return (
    <article className="grid grid-cols-12 gap-8 group">
      <div className="col-span-1 flex flex-col items-end">
        <span
          className="text-[40px] leading-none tracking-[-0.02em]"
          style={{
            fontWeight: 600,
            color: "var(--ed-rule)",
          }}
        >
          {String(index).padStart(2, "0")}
        </span>
      </div>

      <div className="col-span-7 flex flex-col">
        <div
          className="inline-flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase mb-2"
          style={{ color: "var(--ed-accent)", fontWeight: 600 }}
        >
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: "var(--ed-accent-bright)" }}
          />
          {d.robot} · {d.cameras.join(" + ")}
        </div>
        <h2
          className="text-[34px] leading-[1.05] mb-2 tracking-[-0.02em]"
          style={{ fontWeight: 600, color: "var(--ed-ink)" }}
        >
          {d.name}
        </h2>
        <p
          className="text-[15px] leading-[1.5]"
          style={{ color: "var(--ed-soft)" }}
        >
          {d.taskHint}
        </p>

        <div className="flex items-center gap-2 mt-5 flex-wrap">
          <PrimaryLink>Open episodes →</PrimaryLink>
          <SecondaryLink>Push to Hub</SecondaryLink>
          <SecondaryLink>Export</SecondaryLink>
          <SecondaryLink>Annotate</SecondaryLink>
          <span className="grow" />
          <SecondaryLink danger>Discard</SecondaryLink>
        </div>
      </div>

      <div className="col-span-4 flex flex-col gap-3 text-[13px]">
        <Stat label="Episodes" value={d.episodes.toString()} />
        <Stat label="Frames" value={d.frames.toLocaleString()} />
        <Stat label="Duration" value={`${d.durationMin.toFixed(1)} min`} />
        <Stat
          label="Hugging Face"
          value={<HubLine state={d.hubState} repo={d.hubRepo} />}
        />
        <div
          className="text-[10px] tracking-[0.3em] uppercase pt-2"
          style={{ color: "var(--ed-soft)" }}
        >
          last touched · {d.lastTouched}
        </div>
      </div>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      className="flex items-baseline justify-between gap-3 border-b pb-1.5"
      style={{ borderColor: "var(--ed-rule-soft)" }}
    >
      <span
        className="text-[10px] tracking-[0.3em] uppercase"
        style={{ color: "var(--ed-soft)", fontWeight: 500 }}
      >
        {label}
      </span>
      <span
        className="text-[16px] tracking-[-0.01em]"
        style={{ color: "var(--ed-ink)", fontWeight: 600 }}
      >
        {value}
      </span>
    </div>
  );
}

function HubLine({
  state,
  repo,
}: {
  state: MockDataset["hubState"];
  repo?: string;
}) {
  const labels: Record<MockDataset["hubState"], string> = {
    synced: "Synced",
    stale: "Stale",
    pushing: "Pushing…",
    "not-pushed": "Pending",
    "not-configured": "Unconfigured",
    error: "Failed",
  };
  const colors: Record<MockDataset["hubState"], string> = {
    synced: "var(--ed-pos)",
    stale: "#9b6a18",
    pushing: "var(--ed-accent)",
    "not-pushed": "var(--ed-soft)",
    "not-configured": "var(--ed-soft)",
    error: "var(--ed-danger)",
  };
  return (
    <span
      style={{
        color: colors[state],
        display: "inline-flex",
        alignItems: "baseline",
        gap: 6,
      }}
    >
      <span style={{ fontWeight: 600 }}>{labels[state]}</span>
      {repo && (
        <span
          className="text-[11px]"
          style={{
            fontFamily: "'JetBrains Mono', ui-monospace, monospace",
            color: "var(--ed-soft)",
            fontWeight: 400,
          }}
        >
          {repo}
        </span>
      )}
    </span>
  );
}

function PrimaryLink({ children }: { children: React.ReactNode }) {
  return (
    <button
      className="px-5 py-2 text-[12px] tracking-[0.05em]"
      style={{
        background: "var(--ed-ink)",
        color: "var(--ed-paper)",
        borderRadius: 999,
        fontWeight: 500,
      }}
    >
      {children}
    </button>
  );
}

function SecondaryLink({
  children,
  danger,
}: {
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      className="px-4 py-2 text-[12px] tracking-[0.05em] transition-colors"
      style={{
        background: danger ? "var(--ed-danger-soft)" : "var(--ed-paper)",
        color: danger ? "var(--ed-danger)" : "var(--ed-ink)",
        border: "1px solid " + (danger ? "var(--ed-danger)" : "var(--ed-rule)"),
        borderRadius: 999,
        fontWeight: 500,
      }}
    >
      {children}
    </button>
  );
}
