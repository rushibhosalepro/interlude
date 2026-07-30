import { useEffect, useState } from "react";
import axios from "axios";
import { AudioLines, Download, Loader2, ShieldCheck } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

const API_URL = process.env.BUN_PUBLIC_API_URL;

type Description = {
  gapId: string;
  text: string;
  startsAt: number;
  durationSeconds: number;
  availableSeconds: number;
  attempts: number;
  firstPass: boolean;
};

type Project = {
  projectId: string;
  videoId: string;
  durationSeconds: number | null;
  videoUrl: string;
  audioUrl: string;
  vttUrl: string;
  metrics: {
    gapsFound: number;
    toFill: number;
    toSkip: number;
    density: number;
    firstPassFitRate: number;
    finalFitRate: number;
    totalAttempts: number;
  };
  descriptions: Description[];
  provenance: {
    canonicalHash: string | null;
    steps: number | null;
    retainUntil: string | null;
  };
};

function clock(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="font-mono text-sm tabular-nums">{value}</span>
      <span className="text-muted-foreground text-[11px]">{label}</span>
    </div>
  );
}

export function DemoGallery({ refreshKey = 0 }: { refreshKey?: number }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    axios
      .get(`${API_URL}/api/projects`, { params: refreshKey ? { refresh: true } : {} })
      .then(({ data }) => !cancelled && setProjects(data.projects))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (error) {
    return <p className="text-destructive text-sm">Could not load examples: {error}</p>;
  }

  if (projects === null) {
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin" />
        Loading examples
      </p>
    );
  }

  if (projects.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No finished examples yet. Upload a video to make one.
      </p>
    );
  }

  return (
    <div className="flex w-full max-w-lg flex-col gap-4">
      {projects.map((project) => {
        const m = project.metrics;
        return (
          <Card key={`${project.projectId}/${project.videoId}`}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <AudioLines className="size-4" strokeWidth={1.75} />
                Described audio
                {project.durationSeconds && (
                  <span className="text-muted-foreground font-mono text-xs font-normal">
                    {clock(project.durationSeconds)}
                  </span>
                )}
              </CardTitle>
              <CardDescription>
                Original soundtrack with narration mixed into the silences.
              </CardDescription>
            </CardHeader>

            <CardContent className="flex flex-col gap-4">
              {/* the payoff: the original video with the described track on it */}
              <video
                controls
                preload="metadata"
                src={project.videoUrl}
                className="w-full rounded-md border bg-black"
              >
                Your browser does not support video playback.
              </video>

              <a
                href={project.videoUrl}
                download
                className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 self-start text-xs underline underline-offset-4"
              >
                <Download className="size-3.5" />
                Download described video
              </a>

              <div className="grid grid-cols-4 gap-3 border-y py-3">
                <Stat label="gaps found" value={String(m.gapsFound)} />
                <Stat
                  label="described"
                  value={`${m.toFill}/${m.gapsFound}`}
                />
                <Stat
                  label="fit rate"
                  value={`${Math.round(m.finalFitRate * 100)}%`}
                />
                <Stat label="attempts" value={String(m.totalAttempts)} />
              </div>

              <ul className="flex flex-col gap-2">
                {project.descriptions.map((d) => (
                  <li key={d.gapId} className="flex flex-col gap-0.5">
                    <div className="flex items-baseline gap-2">
                      <span className="text-muted-foreground font-mono text-xs tabular-nums">
                        {clock(d.startsAt)}
                      </span>
                      <span className="text-sm">{d.text}</span>
                    </div>
                    <span className="text-muted-foreground pl-10 font-mono text-[11px] tabular-nums">
                      {d.durationSeconds.toFixed(2)}s into{" "}
                      {d.availableSeconds.toFixed(2)}s of silence
                      {" · "}
                      <span
                        className={cn(
                          d.firstPass ? "text-emerald-600" : "text-amber-600",
                        )}
                      >
                        {d.attempts} attempt{d.attempts === 1 ? "" : "s"}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>

              {project.provenance.canonicalHash && (
                <p className="text-muted-foreground flex items-start gap-2 border-t pt-3 text-[11px]">
                  <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    Provenance manifest locked in the compliance bucket,{" "}
                    {project.provenance.steps} steps.
                    <br />
                    <span className="font-mono break-all">
                      {project.provenance.canonicalHash.slice(0, 32)}…
                    </span>
                  </span>
                </p>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
