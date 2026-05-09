import { Link } from "react-router-dom";

const mocks = [
  {
    to: "/mocks/mission-control",
    code: "A",
    title: "Mission Control",
    sub: "Operator console · Mono · Amber + Cyan on graphite",
    blurb:
      "Avionics-style telemetry deck. Tight grid, status pulses, every action a rectangle button. Best when you mostly care about scanning rows of numbers fast.",
    palette: ["#08090b", "#1c2127", "#f0a93b", "#5dd6c7"],
    fontStack:
      "'JetBrains Mono', ui-monospace, monospace",
    tone: "dark",
  },
  {
    to: "/mocks/editorial",
    code: "B",
    title: "Editorial Workshop",
    sub: "Magazine · Fraunces serif · Cream paper",
    blurb:
      "Editorial typography meets dev tool. Big serif headlines, asymmetric columns, generous space. Best when you want recordings to feel like a curated archive instead of a database.",
    palette: ["#f7f1e6", "#fcf8f0", "#a23a2c", "#1d1a14"],
    fontStack: "Fraunces, serif",
    tone: "light",
  },
  {
    to: "/mocks/notebook",
    code: "C",
    title: "Lab Notebook",
    sub: "Research bench · Hairline grid · Serif + Mono mix",
    blurb:
      "Research notebook with §-numbered sections, hairline grid, corner ticks on every entry. Best when density matters AND every row should still feel labelled and trustworthy.",
    palette: ["#f3eee2", "#fbf6e9", "#274936", "#c87a2a"],
    fontStack: "Fraunces, serif",
    tone: "light",
  },
];

export default function MockIndex() {
  return (
    <div
      className="min-h-screen p-12"
      style={{
        background:
          "radial-gradient(circle at 20% 0%, #f7f1e6 0%, #fbf8f0 40%, #fcfbf6 100%)",
        color: "#1a1a1a",
        fontFamily:
          "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      <div className="max-w-[1200px] mx-auto">
        <div className="flex items-end justify-between mb-12 border-b border-[#d8cdb8] pb-6">
          <div>
            <div className="text-[11px] tracking-[0.4em] uppercase text-[#8a7e60] mb-2">
              Layout study · 3 directions
            </div>
            <h1
              className="text-[80px] leading-[0.9]"
              style={{
                fontFamily: "Fraunces, serif",
                fontWeight: 320,
                fontVariationSettings: "'opsz' 144, 'SOFT' 100, 'WONK' 1",
                letterSpacing: "-0.025em",
              }}
            >
              Pick a flavour
              <span
                style={{
                  fontStyle: "italic",
                  fontFamily: "'Instrument Serif', Fraunces, serif",
                  fontWeight: 400,
                }}
              >
                .
              </span>
            </h1>
          </div>
          <Link
            to="/datasets"
            className="text-[12px] tracking-[0.18em] uppercase px-5 py-2 border border-[#1d1a14] rounded-full hover:bg-[#1d1a14] hover:text-[#fcf8f0] transition-colors"
          >
            ← back to app
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {mocks.map((m) => (
            <Link
              key={m.to}
              to={m.to}
              className="group relative block p-6 rounded-lg border border-[#d8cdb8] hover:border-[#1d1a14] transition-all"
              style={{
                background: m.tone === "dark" ? "#0d1014" : "#fcf8f0",
                color: m.tone === "dark" ? "#e6e8eb" : "#1d1a14",
              }}
            >
              <div className="flex items-start justify-between mb-4">
                <span
                  className="text-[60px] leading-none"
                  style={{
                    fontFamily: m.fontStack,
                    fontWeight: m.tone === "dark" ? 500 : 350,
                    color: m.tone === "dark" ? "#f0a93b" : "#a23a2c",
                  }}
                >
                  {m.code}
                </span>
                <div className="flex flex-col items-end gap-1">
                  {m.palette.map((c, i) => (
                    <span
                      key={i}
                      className="block w-4 h-4 border"
                      style={{
                        background: c,
                        borderColor:
                          m.tone === "dark"
                            ? "rgba(255,255,255,0.1)"
                            : "rgba(0,0,0,0.1)",
                      }}
                    />
                  ))}
                </div>
              </div>
              <h2
                className="text-[28px] leading-[1.05] mb-1"
                style={{
                  fontFamily:
                    m.code === "A"
                      ? "'JetBrains Mono', ui-monospace, monospace"
                      : "Fraunces, serif",
                  fontWeight: m.code === "A" ? 500 : 400,
                  letterSpacing: m.code === "A" ? "-0.01em" : "-0.015em",
                }}
              >
                {m.title}
              </h2>
              <div
                className="text-[11px] tracking-[0.2em] uppercase mb-4"
                style={{
                  color: m.tone === "dark" ? "#7a8088" : "#8a7e60",
                }}
              >
                {m.sub}
              </div>
              <p
                className="text-[14px] leading-relaxed"
                style={{
                  color: m.tone === "dark" ? "#b9bcc1" : "#3f3a30",
                }}
              >
                {m.blurb}
              </p>
              <div
                className="mt-5 inline-flex items-center gap-2 text-[12px] tracking-[0.18em] uppercase"
                style={{
                  color: m.tone === "dark" ? "#5dd6c7" : "#a23a2c",
                }}
              >
                Open mock
                <span className="transition-transform group-hover:translate-x-1">
                  →
                </span>
              </div>
            </Link>
          ))}
        </div>

        <div
          className="mt-16 grid md:grid-cols-3 gap-6 text-[13px]"
          style={{ color: "#5b5448" }}
        >
          <p>
            Each mock owns its full screen — sidebar, top bar, datasets list and
            sample episode card — so you can compare how dense vs. airy each one
            feels with the same data.
          </p>
          <p>
            Click around. The mocks aren't wired to the real backend; they
            reuse a small fixture so the visual rhythm survives.
          </p>
          <p>
            Once one feels right, I'll graft just the pieces you like onto the
            real <code>Layout.tsx</code>, <code>DatasetsPage.tsx</code> and{" "}
            <code>ReplayPage.tsx</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
