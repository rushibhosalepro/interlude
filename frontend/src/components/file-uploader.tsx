import { useRef, useState } from "react";
import axios from "axios";
import { CheckCircle2, FileVideo, Loader2, UploadCloud, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { JobTimeline } from "@/components/job-timeline";
import { cn } from "@/lib/utils";

const API_URL = process.env.BUN_PUBLIC_API_URL;

// mirrors ALLOWED_VIDEO_TYPES on the backend
const ACCEPT =
  "video/mp4,video/webm,video/quicktime,video/x-matroska,.mp4,.webm,.mov,.mkv";

type Status = "idle" | "uploading" | "done" | "error";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

export function FileUploader({ onFinished }: { onFinished?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const busy = status === "uploading";

  const selectFile = (next: File | null) => {
    setFile(next);
    setJobId(null);
    setStatus("idle");
    setProgress(0);
    setError(null);
  };

  const reset = () => {
    selectFile(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    selectFile(e.dataTransfer.files?.[0] ?? null);
  };

  const upload = async () => {
    if (!file) return;

    setStatus("uploading");
    setProgress(0);
    setError(null);

    try {
      // 1. ask our api for a scoped, short lived upload url
      const { data: presign } = await axios.post(
        `${API_URL}/api/presigned_url`,
        {
          filename: file.name,
          content_type: file.type,
        },
      );

      // 2. send the bytes straight to storage, never through our api.
      // the header must match what the url was signed with, not file.type.
      await axios.put(presign.presignedUrl, file, {
        headers: { "Content-Type": presign.contentType },
        onUploadProgress: (event) => {
          if (!event.total) return;
          setProgress(Math.round((event.loaded / event.total) * 100));
        },
      });

      // 3. let the api confirm it landed, enforce the size cap and queue the job
      const { data: job } = await axios.post(`${API_URL}/api/uploads/complete`, {
        key: presign.key,
      });

      setJobId(job.jobId);
      setStatus("done");
      toast.success("Upload complete", { description: file.name });
    } catch (err) {
      let message = "Something went wrong";

      if (axios.isAxiosError(err)) {
        // a blocked cross origin PUT never gets a response, so err.response is
        // undefined and the message is a bare "Network Error"
        message = err.response
          ? (err.response.data?.detail ?? err.message)
          : "Could not reach storage. Check the bucket's CORS rules.";
      }

      setStatus("error");
      setError(message);
      toast.error("Upload failed", { description: message });
    }
  };

  return (
    <Card className="w-full max-w-lg">
      <CardHeader>
        <CardTitle>Upload a video</CardTitle>
        <CardDescription>MP4, WebM, MOV or MKV, up to 2 GB.</CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div
          role="button"
          tabIndex={0}
          onClick={() => !busy && inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
          }}
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center transition-colors outline-none",
            "focus-visible:ring-ring/50 focus-visible:ring-[3px]",
            dragging
              ? "border-primary bg-accent"
              : "border-input hover:bg-accent/50",
            busy && "pointer-events-none opacity-60",
          )}
        >
          <UploadCloud
            className="text-muted-foreground size-8"
            strokeWidth={1.5}
          />
          <p className="text-sm font-medium">
            Drop your video here, or{" "}
            <span className="underline underline-offset-4 cursor-pointer">
              browse
            </span>
          </p>
          <p className="text-muted-foreground text-xs">
            Your file uploads directly to storage
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
        />

        {file && (
          <div className="flex items-center gap-3 rounded-lg border p-3">
            <FileVideo
              className="text-muted-foreground size-5 shrink-0"
              strokeWidth={1.5}
            />

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-muted-foreground text-xs">
                {formatBytes(file.size)}
                {status === "uploading" && ` · ${progress}%`}
              </p>

              {status === "uploading" && (
                <div className="bg-muted mt-2 h-1.5 w-full overflow-hidden rounded-full">
                  <div
                    className="bg-primary h-full rounded-full transition-[width] duration-200"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              )}
            </div>

            {status === "done" ? (
              <CheckCircle2 className="size-5 shrink-0 text-emerald-600" />
            ) : (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-7 shrink-0 cursor-pointer"
                onClick={reset}
                disabled={busy}
                aria-label="Remove file"
              >
                <X className="size-4" />
              </Button>
            )}
          </div>
        )}

        {jobId && (
          <div className="border-t pt-4">
            <JobTimeline jobId={jobId} onFinished={onFinished} />
          </div>
        )}

        {error && <p className="text-destructive text-sm">{error}</p>}

        {status === "done" ? (
          <Button variant="outline" onClick={reset} className="cursor-pointer">
            Upload another
          </Button>
        ) : (
          <Button
            onClick={upload}
            className="cursor-pointer"
            disabled={!file || busy}
          >
            {busy && <Loader2 className="size-4 animate-spin" />}
            {busy ? "Uploading" : "Upload"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
