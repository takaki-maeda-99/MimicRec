import { Link } from "react-router-dom";
import { SAMPLE_DATASETS, MOCK_USER, type MockDataset } from "./sample-data";

// "Lab Notebook" — research notebook aesthetic.
// Off-white paper, hairline grid, numbered sections, mono numerals,
// serif headings, corner ticks. Dense but unfailingly legible — the
// way a scientist's bench journal looks: lots of data, no noise.

export default function MockNotebook() {
  return (
    <div
      className="min-h-screen text-[13px] leading-relaxed"
      style={{
        ["--nb-bg" as string]: "#f3eee2",
        ["--nb-paper" as string]: "#fbf6e9",
        ["--nb-ink" as string]: "#1a1d18",
        ["--nb-soft" as string]: "#5d6056",
        ["--nb-rule" as string]: "#c9c2ac",
        ["--nb-rule-soft" as string]: "#ddd5bd",
        ["--nb-accent" as string]: "#274936",
        ["--nb-accent-soft" as string]: "#e1ead0",
        ["--nb-mark" as string]: "#c87a2a",
        ["--nb-mark-soft" as string]: "#f4e6cf",
        ["--nb-stop" as string]: "#a0392b",
        background: "var(--nb-bg)",
        color: "var(--nb-ink)",
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        backgroundImage:
          "linear-gradient(to right, transparent 31px, var(--nb-rule-soft) 31px, var(--nb-rule-soft) 32px, transparent 32px), linear-gradient(to bottom, transparent 23px, var(--nb-rule-soft) 23px, var(--nb-rule-soft) 24px, transparent 24px)",
        backgroundSize: "32px 24px",
      }}
    >
      <div className="flex min-h-screen">
        <aside
          className="w-[230px] flex flex-col border-r"
          style={{
            borderColor: "var(--nb-rule)",
            background: "var(--nb-paper)",
          }}
        >
          <div
            className="px-5 py-5 border-b"
            style={{ borderColor: "var(--nb-rule)" }}
          >
            <div
              className="text-[10px] tracking-[0.4em] uppercase mb-1"
              style={{ color: "var(--nb-soft)" }}
            >
              Lab Notebook
            </div>
            <h1
              className="text-[28px] leading-[1]"
              style={{
                fontFamily: "Fraunces, serif",
                fontWeight: 420,
                fontVariationSettings: "'opsz' 96",
                letterSpacing: "-0.01em",
              }}
            >
              MimicRec
              <span
                style={{
                  fontFamily: "'Instrument Serif', Fraunces, serif",
                  fontStyle: "italic",
                  fontWeight: 400,
                  color: "var(--nb-mark)",
                }}
              >
                /042
              </span>
            </h1>
            <div
              className="text-[10px] mt-2"
              style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                color: "var(--nb-soft)",
              }}
            >
              {new Date().toISOString().slice(0, 10)} · operator @{MOCK_USER}
            </div>
          </div>

          <nav className="flex-1 p-4">
            <SectionLabel>Index</SectionLabel>
            <NbNav code="§01" label="Datasets" active />
            <NbNav code="§02" label="Record" />
            <NbNav code="§03" label="Inference" />
            <NbNav code="§04" label="Settings" />

            <div className="mt-8" />
            <SectionLabel>Status</SectionLabel>
            <KvLine k="Hub" v="authenticated" tone="ok" />
            <KvLine k="Robot" v="so101 / wired" />
            <KvLine k="Session" v="idle" />
            <KvLine k="Queue" v="0" />
          </nav>

          <div
            className="px-5 py-4 border-t text-[11px]"
            style={{
              borderColor: "var(--nb-rule)",
              color: "var(--nb-soft)",
              fontFamily: "Fraunces, serif",
              fontStyle: "italic",
            }}
          >
            “every commit is a hypothesis.”
          </div>
        </aside>

        <main
          className="flex-1 overflow-auto"
          style={{ background: "var(--nb-paper)" }}
        >
          <div className="max-w-[1240px] mx-auto px-10 py-8">
            {/* Page heading */}
            <div className="flex items-baseline gap-4 mb-1">
              <span
                className="text-[10px] tracking-[0.4em] uppercase"
                style={{ color: "var(--nb-mark)" }}
              >
                §01 · Datasets
              </span>
              <span
                className="flex-1 h-px"
                style={{ background: "var(--nb-rule)" }}
              />
              <span
                className="text-[10px]"
                style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  color: "var(--nb-soft)",
                }}
              >
                pp. {String(Math.floor(Math.random() * 80) + 12).padStart(3, "0")}–{String(
                  Math.floor(Math.random() * 80) + 90,
                ).padStart(3, "0")}
              </span>
            </div>
            <h2
              className="text-[52px] leading-[1.02] mb-2"
              style={{
                fontFamily: "Fraunces, serif",
                fontWeight: 350,
                fontVariationSettings: "'opsz' 144, 'SOFT' 50",
                letterSpacing: "-0.02em",
              }}
            >
              Catalogue of recorded
              <span
                style={{
                  fontFamily: "'Instrument Serif', serif",
                  fontStyle: "italic",
                  fontWeight: 400,
                }}
              >
                {" "}
                episodes
              </span>
              .
            </h2>
            <p
              className="text-[14px] max-w-[640px] mb-8"
              style={{ color: "var(--nb-soft)", fontFamily: "Fraunces, serif" }}
            >
              Five active datasets — three sync clean, one is drifting, one
              broke during last upload.
            </p>

            {/* Toolbar */}
            <div
              className="flex items-center gap-2 pb-4 mb-6 border-b"
              style={{ borderColor: "var(--nb-rule)" }}
            >
              <NbButton primary>+ New entry</NbButton>
              <NbButton>Import</NbButton>
              <NbButton>Sort: recency</NbButton>
              <span className="grow" />
              <span
                className="text-[11px]"
                style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  color: "var(--nb-soft)",
                }}
              >
                {SAMPLE_DATASETS.length} items · auto-saved 12 s ago
              </span>
            </div>

            <div className="grid gap-5 grid-cols-1 lg:grid-cols-2">
              {SAMPLE_DATASETS.map((d, i) => (
                <Entry key={d.name} d={d} index={i + 1} />
              ))}
            </div>

            <div className="mt-12 text-[11px]" style={{ color: "var(--nb-soft)" }}>
              <em
                style={{
                  fontFamily: "Fraunces, serif",
                  fontWeight: 400,
                }}
              >
                end of section.
              </em>{" "}
              See §02 — Record — for capture protocol.
            </div>
          </div>
        </main>
      </div>

      <Link
        to="/mocks"
        className="fixed bottom-4 left-4 px-3 py-1.5 text-[11px] uppercase tracking-[0.3em]"
        style={{
          background: "var(--nb-paper)",
          border: "1px solid var(--nb-rule)",
          color: "var(--nb-soft)",
        }}
      >
        ← mocks
      </Link>
    </div>
  );
}

