import { Link } from "react-router-dom";
import { SAMPLE_DATASETS, MOCK_USER, type MockDataset } from "./sample-data";

// "Editorial Workshop — lime/white revision".
// Same airy editorial layout (narrow sidebar, asymmetric main column,
// numbered articles, generous whitespace) but the palette is now
// white + greys + a bold lime accent. No cream paper, no serifs, no
// italics — modern product-tool look in the spirit of Linear/Vercel
// with the brand color doing the work.

export default function MockEditorial() {
  return (
    <div
      className="min-h-screen text-[14px] leading-relaxed"
      style={{
        // Surface scale
        ["--bg" as string]: "#ffffff",
        ["--surface" as string]: "#f7f7f8",
        ["--surface-2" as string]: "#eeeef0",
        ["--rule" as string]: "#e5e5e7",
        ["--rule-soft" as string]: "#efeff1",
        // Ink scale
        ["--ink" as string]: "#0a0a0a",
        ["--charcoal" as string]: "#1f1f22",
        ["--slate" as string]: "#3f3f46",
        ["--steel" as string]: "#6b7280",
        ["--stone" as string]: "#9ca3af",
        // Lime brand
        ["--lime" as string]: "#84cc16", // lime-500
        ["--lime-bright" as string]: "#a3e635", // lime-400 (highlighter)
        ["--lime-deep" as string]: "#4d7c0f", // lime-700 (readable text)
        ["--lime-soft" as string]: "rgba(132,204,22,0.14)",
        // States
        ["--danger" as string]: "#dc2626",
        ["--danger-soft" as string]: "rgba(220,38,38,0.1)",
        ["--warn" as string]: "#b45309",
        background: "var(--bg)",
        color: "var(--ink)",
        fontFamily:
          "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div className="flex min-h-screen">
        {/* Sidebar */}
        <aside
          className="w-[232px] flex flex-col px-6 py-7 border-r"
          style={{ borderColor: "var(--rule)", background: "var(--bg)" }}
        >
          <div className="mb-10 flex items-center gap-2.5">
            <span
              className="inline-block w-3 h-3 rounded-sm"
              style={{ background: "var(--lime)" }}
            />
            <div
              className="text-[20px] leading-[1] tracking-[-0.025em]"
              style={{ fontWeight: 700, color: "var(--ink)" }}
            >
              MimicRec
            </div>
          </div>

          <nav className="flex flex-col gap-1 mb-10">
            <NavLink active>Datasets</NavLink>
            <NavLink>Record</NavLink>
            <NavLink>Inference</NavLink>
            <NavLink>Settings</NavLink>
          </nav>

          <div
            className="text-[12px] mt-auto pt-4 border-t flex flex-col gap-1.5"
            style={{ borderColor: "var(--rule)", color: "var(--steel)" }}
          >
            <div
              className="text-[10px] tracking-[0.2em] uppercase"
              style={{ color: "var(--stone)", fontWeight: 500 }}
            >
              Operator
            </div>
            <div
              className="text-[14px]"
              style={{ color: "var(--ink)", fontWeight: 600 }}
            >
              {MOCK_USER}
            </div>
            <div className="flex items-center gap-1.5 mt-2 text-[11px]">
              <span
                className="w-2 h-2 rounded-full"
                style={{ background: "var(--lime)" }}
              />
              <span style={{ color: "var(--slate)" }}>Hub authenticated</span>
            </div>
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1">
          <div className="max-w-[1100px] mx-auto px-12 py-12">
            <div className="flex items-end justify-between gap-6 mb-10">
              <div>
                <div
                  className="inline-flex items-center gap-2 mb-3 text-[10px] tracking-[0.3em] uppercase"
                  style={{ color: "var(--lime-deep)", fontWeight: 600 }}
                >
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ background: "var(--lime)" }}
                  />
                  Datasets · 2026 Q2
                </div>
                <h1
                  className="text-[68px] leading-[0.96] tracking-[-0.035em]"
                  style={{ fontWeight: 700, color: "var(--ink)" }}
                >
                  The catalogue
                  <span style={{ color: "var(--lime)" }}>.</span>
                </h1>
              </div>
              <button
                className="text-[12px] tracking-[0.05em] px-5 py-3 self-end transition-colors"
                style={{
                  background: "var(--lime)",
                  color: "var(--ink)",
                  borderRadius: 999,
                  fontWeight: 600,
                }}
              >
                + New dataset
              </button>
            </div>

            <div className="h-px mb-6" style={{ background: "var(--rule)" }} />

            <div className="flex items-center justify-between text-[12px] mb-12">
              <div className="flex gap-8" style={{ color: "var(--steel)" }}>
                <Stat
                  count={SAMPLE_DATASETS.length}
                  label="datasets"
                />
                <Stat
                  count={SAMPLE_DATASETS.reduce((s, d) => s + d.episodes, 0)}
                  label="episodes"
                />
                <Stat
                  count={SAMPLE_DATASETS.reduce(
                    (s, d) => s + d.frames,
                    0,
                  ).toLocaleString()}
                  label="frames"
                />
              </div>
              <span style={{ color: "var(--steel)" }}>
                last updated · 2 min ago
              </span>
            </div>

            <div className="flex flex-col gap-12">
              {SAMPLE_DATASETS.map((d, i) => (
                <Article key={d.name} d={d} index={i + 1} />
              ))}
            </div>

            <footer
              className="mt-20 pt-6 border-t flex items-baseline justify-between text-[12px]"
              style={{ borderColor: "var(--rule)", color: "var(--steel)" }}
            >
              <span className="text-[10px] tracking-[0.3em] uppercase">
                end
              </span>
              <span>
                MimicRec · {new Date().toLocaleDateString()}
              </span>
            </footer>
          </div>
        </main>
      </div>

      <Link
        to="/mocks"
        className="fixed bottom-4 left-4 px-3 py-1.5 text-[11px] uppercase tracking-[0.3em]"
        style={{
          background: "var(--bg)",
          border: "1px solid var(--rule)",
          color: "var(--steel)",
          borderRadius: 999,
        }}
      >
        ← mocks
      </Link>
    </div>
  );
}

