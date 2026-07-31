import type { Project, SkippedGap } from "@/lib/types";

const AMBER = "#e8a94f";

function clock(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * The silences it deliberately did not narrate, with the model's reason.
 *
 * Restraint is the central claim, and until now the page only showed what was
 * narrated, which argues the opposite. Over-narration is the classic failure of
 * bad audio description, so showing the decisions not to speak is the evidence.
 */
export function LeftSilent({ project }: { project: Project }) {
  const { skipped, metrics } = project;
  if (!skipped.length) return null;

  return (
    <div
      style={{
        border: "1px solid #1a1a1d",
        borderRadius: 12,
        background: "#0d0d0f",
        padding: 18,
      }}
    >
      <div
        style={{
          fontFamily: "'IBM Plex Mono',monospace",
          fontSize: 10,
          letterSpacing: "0.12em",
          color: "#7d7a75",
          marginBottom: 4,
        }}
      >
        LEFT SILENT ON PURPOSE · {skipped.length} OF {metrics.gapsFound}
      </div>
      <div style={{ fontSize: 12, color: "#75726d", lineHeight: 1.45, marginBottom: 12 }}>
        Talking through every silence is how audio description gets worse, not
        better. These are the gaps it decided not to fill, and why.
      </div>

      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {skipped.map((gap: SkippedGap) => (
          <li
            key={gap.gapId}
            style={{
              display: "flex",
              gap: 10,
              padding: "9px 0",
              borderTop: "1px solid #17171a",
            }}
          >
            <span
              style={{
                fontFamily: "'IBM Plex Mono',monospace",
                fontSize: 11,
                color: "#5f5c58",
                flex: "none",
                paddingTop: 2,
                width: 62,
              }}
            >
              {clock(gap.startsAt)} · {gap.durationSeconds.toFixed(1)}s
            </span>
            <span style={{ fontSize: 12.5, color: "#9a968f", lineHeight: 1.45 }}>
              {gap.reason}
            </span>
          </li>
        ))}
      </ul>

      <div
        style={{
          fontSize: 11.5,
          color: "#75726d",
          marginTop: 12,
          paddingTop: 11,
          borderTop: "1px solid #17171a",
          lineHeight: 1.45,
        }}
      >
        Description density{" "}
        <span style={{ color: AMBER, fontFamily: "'IBM Plex Mono',monospace" }}>
          {Math.round(metrics.density * 100)}%
        </span>
        . Restraint is the correct behaviour, so this number should be low.
      </div>
    </div>
  );
}
