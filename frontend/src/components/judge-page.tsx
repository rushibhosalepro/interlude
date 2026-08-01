import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";

import { LeftSilent } from "@/components/left-silent";
import type { Project } from "@/lib/types";

const API_URL = process.env.BUN_PUBLIC_API_URL;

const AMBER = "#e8a94f";
const GREEN = "#6fb79c";
const RED = "#c76b5a";
const INK = "#f3f1ee";

function clock(t: number) {
  if (!Number.isFinite(t)) return "0:00";
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
}

/** The player, its gap overlay and the banded scrubber. */
function Player({ project }: { project: Project }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [described, setDescribed] = useState(true);
  const [loadedDuration, setLoadedDuration] = useState(0);
  // true while the file is fetching/buffering, so a click gives instant feedback
  // instead of a black box (preload=metadata means first play always buffers)
  const [buffering, setBuffering] = useState(false);

  // Two real files, not one file muted. The described cut is the deliverable;
  // the original is the untouched upload, so the A/B is an actual comparison.
  const src = described ? project.videoUrl : project.originalUrl;

  // where playback was when the source was swapped, restored once the new file
  // has metadata, so switching does not send the judge back to zero
  const restoreRef = useRef<{ at: number; playing: boolean } | null>(null);

  // transcript duration is authoritative, but fall back to the file's own so a
  // null never collapses the scrubber and throws every gap band off it
  const duration = project.durationSeconds || loadedDuration || 1;
  const narratedGaps = project.gaps.filter((g) => g.narrated);

  // which narrated gap, if any, is playing right now
  const current = useMemo(
    () => narratedGaps.find((g) => t >= g.start && t <= g.end),
    [t, narratedGaps],
  );
  const currentText = current
    ? project.descriptions.find((d) => d.gapId === current.gapId)?.text
    : undefined;

  const switchTo = (next: boolean) => {
    if (next === described) return;
    const video = videoRef.current;
    if (video) restoreRef.current = { at: video.currentTime, playing: !video.paused };
    setDescribed(next);
  };

  // React swaps the src on the next render; put playback back where it was once
  // the new file reports metadata
  useEffect(() => {
    const video = videoRef.current;
    const restore = restoreRef.current;
    if (!video || !restore) return;

    const onLoaded = () => {
      video.currentTime = restore.at;
      if (restore.playing) video.play().catch(() => {});
      restoreRef.current = null;
    };

    video.addEventListener("loadedmetadata", onLoaded, { once: true });
    return () => video.removeEventListener("loadedmetadata", onLoaded);
  }, [src]);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      video.pause();
    } else {
      // instant feedback: the file usually has to fetch before the first frame
      if (video.readyState < 3) setBuffering(true);
      video.play().catch(() => {});
    }
  };

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const next = ((e.clientX - rect.left) / rect.width) * duration;
    setT(next);
    if (videoRef.current) videoRef.current.currentTime = next;
  };

  const modeSwitch = (big: boolean) => (
    <div
      style={{
        display: "flex",
        gap: 5,
        padding: 4,
        background: "#141417",
        borderRadius: 999,
        flex: "none",
      }}
    >
      {(["Original", "Described"] as const).map((label) => {
        const active = (label === "Described") === described;
        return (
          <div
            key={label}
            onClick={() => switchTo(label === "Described")}
            style={{
              padding: big ? "9px 20px" : "7px 14px",
              borderRadius: 999,
              fontSize: big ? 13.5 : 12,
              fontWeight: 500,
              cursor: "pointer",
              background: active ? INK : "transparent",
              color: active ? "#0a0a0b" : "#8d8a85",
            }}
          >
            {label}
          </div>
        );
      })}
    </div>
  );

  return (
    <div>
      {/* The A/B is the whole argument in one click, so it leads rather than
          sitting as a small pill among the transport controls. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        {modeSwitch(true)}
        <div style={{ fontSize: 13, color: "#9a968f", lineHeight: 1.4 }}>
          {described ? (
            <>
              Switch to <strong style={{ color: INK }}>Original</strong> to hear what
              a blind student gets today.
            </>
          ) : (
            <>
              This is the lecture as it ships. Switch back to{" "}
              <strong style={{ color: INK }}>Described</strong> for the same moment,
              narrated.
            </>
          )}
        </div>
      </div>

      <div
        style={{
          position: "relative",
          width: "100%",
          aspectRatio: "16/9",
          borderRadius: 12,
          overflow: "hidden",
          background: "#08080a",
          border: "1px solid #1c1c1f",
        }}
      >
        <video
          ref={videoRef}
          src={src}
          // metadata, not auto. auto pulls the whole file on every page load
          // even if nobody presses play, and the B2 account is on a 1 GB/day
          // download cap. Headers cost a few KB; the file is only fetched when
          // someone actually watches. Worth the brief buffer on first play.
          preload="metadata"
          playsInline
          onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setLoadedDuration(e.currentTarget.duration || 0)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onWaiting={() => setBuffering(true)}
          onStalled={() => setBuffering(true)}
          onPlaying={() => setBuffering(false)}
          onCanPlay={() => setBuffering(false)}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />

        {buffering && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: 12,
              background: "rgba(8,8,10,0.55)",
              pointerEvents: "none",
            }}
          >
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: "50%",
                border: "3px solid rgba(255,255,255,0.18)",
                borderTopColor: AMBER,
                animation: "spin 0.8s linear infinite",
              }}
            />
            <div
              style={{
                fontFamily: "'IBM Plex Mono',monospace",
                fontSize: 11,
                letterSpacing: "0.08em",
                color: "#c9c5be",
              }}
            >
              LOADING THE LECTURE
            </div>
          </div>
        )}

        {current && (
          <div
            style={{
              position: "absolute",
              inset: "auto 0 0 0",
              padding: "60px 24px 22px",
              background:
                "linear-gradient(to top,rgba(7,7,8,0.96),rgba(7,7,8,0))",
            }}
          >
            <div
              style={{
                fontFamily: "'IBM Plex Mono',monospace",
                fontSize: 10,
                letterSpacing: "0.12em",
                color: described ? AMBER : "#6d6a66",
                marginBottom: 8,
              }}
            >
              {described
                ? `NARRATION FILLING A ${current.duration.toFixed(1)}s SILENCE`
                : `SILENCE, ${current.duration.toFixed(1)}s, NOTHING CONVEYED`}
            </div>
            <div
              style={{
                fontSize: 18,
                lineHeight: 1.4,
                color: described ? INK : "#8d8a85",
                maxWidth: "34em",
              }}
            >
              {described
                ? currentText
                : "The lecturer is silent here, and the original audio carries none of what is on screen."}
            </div>
          </div>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 13, marginTop: 14 }}>
        <div
          onClick={toggle}
          style={{
            width: 44,
            height: 44,
            flex: "none",
            borderRadius: "50%",
            background: INK,
            color: "#0a0a0b",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          {playing ? "❚❚" : "▶"}
        </div>

        <div
          style={{
            fontFamily: "'IBM Plex Mono',monospace",
            fontSize: 12.5,
            color: "#c9c5be",
            width: 86,
            flex: "none",
          }}
        >
          {clock(t)} / {clock(duration)}
        </div>

        <div
          onClick={seek}
          style={{
            flex: 1,
            minWidth: 0,
            position: "relative",
            height: 32,
            cursor: "crosshair",
            borderRadius: 6,
            background: "#131316",
            overflow: "hidden",
          }}
        >
          {narratedGaps.map((g) => (
            <div
              key={g.gapId}
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: `${(g.start / duration) * 100}%`,
                width: `${((g.end - g.start) / duration) * 100}%`,
                background: "rgba(232,169,79,0.22)",
                borderLeft: "1px solid rgba(232,169,79,0.6)",
                borderRight: "1px solid rgba(232,169,79,0.6)",
              }}
            />
          ))}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${(t / duration) * 100}%`,
              width: 2,
              background: INK,
            }}
          />
        </div>

        <a
          href={project.downloadUrl}
          style={{
            padding: "11px 15px",
            border: "1px solid #26262a",
            borderRadius: 8,
            fontSize: 12.5,
            color: "#c9c5be",
            flex: "none",
            textDecoration: "none",
          }}
        >
          Download described lecture
        </a>
      </div>

      <div
        style={{
          fontFamily: "'IBM Plex Mono',monospace",
          fontSize: 10,
          color: "#5f5c58",
          marginTop: 9,
          letterSpacing: "0.05em",
        }}
      >
        AMBER BANDS ARE THE SILENCES IT CHOSE TO NARRATE. SCRUB ANYWHERE. THE TOGGLE
        DOES NOT RESTART PLAYBACK.
      </div>
    </div>
  );
}

function StatCard({
  value,
  before,
  label,
  color = INK,
}: {
  value: string;
  before?: string;
  label: string;
  color?: string;
}) {
  return (
    <div
      style={{
        border: "1px solid #1a1a1d",
        borderRadius: 12,
        background: "#0d0d0f",
        padding: "16px 18px",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
        {before && (
          <div
            style={{
              fontFamily: "'IBM Plex Mono',monospace",
              fontSize: 15,
              color: "#5c5a56",
              textDecoration: "line-through",
            }}
          >
            {before}
          </div>
        )}
        <div
          style={{
            fontFamily: "'IBM Plex Mono',monospace",
            fontSize: 24,
            fontWeight: 600,
            color,
            letterSpacing: "-0.03em",
          }}
        >
          {value}
        </div>
      </div>
      <div style={{ fontSize: 12.5, color: "#8d8a85", marginTop: 6, lineHeight: 1.4 }}>
        {label}
      </div>
    </div>
  );
}

export function JudgePage({
  project,
  actions,
}: {
  project: Project;
  actions?: React.ReactNode;
}) {
  // the design is drawn at 1180px. below that the side by side layout squeezes
  // the player, so stack instead.
  const [wide, setWide] = useState(
    typeof window === "undefined" ? true : window.innerWidth >= 1100,
  );
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= 1100);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const cols = wide ? "minmax(0,1.6fr) minmax(0,1fr)" : "minmax(0,1fr)";
  const m = project.metrics;
  const skipped = m.gapsFound - m.toFill;

  // Show coverage as honest counts ("2 of 3 facts"), not a percentage. The
  // sample is 1-3 facts per short clip, so "100%" reads as inflated; the raw
  // count makes the small sample visible, which is the honest thing.
  const covTotal = project.coverage.facts.length;
  const covAfter = project.coverage.facts.filter((f) => f.recovered).length;
  const covBefore = Math.round(project.coverage.before * covTotal);

  // the gap with the most attempts is the one worth showing the loop for
  const showcase = useMemo(
    () =>
      [...project.descriptions].sort(
        (a, b) => b.attempts.length - a.attempts.length,
      )[0],
    [project.descriptions],
  );

  return (
    <div
      style={{
        background: "#0a0a0b",
        border: "1px solid #1a1a1d",
        borderRadius: 14,
        overflow: "hidden",
        fontFamily: "'Space Grotesk',Helvetica,sans-serif",
        color: INK,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "18px 40px",
          borderBottom: "1px solid #16161a",
        }}
      >
        <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.02em" }}>
          Interlude
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            fontFamily: "'IBM Plex Mono',monospace",
            fontSize: 10,
            color: GREEN,
            letterSpacing: "0.06em",
          }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: GREEN,
              animation: "livedot 1.8s ease-in-out infinite",
            }}
          />
          LIVE · NO LOGIN
        </div>
      </div>

      <div style={{ padding: "44px 40px 40px" }}>
        <h1
          style={{
            fontSize: 46,
            lineHeight: 1.05,
            fontWeight: 600,
            letterSpacing: "-0.035em",
            maxWidth: "20em",
            margin: 0,
            textWrap: "balance",
          }}
        >
          You captioned every lecture. Your blind students still can't follow one.
        </h1>
        <p style={{ fontSize: 16.5, color: "#9a968f", marginTop: 16, maxWidth: "44em" }}>
          Interlude finds the silences where the lecturer is drawing instead of
          talking, writes narration short enough to fit inside them, and hands back
          the lecture with a described audio track.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: cols,
            gap: 26,
            marginTop: 30,
            alignItems: "start",
          }}
        >
          <Player project={project} />

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <StatCard
              value={`${m.toFill} of ${m.gapsFound}`}
              label={`silences narrated, ${skipped} left silent on purpose`}
              color={AMBER}
            />
            <StatCard
              value={String(m.overruns)}
              label={
                m.overruns === 0
                  ? "descriptions that ran over their silence"
                  : "descriptions that ran over their silence, spoken across the lecturer"
              }
              color={m.overruns === 0 ? INK : RED}
            />
            <StatCard
              value={`${covAfter} of ${covTotal}`}
              before={`${covBefore} of ${covTotal}`}
              label="visual facts a listener can recover from audio alone, before and after"
              color={GREEN}
            />
          </div>
        </div>

        {showcase && (
          <div style={{ marginTop: 38, paddingTop: 30, borderTop: "1px solid #16161a" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: cols,
                gap: 26,
                alignItems: "start",
              }}
            >
              <div>
                <div
                  style={{
                    fontFamily: "'IBM Plex Mono',monospace",
                    fontSize: 10.5,
                    letterSpacing: "0.14em",
                    color: AMBER,
                    marginBottom: 8,
                  }}
                >
                  THE REWRITE LOOP · {showcase.gapId.toUpperCase()}, THIS RUN
                </div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 600,
                    letterSpacing: "-0.025em",
                    maxWidth: "24em",
                    textWrap: "balance",
                  }}
                >
                  A description that runs past the silence is not a description, so it
                  rewrites until it fits.
                </div>
                <div
                  style={{
                    fontSize: 13.5,
                    color: "#8d8a85",
                    marginTop: 10,
                    maxWidth: "46em",
                  }}
                >
                  The gap is {showcase.availableSeconds.toFixed(1)} seconds. Every
                  duration below is measured from the synthesised speech, not estimated
                  from the word count.
                </div>

                <div style={{ marginTop: 16 }}>
                  {showcase.attempts.map((a) => (
                    <div
                      key={a.n}
                      style={{
                        display: "flex",
                        gap: 14,
                        padding: "13px 0",
                        borderTop: "1px solid #16161a",
                      }}
                    >
                      <div
                        style={{
                          fontFamily: "'IBM Plex Mono',monospace",
                          fontSize: 11,
                          color: "#5f5c58",
                          flex: "none",
                          width: 20,
                          paddingTop: 2,
                        }}
                      >
                        {a.n}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontSize: 14.5,
                            lineHeight: 1.45,
                            color: a.fits ? INK : "#6d6a66",
                            textDecoration: a.fits ? "none" : "line-through",
                          }}
                        >
                          {a.text}
                        </div>
                        <div
                          style={{
                            display: "flex",
                            gap: 14,
                            marginTop: 7,
                            fontFamily: "'IBM Plex Mono',monospace",
                            fontSize: 10.5,
                            color: "#6d6a66",
                          }}
                        >
                          <span>{a.words}w</span>
                          <span>{a.durationSeconds.toFixed(2)}s</span>
                          <span style={{ color: a.fits ? GREEN : RED }}>
                            {a.fits
                              ? "FITS"
                              : `OVER BY ${(a.durationSeconds - a.targetSeconds).toFixed(1)}s`}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
                      color: GREEN,
                      marginBottom: 11,
                    }}
                  >
                    COVERAGE CHECK · AUDIO ONLY
                  </div>
                  {project.coverage.facts.map((f, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        gap: 9,
                        padding: "5px 0",
                        fontSize: 12.5,
                        color: f.recovered ? "#c9c5be" : "#6d6a66",
                        lineHeight: 1.4,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "'IBM Plex Mono',monospace",
                          color: f.recovered ? GREEN : RED,
                        }}
                      >
                        {f.recovered ? "✓" : "✕"}
                      </span>
                      {f.text}
                    </div>
                  ))}
                  <div
                    style={{
                      fontSize: 12,
                      color: "#75726d",
                      marginTop: 12,
                      paddingTop: 11,
                      borderTop: "1px solid #17171a",
                      lineHeight: 1.45,
                    }}
                  >
                    A second model listens with no video and lists what it can tell. It
                    did not write the descriptions it is grading.
                  </div>
                </div>

                <LeftSilent project={project} />

                {actions}
              </div>
            </div>
          </div>
        )}

        <div
          style={{
            marginTop: 34,
            border: "1px solid #1a1a1d",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: wide ? "repeat(4,minmax(0,1fr))" : "repeat(2,minmax(0,1fr))",
              gap: 1,
              background: "#16161a",
            }}
          >
            {[
              {
                label: "CANONICAL HASH",
                value: project.provenance.canonicalHash
                  ? `${project.provenance.canonicalHash.slice(0, 6)}…${project.provenance.canonicalHash.slice(-4)}`
                  : "—",
                size: 14,
                color: INK,
                note: "sha256 over the run and every model call",
              },
              {
                label: "STEPS RECORDED",
                value: String(project.provenance.steps ?? "—"),
                size: 22,
                color: INK,
                note: "one per provider call, in pipeline order",
              },
              {
                label: "BUCKET",
                value: `b2://${project.provenance.bucket ?? "—"}`,
                size: 12,
                color: "#c9c5be",
                // the mode is stated once, by the LOCKED UNTIL card. saying it
                // here too would let the two cards contradict each other.
                note: "Object Lock on, write once",
              },
              {
                label: "LOCKED UNTIL",
                value: project.provenance.retainUntil
                  ? project.provenance.retainUntil.slice(0, 10)
                  : "—",
                size: 16,
                color: GREEN,
                note:
                  project.provenance.lockMode === "COMPLIANCE"
                    ? "compliance mode, not removable by anyone"
                    : "governance mode, removable with a bypass key",
              },
            ].map((p) => (
              <div key={p.label} style={{ background: "#0d0d0f", padding: "17px 18px" }}>
                <div
                  style={{
                    fontFamily: "'IBM Plex Mono',monospace",
                    fontSize: 9.5,
                    letterSpacing: "0.1em",
                    color: "#7d7a75",
                  }}
                >
                  {p.label}
                </div>
                <div
                  style={{
                    fontFamily: "'IBM Plex Mono',monospace",
                    fontSize: p.size,
                    fontWeight: 600,
                    color: p.color,
                    marginTop: 8,
                    wordBreak: "break-all",
                    lineHeight: 1.3,
                  }}
                >
                  {p.value}
                </div>
                <div
                  style={{ fontSize: 11, color: "#6d6a66", marginTop: 6, lineHeight: 1.4 }}
                >
                  {p.note}
                </div>
              </div>
            ))}
          </div>
          <div
            style={{
              padding: "14px 18px",
              background: "#0b0b0d",
              borderTop: "1px solid #16161a",
              fontSize: 12.5,
              color: "#8d8a85",
              lineHeight: 1.5,
            }}
          >
            Every description traces back to the model call that produced it: prompt,
            parameters, voice, timing. Written once to a bucket with Object Lock on.{" "}
            {project.provenance.lockMode === "COMPLIANCE"
              ? "In compliance mode, so it cannot be deleted or altered before the retention date by anyone, including us."
              : "In governance mode, so it is immutable to ordinary access, though a key holding the bypass permission could still remove it."}
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 20,
            marginTop: 26,
            paddingTop: 20,
            borderTop: "1px solid #16161a",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", gap: 20, fontSize: 12.5 }}>
            <a href="https://github.com/rushibhosalepro/interlude" style={{ color: AMBER }}>
              Repo
            </a>
            <a href={project.vttUrl} style={{ color: AMBER }}>
              descriptions.vtt
            </a>
          </div>
          <div style={{ fontSize: 11, color: "#5c5a56" }}>
            Descriptions are generated. Durations measured from the synthesised speech.
          </div>
        </div>
      </div>
    </div>
  );
}

export function useProjects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const { data } = await axios.get(`${API_URL}/api/projects`, {
          params: key ? { refresh: true } : {},
        });
        // Everything streams from B2 via the presigned URLs the API returns.
        if (!cancelled) setProjects(data.projects);
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [key]);

  return { projects, error, refresh: () => setKey((n) => n + 1) };
}
