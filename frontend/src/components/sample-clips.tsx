import { useEffect, useState } from "react";
import axios from "axios";
import { Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";

const API_URL = process.env.BUN_PUBLIC_API_URL;

type Sample = {
  sampleId: string;
  title: string;
  seconds: number | null;
  sizeBytes: number;
};

export function SampleClips({ onQueued }: { onQueued?: (jobId: string) => void }) {
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    axios
      .get(`${API_URL}/api/samples`)
      .then(({ data }) => !cancelled && setSamples(data.samples))
      .catch(() => !cancelled && setSamples([]));
    return () => {
      cancelled = true;
    };
  }, []);

  if (!samples?.length) return null;

  const run = async (sampleId: string) => {
    setStarting(sampleId);
    try {
      const { data } = await axios.post(`${API_URL}/api/samples/${sampleId}/run`);
      onQueued?.(data.jobId);
    } finally {
      setStarting(null);
    }
  };

  return (
    <div className="flex w-full flex-col gap-2">
      <p className="text-muted-foreground text-xs">
        Or run one of these without uploading anything.
      </p>
      <div className="flex flex-wrap gap-2">
        {samples.map((sample) => (
          <Button
            key={sample.sampleId}
            variant="outline"
            size="sm"
            className="cursor-pointer"
            disabled={starting !== null}
            onClick={() => run(sample.sampleId)}
          >
            {starting === sample.sampleId ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Play className="size-3.5" />
            )}
            {sample.title}
            {sample.seconds && (
              <span className="text-muted-foreground font-mono text-[11px]">
                {Math.round(sample.seconds)}s
              </span>
            )}
          </Button>
        ))}
      </div>
    </div>
  );
}
