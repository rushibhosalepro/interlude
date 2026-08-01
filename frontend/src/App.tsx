import { useEffect, useState } from "react";

import "./index.css";
import type { Project } from "@/lib/types";
import { FileUploader } from "@/components/file-uploader";
import { JobTimeline } from "@/components/job-timeline";
import { JudgePage, useProjects } from "@/components/judge-page";
import { SampleClips } from "@/components/sample-clips";
import { Toaster } from "@/components/ui/sonner";

function clip(t: number | null) {
  if (!t || !Number.isFinite(t)) return "";
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
}

/** A placeholder that fills the demo column while projects load, so the page
 *  keeps its shape instead of collapsing to a small box in empty space. */
function DemoSkeleton({
  state,
  message,
  onRetry,
}: {
  state: "loading" | "error" | "empty";
  message: string;
  onRetry?: () => void;
}) {
  const block = (h: number | string, mt = 0) => (
    <div
      style={{
        height: h,
        width: "100%",
        marginTop: mt,
        borderRadius: 8,
        background: "#0e0e11",
        animation:
          state === "loading" ? "shimmer 1.4s ease-in-out infinite" : "none",
      }}
    />
  );

  return (
    <div
      style={{
        background: "#0a0a0b",
        border: "1px solid #1a1a1d",
        borderRadius: 14,
        overflow: "hidden",
        fontFamily: "'Space Grotesk',Helvetica,sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "18px 32px",
          borderBottom: "1px solid #16161a",
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 600, color: "#f3f1ee" }}>
          Interlude
        </div>
        <div
          style={{
            fontFamily: "'IBM Plex Mono',monospace",
            fontSize: 10,
            color: "#6fb79c",
            letterSpacing: "0.06em",
          }}
        >
          ● LIVE · NO LOGIN
        </div>
      </div>

      <div style={{ padding: "32px" }}>
        <Pitch />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)",
            gap: 22,
            marginTop: 28,
            alignItems: "start",
          }}
        >
          <div>
            <div
              style={{
                width: "100%",
                aspectRatio: "16/9",
                borderRadius: 12,
                background: "#0e0e11",
                border: "1px solid #1c1c1f",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 14,
                animation:
                  state === "loading"
                    ? "shimmer 1.4s ease-in-out infinite"
                    : "none",
              }}
            >
              {state === "loading" && (
                <div
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: "50%",
                    border: "2px solid #2a2a2f",
                    borderTopColor: "#e8a94f",
                    animation: "spin 0.8s linear infinite",
                  }}
                />
              )}
              <div
                style={{
                  fontFamily: "'IBM Plex Mono',monospace",
                  fontSize: 12,
                  color: state === "error" ? "#c76b5a" : "#75726d",
                  textAlign: "center",
                  maxWidth: "80%",
                  lineHeight: 1.5,
                }}
              >
                {message}
              </div>
              {state === "error" && onRetry && (
                <button
                  onClick={onRetry}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 8,
                    border: "1px solid #26262a",
                    background: "transparent",
                    color: "#c9c5be",
                    fontSize: 12.5,
                    cursor: "pointer",
                    fontFamily: "'Space Grotesk',Helvetica,sans-serif",
                  }}
                >
                  Try again
                </button>
              )}
            </div>
            {block(34, 14)}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {block(78)}
            {block(78)}
            {block(78)}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Static pitch, rendered immediately so the page never looks empty while the
 *  demos load. The full interactive hero inside JudgePage replaces it. */
function Pitch({ compact = false }: { compact?: boolean }) {
  return (
    <div style={{ marginBottom: compact ? 20 : 0 }}>
      <h1
        style={{
          fontSize: 44,
          lineHeight: 1.05,
          fontWeight: 600,
          letterSpacing: "-0.035em",
          maxWidth: "20em",
          margin: 0,
          color: "#f3f1ee",
          fontFamily: "'Space Grotesk',Helvetica,sans-serif",
          textWrap: "balance",
        }}
      >
        You captioned 4,000 lectures. Your blind students still can't follow one
        of them.
      </h1>
      <p
        style={{
          fontSize: 16.5,
          color: "#9a968f",
          marginTop: 16,
          maxWidth: "44em",
          fontFamily: "'Space Grotesk',Helvetica,sans-serif",
        }}
      >
        Interlude finds the silences where the lecturer is drawing instead of
        talking, writes narration short enough to fit inside them, and hands back
        the lecture with a described audio track.
      </p>
    </div>
  );
}

/** A one-line summary of what each clip demonstrates, from its numbers alone. */
function blurb(p: Project) {
  const { toFill, gapsFound } = p.metrics;
  const skipped = gapsFound - toFill;
  if (gapsFound === 0) return "no describable silences";
  if (toFill === 0) return `all ${gapsFound} silences left alone`;
  if (skipped === 0) return `every silence narrated`;
  if (skipped > toFill) return `${skipped} silences deliberately left silent`;
  return `${toFill} narrated, ${skipped} left silent`;
}

