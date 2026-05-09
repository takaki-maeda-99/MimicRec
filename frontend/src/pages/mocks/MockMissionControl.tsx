import { Link } from "react-router-dom";
import { SAMPLE_DATASETS, MOCK_USER, type MockDataset } from "./sample-data";

// "Mission Control" — operator console aesthetic.
// Dark deck, JetBrains Mono everywhere, telemetry pulses, amber + cyan accents.
// Inspired by avionics MFDs, Raspberry-Pi mission ops dashboards, and the way
// SpaceX engineering consoles let dense data breathe through hierarchy alone.

export default function MockMissionControl() {
  const totalEp = SAMPLE_DATASETS.reduce((s, d) => s + d.episodes, 0);
  const totalFr = SAMPLE_DATASETS.reduce((s, d) => s + d.frames, 0);
  return (
    <div
      className="min-h-screen w-full font-mono text-[13px] leading-tight selection:bg-amber-300 selection:text-black"
      style={{
        ["--mc-bg" as string]: "#08090b",
        ["--mc-panel" as string]: "#0d1014",
        ["--mc-line" as string]: "#1c2127",
        ["--mc-line-soft" as string]: "#13171c",
        ["--mc-ink" as string]: "#e6e8eb",
        ["--mc-dim" as string]: "#7a8088",
        ["--mc-dimmer" as string]: "#4a4e54",
        ["--mc-amber" as string]: "#f0a93b",
        ["--mc-cyan" as string]: "#5dd6c7",
        ["--mc-red" as string]: "#ff5f6b",
        background: "var(--mc-bg)",
        color: "var(--mc-ink)",
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
      }}
    >
      <div className="flex h-screen">
        {/* Sidebar deck */}
        <aside
          className="w-52 border-r flex flex-col"
          style={{ borderColor: "var(--mc-line)", background: "var(--mc-panel)" }}
        >
          <div
            className="px-4 py-3 border-b flex flex-col gap-1"
            style={{ borderColor: "var(--mc-line)" }}
          >
            <div className="flex items-center justify-between">
              <span style={{ color: "var(--mc-amber)" }} className="text-[11px] tracking-[0.18em]">
                MIMIC//REC
              </span>
              <PulseDot color="var(--mc-cyan)" />
            </div>
            <div className="text-[10px]" style={{ color: "var(--mc-dim)" }}>
              ops_console v0.42 · {new Date().toISOString().slice(11, 19)}Z
            </div>
          </div>

          <nav className="flex-1 py-2">
            {[
              { code: "01", label: "DATASETS", active: true },
              { code: "02", label: "RECORD" },
              { code: "03", label: "INFERENCE" },
              { code: "04", label: "SETTINGS" },
            ].map((it) => (
              <a
                key={it.label}
                href="#"
                className="group flex items-center gap-3 px-4 py-2 transition-colors"
                style={{
                  color: it.active ? "var(--mc-amber)" : "var(--mc-ink)",
                  borderLeft: it.active ? "2px solid var(--mc-amber)" : "2px solid transparent",
                  background: it.active ? "rgba(240,169,59,0.06)" : "transparent",
                }}
              >
                <span
                  className="text-[10px]"
                  style={{ color: it.active ? "var(--mc-amber)" : "var(--mc-dimmer)" }}
                >
                  {it.code}
                </span>
                <span className="tracking-[0.14em] text-[12px]">{it.label}</span>
                {it.active && (
                  <span className="ml-auto" style={{ color: "var(--mc-amber)" }}>
                    ›
                  </span>
                )}
              </a>
            ))}
          </nav>

          <div
            className="border-t px-4 py-3 flex flex-col gap-2"
            style={{ borderColor: "var(--mc-line)", background: "var(--mc-bg)" }}
          >
            <RowKv k="LINK" v={<><PulseDot color="var(--mc-cyan)" inline /> ONLINE</>} />
            <RowKv k="HF" v={`@${MOCK_USER}`} accent="var(--mc-amber)" />
            <RowKv k="GPU" v="A6000 / 22.4°C" />
            <RowKv k="QUEUE" v="0 jobs" />
          </div>
        </aside>

        {/* Main deck */}
        <main className="flex-1 overflow-auto">
          {/* Top status bar */}
          <div
            className="border-b flex items-stretch"
            style={{ borderColor: "var(--mc-line)", background: "var(--mc-panel)" }}
          >
            <Crumb label="MISSION" value="ops" />
            <Crumb label="VIEW" value="datasets" highlight />
            <Crumb label="SCOPE" value="all" />
            <div className="flex-1" />
            <Crumb label="DATASETS" value={String(SAMPLE_DATASETS.length).padStart(2, "0")} />
            <Crumb label="EPISODES" value={totalEp.toLocaleString()} />
            <Crumb label="FRAMES" value={totalFr.toLocaleString()} />
            <button
              className="px-5 border-l text-[12px] tracking-[0.18em] transition-colors hover:bg-black/30"
              style={{
                borderColor: "var(--mc-line)",
                color: "var(--mc-amber)",
              }}
            >
              + NEW DATASET
            </button>
          </div>

          {/* Body grid */}
          <div className="px-6 py-5">
            <div className="flex items-baseline gap-3 mb-3">
              <h2 className="text-[10px] tracking-[0.32em]" style={{ color: "var(--mc-dim)" }}>
                §A · TELEMETRY
              </h2>
              <div className="flex-1 h-px" style={{ background: "var(--mc-line)" }} />
              <span className="text-[10px]" style={{ color: "var(--mc-dim)" }}>
                LIVE
              </span>
            </div>

            <div
              className="grid border-t border-l"
              style={{
                gridTemplateColumns: "44px 1.4fr 0.6fr 0.7fr 0.7fr 0.9fr 1.1fr 0.8fr",
                borderColor: "var(--mc-line)",
              }}
            >
              {[
                "#",
                "DATASET",
                "EP",
                "FRAMES",
                "DUR",
                "CAMERAS",
                "HUB",
                "ACTIONS",
              ].map((h) => (
                <div
                  key={h}
                  className="text-[10px] tracking-[0.20em] py-2 px-3 border-b border-r"
                  style={{
                    color: "var(--mc-dim)",
                    borderColor: "var(--mc-line)",
                    background: "var(--mc-panel)",
                  }}
                >
                  {h}
                </div>
              ))}
              {SAMPLE_DATASETS.map((d, i) => (
                <Row key={d.name} d={d} index={i + 1} />
              ))}
            </div>

            <div className="mt-6 flex items-baseline gap-3">
              <h2 className="text-[10px] tracking-[0.32em]" style={{ color: "var(--mc-dim)" }}>
                §B · INPUT BUS
              </h2>
              <div className="flex-1 h-px" style={{ background: "var(--mc-line)" }} />
            </div>
            <div
              className="mt-3 grid grid-cols-3 gap-3 border-t pt-3"
              style={{ borderColor: "var(--mc-line-soft)" }}
            >
              <Module title="ROBOT" lines={["so101 / wired", "calibrated 2026-05-08"]} />
              <Module title="CAMERAS" lines={["front · 1280×720@30", "wrist · 640×480@30"]} />
              <Module
                title="HUB"
                lines={[`@${MOCK_USER}`, "huggingface_hub 1.14"]}
                accent="var(--mc-amber)"
              />
            </div>
          </div>
        </main>
      </div>

      <Link
        to="/mocks"
        className="fixed bottom-4 left-4 px-3 py-1 text-[11px] tracking-[0.2em] border"
        style={{
          background: "var(--mc-panel)",
          borderColor: "var(--mc-line)",
          color: "var(--mc-dim)",
        }}
      >
        ← MOCKS
      </Link>
    </div>
  );
}

