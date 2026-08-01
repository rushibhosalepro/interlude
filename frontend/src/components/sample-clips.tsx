import { useEffect, useState } from "react";
import axios from "axios";
import { Loader2, Play } from "lucide-react";

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
      <p style={{ fontSize: 12, color: "#8d8a85" }}>
        Or run one of these without uploading anything.
      </p>
      <div className="flex flex-col gap-2">
        {samples.map((sample) => {
          const busy = starting === sample.sampleId;
          return (
            <button
              key={sample.sampleId}
              disabled={starting !== null}
              onClick={() => run(sample.sampleId)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                width: "100%",
                textAlign: "left",
                padding: "9px 12px",
                borderRadius: 8,
                border: "1px solid #2c2c30",
                background: busy ? "#141310" : "#0d0d0f",
                color: "#e8e6e1",
                fontSize: 12.5,
                fontFamily: "'Space Grotesk',Helvetica,sans-serif",
                cursor: starting !== null ? "default" : "pointer",
                opacity: starting !== null && !busy ? 0.5 : 1,
              }}
            >
              {busy ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin" style={{ color: "#e8a94f" }} />
              ) : (
                <Play className="size-3.5 shrink-0" style={{ color: "#e8a94f" }} />
              )}
              <span style={{ flex: 1, minWidth: 0 }}>{sample.title}</span>
              {sample.seconds != null && (
                <span
                  style={{
                    fontFamily: "'IBM Plex Mono',monospace",
                    fontSize: 11,
                    color: "#8d8a85",
                  }}
                >
                  {Math.round(sample.seconds)}s
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
