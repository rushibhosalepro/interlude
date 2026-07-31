import { useState } from "react";

import "./index.css";
import { FileUploader } from "@/components/file-uploader";
import { JobTimeline } from "@/components/job-timeline";
import { JudgePage, useProjects } from "@/components/judge-page";
import { SampleClips } from "@/components/sample-clips";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  const { projects, error, refresh } = useProjects();
  // a run started from this page, whether uploaded or a sample
  const [jobId, setJobId] = useState<string | null>(null);

  // newest finished run is the one a judge should land on
  const featured = projects?.[projects.length - 1];

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
      <div style={{ fontSize: 12, color: "#75726d", marginTop: 5, lineHeight: 1.45 }}>
        Up to 90 seconds, MP4 or MOV, straight to Backblaze B2. No account, no email.
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
      <div style={{ width: "100%", maxWidth: 1180 }}>
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
          <JudgePage project={featured} actions={runPanel} />
        ) : (
          <div
            style={{
              background: "#0a0a0b",
              border: "1px solid #1a1a1d",
              borderRadius: 14,
              padding: 40,
              color: "#9a968f",
              fontFamily: "'Space Grotesk',Helvetica,sans-serif",
            }}
          >
            {error
              ? `Could not load examples: ${error}`
              : projects === null
                ? "Loading…"
                : "No finished runs yet."}
            <div style={{ marginTop: 20, maxWidth: 420 }}>{runPanel}</div>
          </div>
        )}
      </div>

      <Toaster position="bottom-right" richColors />
    </main>
  );
}

export default App;