function Row({ d, index }: { d: MockDataset; index: number }) {
  const cellBase = "py-3 px-3 border-b border-r flex items-center";
  const border = "var(--mc-line-soft)";
  return (
    <>
      <div
        className={cellBase + " text-[10px] justify-center"}
        style={{ borderColor: border, color: "var(--mc-dimmer)" }}
      >
        {String(index).padStart(2, "0")}
      </div>
      <div
        className={cellBase + " gap-2"}
        style={{ borderColor: border }}
      >
        <span className="text-[13px]" style={{ color: "var(--mc-ink)" }}>
          {d.name}
        </span>
        <span
          className="text-[10px] tracking-[0.15em]"
          style={{ color: "var(--mc-dim)" }}
        >
          // {d.taskHint}
        </span>
      </div>
      <div
        className={cellBase}
        style={{ borderColor: border, color: "var(--mc-cyan)" }}
      >
        {d.episodes}
      </div>
      <div
        className={cellBase}
        style={{ borderColor: border, color: "var(--mc-ink)" }}
      >
        {d.frames.toLocaleString()}
      </div>
      <div className={cellBase} style={{ borderColor: border, color: "var(--mc-ink)" }}>
        {d.durationMin.toFixed(1)}m
      </div>
      <div
        className={cellBase + " gap-1 flex-wrap"}
        style={{ borderColor: border }}
      >
        {d.cameras.map((c) => (
          <span
            key={c}
            className="text-[10px] tracking-[0.1em] px-1.5 py-0.5 border"
            style={{
              borderColor: "var(--mc-line)",
              color: "var(--mc-dim)",
            }}
          >
            {c}
          </span>
        ))}
      </div>
      <div className={cellBase + " gap-2"} style={{ borderColor: border }}>
        <HubChip state={d.hubState} repo={d.hubRepo} />
      </div>
      <div className={cellBase + " gap-1"} style={{ borderColor: border }}>
        <ConsoleBtn>OPEN</ConsoleBtn>
        <ConsoleBtn accent="var(--mc-amber)">PUSH</ConsoleBtn>
        <ConsoleBtn accent="var(--mc-red)">DROP</ConsoleBtn>
      </div>
    </>
  );
}