function Entry({ d, index }: { d: MockDataset; index: number }) {
  return (
    <div
      className="relative p-5 transition-shadow"
      style={{
        background: "var(--nb-paper)",
        border: "1px solid var(--nb-rule)",
        boxShadow: "2px 2px 0 var(--nb-rule-soft)",
      }}
    >
      {/* Corner ticks */}
      <CornerTicks />

      {/* Index card top */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-baseline gap-2">
            <span
              className="text-[10px] tracking-[0.32em] uppercase"
              style={{ color: "var(--nb-mark)" }}
            >
              entry · {String(index).padStart(2, "0")}
            </span>
            <NbStateChip state={d.hubState} />
          </div>
          <h3
            className="text-[28px] leading-[1.05] mt-1"
            style={{
              fontFamily: "Fraunces, serif",
              fontWeight: 420,
              fontVariationSettings: "'opsz' 144, 'SOFT' 50",
              letterSpacing: "-0.012em",
            }}
          >
            {d.name}
          </h3>
          <p
            className="text-[13px] mt-1"
            style={{
              fontFamily: "Fraunces, serif",
              fontStyle: "italic",
              color: "var(--nb-soft)",
            }}
          >
            {d.taskHint}
          </p>
        </div>
      </div>

      <table className="w-full text-[12px] mb-4">
        <tbody>
          <FactRow k="ROBOT" v={d.robot} />
          <FactRow k="CAMERAS" v={d.cameras.join(", ")} />
          <FactRow k="EPISODES" v={d.episodes.toString()} mono />
          <FactRow k="FRAMES" v={d.frames.toLocaleString()} mono />
          <FactRow k="DURATION" v={`${d.durationMin.toFixed(1)} min`} mono />
          <FactRow
            k="HUB"
            v={
              <span
                style={{
                  fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                  color: "var(--nb-ink)",
                }}
              >
                {d.hubRepo ?? "—"}
              </span>
            }
          />
          <FactRow k="TOUCHED" v={d.lastTouched} />
        </tbody>
      </table>

      <div className="flex flex-wrap items-center gap-2 pt-3 border-t"
        style={{ borderColor: "var(--nb-rule-soft)" }}>
        <NbButton primary>Open</NbButton>
        <NbButton>Push</NbButton>
        <NbButton>Edit Hub</NbButton>
        <NbButton>Export</NbButton>
        <NbButton>Annotate</NbButton>
        <span className="grow" />
        <NbButton danger>Discard</NbButton>
      </div>
    </div>
  );
}

function FactRow({
  k,
  v,
  mono,
}: {
  k: string;
  v: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <tr style={{ borderBottom: "1px dashed var(--nb-rule-soft)" }}>
      <td
        className="py-1.5 pr-3 text-[10px] tracking-[0.22em] uppercase align-top"
        style={{ color: "var(--nb-soft)", width: 100 }}
      >
        {k}
      </td>
      <td
        className="py-1.5"
        style={{
          color: "var(--nb-ink)",
          fontFamily: mono
            ? "'JetBrains Mono', ui-monospace, monospace"
            : "inherit",
        }}
      >
        {v}
      </td>
    </tr>
  );
}

function CornerTicks() {
  const t: React.CSSProperties = {
    position: "absolute",
    width: 8,
    height: 8,
    borderColor: "var(--nb-mark)",
  };
  return (
    <>
      <span style={{ ...t, top: -1, left: -1, borderTop: "1px solid", borderLeft: "1px solid" }} />
      <span style={{ ...t, top: -1, right: -1, borderTop: "1px solid", borderRight: "1px solid" }} />
      <span style={{ ...t, bottom: -1, left: -1, borderBottom: "1px solid", borderLeft: "1px solid" }} />
      <span style={{ ...t, bottom: -1, right: -1, borderBottom: "1px solid", borderRight: "1px solid" }} />
    </>
  );
}

function NbStateChip({ state }: { state: MockDataset["hubState"] }) {
  const cfg: Record<MockDataset["hubState"], { fg: string; bg: string; label: string }> = {
    synced: { fg: "var(--nb-accent)", bg: "var(--nb-accent-soft)", label: "synced" },
    stale: { fg: "var(--nb-mark)", bg: "var(--nb-mark-soft)", label: "stale" },
    pushing: { fg: "var(--nb-mark)", bg: "var(--nb-mark-soft)", label: "pushing" },
    "not-pushed": { fg: "var(--nb-soft)", bg: "transparent", label: "pending" },
    "not-configured": { fg: "var(--nb-soft)", bg: "transparent", label: "unconfigured" },
    error: { fg: "var(--nb-stop)", bg: "rgba(160,57,43,0.1)", label: "error" },
  };
  const c = cfg[state];
  return (
    <span
      className="inline-flex items-center text-[10px] tracking-[0.18em] uppercase px-2 py-0.5"
      style={{
        background: c.bg,
        color: c.fg,
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        border: state === "not-pushed" || state === "not-configured" ? "1px dashed var(--nb-rule)" : "none",
      }}
    >
      ◆ {c.label}
    </span>
  );
}

function NbButton({
  children,
  primary,
  danger,
}: {
  children: React.ReactNode;
  primary?: boolean;
  danger?: boolean;
}) {
  const bg = primary ? "var(--nb-ink)" : danger ? "rgba(160,57,43,0.08)" : "var(--nb-paper)";
  const fg = primary ? "var(--nb-paper)" : danger ? "var(--nb-stop)" : "var(--nb-ink)";
  const border = primary
    ? "var(--nb-ink)"
    : danger
    ? "var(--nb-stop)"
    : "var(--nb-rule)";
  return (
    <button
      className="text-[12px] px-3.5 py-1.5 transition-colors"
      style={{
        background: bg,
        color: fg,
        border: `1px solid ${border}`,
        fontFamily: "Inter, sans-serif",
      }}
    >
      {children}
    </button>
  );
}

function NbNav({
  code,
  label,
  active,
}: {
  code: string;
  label: string;
  active?: boolean;
}) {
  return (
    <a
      href="#"
      className="flex items-baseline gap-3 py-1.5 px-2 transition-colors"
      style={{
        background: active ? "var(--nb-accent-soft)" : "transparent",
        color: active ? "var(--nb-accent)" : "var(--nb-ink)",
      }}
    >
      <span
        className="text-[10px]"
        style={{
          fontFamily: "'JetBrains Mono', ui-monospace, monospace",
          color: active ? "var(--nb-accent)" : "var(--nb-soft)",
        }}
      >
        {code}
      </span>
      <span
        style={{
          fontFamily: active ? "Fraunces, serif" : "inherit",
          fontStyle: active ? "italic" : "normal",
        }}
      >
        {label}
      </span>
    </a>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[9px] tracking-[0.42em] uppercase mb-2"
      style={{ color: "var(--nb-soft)" }}
    >
      {children}
    </div>
  );
}

function KvLine({
  k,
  v,
  tone,
}: {
  k: string;
  v: string;
  tone?: "ok";
}) {
  return (
    <div
      className="flex items-baseline justify-between text-[12px] py-1"
      style={{
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        color: "var(--nb-ink)",
      }}
    >
      <span style={{ color: "var(--nb-soft)" }}>{k}</span>
      <span
        style={{
          color: tone === "ok" ? "var(--nb-accent)" : "var(--nb-ink)",
        }}
      >
        {v}
      </span>
    </div>
  );
}