function Stat({ count, label }: { count: number | string; label: string }) {
  return (
    <span>
      <strong style={{ color: "var(--ink)", fontWeight: 700 }}>{count}</strong>{" "}
      {label}
    </span>
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
      className="group flex items-center gap-2.5 text-[14px] py-1.5 px-2 rounded-md transition-colors"
      style={{
        color: active ? "var(--ink)" : "var(--steel)",
        fontWeight: active ? 600 : 500,
        background: active ? "var(--lime-soft)" : "transparent",
      }}
    >
      <span
        className="w-1 h-4 rounded-sm transition-all"
        style={{
          background: active ? "var(--lime)" : "transparent",
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
          className="text-[44px] leading-none tracking-[-0.03em]"
          style={{
            fontWeight: 700,
            color: "var(--rule)",
          }}
        >
          {String(index).padStart(2, "0")}
        </span>
      </div>

      <div className="col-span-7 flex flex-col">
        <div
          className="inline-flex items-center gap-2 text-[10px] tracking-[0.3em] uppercase mb-2"
          style={{ color: "var(--lime-deep)", fontWeight: 600 }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: "var(--lime)" }}
          />
          {d.robot} · {d.cameras.join(" + ")}
        </div>
        <h2
          className="text-[32px] leading-[1.05] mb-2 tracking-[-0.02em]"
          style={{ fontWeight: 700, color: "var(--ink)" }}
        >
          {d.name}
        </h2>
        <p className="text-[15px] leading-[1.5]" style={{ color: "var(--steel)" }}>
          {d.taskHint}
        </p>

        <div className="flex items-center gap-2 mt-5 flex-wrap">
          <PrimaryBtn>Open episodes →</PrimaryBtn>
          <SecondaryBtn>Push to Hub</SecondaryBtn>
          <SecondaryBtn>Export</SecondaryBtn>
          <SecondaryBtn>Annotate</SecondaryBtn>
          <span className="grow" />
          <SecondaryBtn danger>Discard</SecondaryBtn>
        </div>
      </div>

      <div className="col-span-4 flex flex-col gap-3 text-[13px]">
        <Fact label="Episodes" value={d.episodes.toString()} />
        <Fact label="Frames" value={d.frames.toLocaleString()} />
        <Fact label="Duration" value={`${d.durationMin.toFixed(1)} min`} />
        <Fact
          label="Hugging Face"
          value={<HubLine state={d.hubState} repo={d.hubRepo} />}
        />
        <div
          className="text-[10px] tracking-[0.3em] uppercase pt-2"
          style={{ color: "var(--stone)", fontWeight: 500 }}
        >
          last touched · {d.lastTouched}
        </div>
      </div>
    </article>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      className="flex items-baseline justify-between gap-3 border-b pb-1.5"
      style={{ borderColor: "var(--rule-soft)" }}
    >
      <span
        className="text-[10px] tracking-[0.3em] uppercase"
        style={{ color: "var(--steel)", fontWeight: 600 }}
      >
        {label}
      </span>
      <span
        className="text-[15px] tracking-[-0.01em]"
        style={{ color: "var(--ink)", fontWeight: 600 }}
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
    synced: "var(--lime-deep)",
    stale: "var(--warn)",
    pushing: "var(--lime-deep)",
    "not-pushed": "var(--steel)",
    "not-configured": "var(--steel)",
    error: "var(--danger)",
  };
  const dots: Record<MockDataset["hubState"], string> = {
    synced: "var(--lime)",
    stale: "var(--warn)",
    pushing: "var(--lime)",
    "not-pushed": "var(--stone)",
    "not-configured": "var(--rule)",
    error: "var(--danger)",
  };
  return (
    <span
      style={{
        color: colors[state],
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: dots[state] }}
      />
      <span style={{ fontWeight: 600 }}>{labels[state]}</span>
      {repo && (
        <span
          className="text-[11px]"
          style={{
            fontFamily: "'Geist Mono', 'JetBrains Mono', ui-monospace, monospace",
            color: "var(--stone)",
            fontWeight: 400,
          }}
        >
          {repo}
        </span>
      )}
    </span>
  );
}

function PrimaryBtn({ children }: { children: React.ReactNode }) {
  return (
    <button
      className="px-5 py-2 text-[12px] tracking-[0.02em]"
      style={{
        background: "var(--lime)",
        color: "var(--ink)",
        borderRadius: 999,
        fontWeight: 600,
      }}
    >
      {children}
    </button>
  );
}

function SecondaryBtn({
  children,
  danger,
}: {
  children: React.ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      className="px-4 py-2 text-[12px] tracking-[0.02em] transition-colors"
      style={{
        background: danger ? "var(--danger-soft)" : "var(--surface)",
        color: danger ? "var(--danger)" : "var(--ink)",
        border: "1px solid " + (danger ? "var(--danger)" : "var(--rule)"),
        borderRadius: 999,
        fontWeight: 600,
      }}
    >
      {children}
    </button>
  );
}