function HubChip({
  state,
  repo,
}: {
  state: MockDataset["hubState"];
  repo?: string;
}) {
  const styles: Record<MockDataset["hubState"], { bg: string; fg: string; label: string }> = {
    synced: { bg: "rgba(93,214,199,0.12)", fg: "var(--mc-cyan)", label: "SYNCED" },
    stale: { bg: "rgba(240,169,59,0.12)", fg: "var(--mc-amber)", label: "STALE" },
    pushing: { bg: "rgba(93,214,199,0.18)", fg: "var(--mc-cyan)", label: "▶ PUSHING" },
    "not-pushed": { bg: "transparent", fg: "var(--mc-dim)", label: "QUEUED 00" },
    "not-configured": { bg: "transparent", fg: "var(--mc-dimmer)", label: "—" },
    error: { bg: "rgba(255,95,107,0.14)", fg: "var(--mc-red)", label: "FAULT" },
  };
  const s = styles[state];
  return (
    <div className="flex items-center gap-2">
      <span
        className="text-[10px] tracking-[0.18em] px-1.5 py-0.5"
        style={{ background: s.bg, color: s.fg }}
      >
        {s.label}
      </span>
      <span className="text-[11px]" style={{ color: "var(--mc-dim)" }}>
        {repo ?? "—"}
      </span>
    </div>
  );
}

function ConsoleBtn({
  children,
  accent = "var(--mc-cyan)",
}: {
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <button
      className="text-[10px] tracking-[0.18em] px-2 py-1 border transition-colors hover:bg-black/30"
      style={{
        borderColor: accent,
        color: accent,
      }}
    >
      {children}
    </button>
  );
}

function PulseDot({ color, inline = false }: { color: string; inline?: boolean }) {
  return (
    <span
      className={inline ? "inline-block" : ""}
      style={{
        width: 6,
        height: 6,
        borderRadius: 999,
        background: color,
        boxShadow: `0 0 0 0 ${color}`,
        animation: "mc-pulse 1.6s ease-out infinite",
        verticalAlign: "middle",
        marginRight: inline ? 6 : 0,
      }}
    >
      <style>{`
        @keyframes mc-pulse {
          0%   { box-shadow: 0 0 0 0 ${color}aa; }
          70%  { box-shadow: 0 0 0 8px ${color}00; }
          100% { box-shadow: 0 0 0 0 ${color}00; }
        }
      `}</style>
    </span>
  );
}

function Crumb({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className="px-4 py-2 border-r flex flex-col gap-0.5"
      style={{ borderColor: "var(--mc-line)" }}
    >
      <span className="text-[9px] tracking-[0.22em]" style={{ color: "var(--mc-dim)" }}>
        {label}
      </span>
      <span
        className="text-[12px] tracking-[0.05em]"
        style={{ color: highlight ? "var(--mc-amber)" : "var(--mc-ink)" }}
      >
        {value}
      </span>
    </div>
  );
}

function RowKv({
  k,
  v,
  accent,
}: {
  k: string;
  v: React.ReactNode;
  accent?: string;
}) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span style={{ color: "var(--mc-dim)" }} className="tracking-[0.18em] text-[10px]">
        {k}
      </span>
      <span style={{ color: accent || "var(--mc-ink)" }}>{v}</span>
    </div>
  );
}

function Module({
  title,
  lines,
  accent,
}: {
  title: string;
  lines: string[];
  accent?: string;
}) {
  return (
    <div
      className="border p-3 flex flex-col gap-1"
      style={{ borderColor: "var(--mc-line)", background: "var(--mc-panel)" }}
    >
      <div
        className="text-[10px] tracking-[0.22em]"
        style={{ color: accent || "var(--mc-dim)" }}
      >
        {title}
      </div>
      {lines.map((l, i) => (
        <div
          key={i}
          className="text-[12px]"
          style={{ color: i === 0 ? "var(--mc-ink)" : "var(--mc-dim)" }}
        >
          {l}
        </div>
      ))}
    </div>
  );
}