/** Vertical playlist rail of finished demos, so a judge can switch clips. */
function ClipRail({
  projects,
  selectedId,
  onSelect,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div
        style={{
          fontFamily: "'IBM Plex Mono',monospace",
          fontSize: 10.5,
          letterSpacing: "0.12em",
          color: "#7d7a75",
          lineHeight: 1.5,
        }}
      >
        {projects.length} LECTURES, ONE PIPELINE. PICK ONE.
      </div>

      {projects.map((p, i) => {
        const active = p.videoId === selectedId;
        return (
          <button
            key={p.videoId}
            onClick={() => onSelect(p.videoId)}
            style={{
              textAlign: "left",
              width: "100%",
              padding: "13px 14px",
              borderRadius: 12,
              border: `1px solid ${active ? "#e8a94f" : "#1f1f23"}`,
              background: active ? "#141310" : "#0d0d0f",
              cursor: "pointer",
              fontFamily: "'Space Grotesk',Helvetica,sans-serif",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <span
                style={{
                  fontFamily: "'IBM Plex Mono',monospace",
                  fontSize: 15,
                  fontWeight: 600,
                  color: active ? "#f3f1ee" : "#c9c5be",
                }}
              >
                {clip(p.durationSeconds) || `clip ${i + 1}`}
              </span>
              <span
                style={{
                  fontFamily: "'IBM Plex Mono',monospace",
                  fontSize: 9.5,
                  letterSpacing: "0.08em",
                  color: active ? "#6fb79c" : "#5f5c58",
                }}
              >
                {active ? "● PLAYING" : "SWITCH"}
              </span>
            </div>
            <div
              style={{
                fontSize: 12,
                color: active ? "#c9c5be" : "#8d8a85",
                marginTop: 6,
                lineHeight: 1.4,
              }}
            >
              {blurb(p)}
            </div>
            <div
              style={{
                fontFamily: "'IBM Plex Mono',monospace",
                fontSize: 10.5,
                color: active ? "#e8a94f" : "#6d6a66",
                marginTop: 5,
              }}
            >
              {p.metrics.toFill} of {p.metrics.gapsFound} narrated
            </div>
          </button>
        );
      })}
    </div>
  );
}

export function App() {
  const { projects, error, refresh } = useProjects();
  // a run started from this page, whether uploaded or a sample
  const [jobId, setJobId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // default to the shortest clip so a judge's first play loads fast; the rail
  // lets them switch to the longer ones. falls back to the first if durations
  // are missing.
  useEffect(() => {
    if (!projects?.length) return;
    if (projects.some((p) => p.videoId === selectedId)) return;
    const shortest = [...projects].sort(
      (a, b) => (a.durationSeconds ?? 1e9) - (b.durationSeconds ?? 1e9),
    )[0];
    if (shortest) setSelectedId(shortest.videoId);
  }, [projects, selectedId]);

  const shortestFirst = projects
    ? [...projects].sort(
        (a, b) => (a.durationSeconds ?? 1e9) - (b.durationSeconds ?? 1e9),
      )
    : null;

  const featured =
    projects?.find((p) => p.videoId === selectedId) ?? shortestFirst?.[0];

  const runPanel = (
    <div
      style={{
        border: "1px dashed #26262a",
        borderRadius: 12,
        background: "#0c0c0e",
        padding: 18,
      }}
    >
      <div style={{ fontSize: 13.5, fontWeight: 600, color: "#f3f1ee" }}>
        Run it on a clip we have never seen
      </div>
      <div
        style={{
          fontSize: 12,
          color: "#75726d",
          marginTop: 5,
          lineHeight: 1.45,
        }}
      >
        Up to 15 minutes, MP4 or MOV, straight to Backblaze B2. No account, no
        email.
      </div>
      <div style={{ marginTop: 13 }}>
        <FileUploader
          onQueued={setJobId}
          onFinished={() => {
            setJobId(null);
            refresh();
          }}
        />
        <SampleClips onQueued={setJobId} />
      </div>
    </div>
  );

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#070708",
        padding: "40px 24px",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div style={{ width: "100%", maxWidth: 1300 }}>
        {jobId && (
          <div
            style={{
              marginBottom: 24,
              background: "#0a0a0b",
              border: "1px solid #1a1a1d",
              borderRadius: 14,
              padding: 24,
            }}
          >
            <JobTimeline
              jobId={jobId}
              onFinished={() => {
                setJobId(null);
                refresh();
              }}
            />
          </div>
        )}

        {featured ? (
          <div
            style={{
              display: "flex",
              gap: 20,
              alignItems: "flex-start",
              flexWrap: "wrap",
            }}
          >
            <aside
              style={{
                width: 288,
                flex: "1 1 288px",
                maxWidth: 320,
                position: "sticky",
                top: 24,
                display: "flex",
                flexDirection: "column",
                gap: 18,
              }}
            >
              {shortestFirst && shortestFirst.length > 1 && (
                <ClipRail
                  projects={shortestFirst}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              )}
              {runPanel}
            </aside>
            <div style={{ flex: "1 1 620px", minWidth: 0 }}>
              <JudgePage key={featured.videoId} project={featured} />
            </div>
          </div>
        ) : (
          <div
            style={{
              display: "flex",
              gap: 20,
              alignItems: "flex-start",
              flexWrap: "wrap",
            }}
          >
            <aside
              style={{
                width: 288,
                flex: "1 1 288px",
                maxWidth: 320,
                position: "sticky",
                top: 24,
              }}
            >
              {runPanel}
            </aside>
            <div style={{ flex: "1 1 620px", minWidth: 0 }}>
              <DemoSkeleton
                state={error ? "error" : projects === null ? "loading" : "empty"}
                message={
                  error
                    ? "Could not reach the server. It may be starting up, or the storage cap is refreshing."
                    : projects === null
                      ? "Loading the described lectures"
                      : "No finished runs yet. Start one on the left."
                }
                onRetry={refresh}
              />
            </div>
          </div>
        )}
      </div>

      <Toaster position="bottom-right" richColors />
    </main>
  );
}

export default App;
