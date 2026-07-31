import { useEffect, useRef, useState } from "react";
import { Check, CircleDashed, Loader2, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

const API_URL = process.env.BUN_PUBLIC_API_URL;

const STAGES = [
  { id: "transcribe", label: "Transcribe", hint: "word level timestamps" },
  { id: "gaps", label: "Find gaps", hint: "silences worth describing" },
  { id: "analyse", label: "Analyse", hint: "fill or leave silent" },
  { id: "describe", label: "Fit loop", hint: "write, render, measure, retry" },
  { id: "coverage", label: "Coverage loop", hint: "audio-only recheck, second provider" },
  { id: "mux", label: "Mux", hint: "described audio track" },
  { id: "publish", label: "Publish", hint: "manifest to the object lock bucket" },
] as const;

type Attempt = {
  attempt: number;
  text: string;
  words: number;
  durationSeconds: number;
  targetSeconds: number;
  speed: number;
  fits: boolean;
};

type Gap = {
  gapId: string;
  available: number;
  attempts: Attempt[];
  status?: "committed" | "abandoned";
};

export function JobTimeline({
  jobId,
  onFinished,
}: {
  jobId: string;
  onFinished?: () => void;
}) {
  const [status, setStatus] = useState("queued");
  const [stage, setStage] = useState<string | null>(null);
  const [completed, setCompleted] = useState<string[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(`${API_URL}/api/jobs/${jobId}/events`);
    sourceRef.current = source;

    source.addEventListener("state", (e) => {
      const payload = JSON.parse((e as MessageEvent).data);
      // tolerate both shapes: the envelope, and a bare job from an older server
      const state = payload?.state ?? payload;
      if (!state?.status) return;

      setStatus(state.status);
      setStage(state.stage);
      setCompleted(state.completedStages ?? []);
      if (state.error) setError(state.error);
    });

    source.addEventListener("gap-start", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setGaps((prev) =>
        prev.some((g) => g.gapId === d.gapId)
          ? prev
          : [...prev, { gapId: d.gapId, available: d.available, attempts: [] }],
      );
    });

    source.addEventListener("attempt", (e) => {
      const d = JSON.parse((e as MessageEvent).data) as Attempt & { gapId: string };
      setGaps((prev) =>
        prev.map((g) =>
          g.gapId === d.gapId
            ? {
                ...g,
                // the worker can resend on reconnect, so key on attempt number
                attempts: [...g.attempts.filter((a) => a.attempt !== d.attempt), d].sort(
                  (a, b) => a.attempt - b.attempt,
                ),
              }
            : g,
        ),
      );
    });

    source.addEventListener("gap-done", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setGaps((prev) =>
        prev.map((g) => (g.gapId === d.gapId ? { ...g, status: d.status } : g)),
      );
    });

    source.addEventListener("end", (e) => {
      source.close();
      if (JSON.parse((e as MessageEvent).data).status === "done") onFinished?.();
    });

    // the browser reconnects automatically on error, which is what we want while
    // the worker restarts. only surface it if the job itself failed.
    return () => source.close();
  }, [jobId]);

  const stageState = (id: string) => {
    if (completed.includes(id)) return "done";
    if (stage === id) return "running";
    if (status === "failed") return "stopped";
    return "pending";
  };

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col gap-1">
        {STAGES.map((s) => {
          const state = stageState(s.id);
          return (
            <li key={s.id} className="flex flex-col gap-2">
              <div
                className={cn(
                  "flex items-center gap-3 rounded-md px-2 py-1.5 text-sm transition-colors",
                  state === "running" && "bg-accent",
                  state === "pending" && "opacity-45",
                )}
              >
                {state === "done" ? (
                  <Check className="size-4 shrink-0 text-emerald-600" />
                ) : state === "running" ? (
                  <Loader2 className="text-primary size-4 shrink-0 animate-spin" />
                ) : (
                  <CircleDashed className="text-muted-foreground size-4 shrink-0" />
                )}
                <span className="font-medium">{s.label}</span>
                <span className="text-muted-foreground text-xs">{s.hint}</span>
              </div>

              {/* the fit loop is the part worth watching, so it expands inline */}
              {s.id === "describe" && gaps.length > 0 && (
                <div className="ml-7 flex flex-col gap-3 border-l pl-4">
                  {gaps.map((gap) => (
                    <div key={gap.gapId} className="flex flex-col gap-1">
                      <p className="text-muted-foreground font-mono text-xs">
                        {gap.gapId} · {gap.available.toFixed(2)}s of silence
                      </p>

                      {gap.attempts.map((a) => (
                        <div
                          key={a.attempt}
                          className="flex items-baseline gap-2 text-xs"
                        >
                          <span
                            className={cn(
                              "font-mono tabular-nums",
                              a.fits ? "text-emerald-600" : "text-destructive",
                            )}
                          >
                            #{a.attempt}
                          </span>
                          <span
                            className={cn(
                              "flex-1",
                              !a.fits && "text-muted-foreground line-through",
                            )}
                          >
                            {a.text}
                          </span>
                          <span
                            className={cn(
                              "font-mono tabular-nums whitespace-nowrap",
                              a.fits ? "text-emerald-600" : "text-destructive",
                            )}
                          >
                            {a.durationSeconds.toFixed(2)}s
                            {a.speed !== 1 && ` @${a.speed}x`}
                          </span>
                        </div>
                      ))}

                      {gap.status === "abandoned" && (
                        <p className="text-muted-foreground text-xs italic">
                          no attempt fit, left silent
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {error && (
        <p className="text-destructive flex items-start gap-2 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          {error}
        </p>
      )}
    </div>
  );
}
