import { useState } from "react";

import "./index.css";
import { DemoGallery } from "@/components/demo-gallery";
import { FileUploader } from "@/components/file-uploader";
import { JobTimeline } from "@/components/job-timeline";
import { SampleClips } from "@/components/sample-clips";
import { Toaster } from "@/components/ui/sonner";

export function App() {
  // bumping this after an upload finishes pulls the new run into the gallery
  const [completed, setCompleted] = useState(0);
  // a sample run has no upload, so its timeline lives here rather than in the uploader
  const [sampleJobId, setSampleJobId] = useState<string | null>(null);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-lg flex-col items-center gap-8 p-6 py-12">
      <header className="flex w-full flex-col gap-1">
        <h1 className="text-xl font-semibold">Interlude</h1>
        <p className="text-muted-foreground text-sm">
          Audio description for video libraries that already have captions. It finds
          the silences, decides which ones hide something visual, and narrates them.
        </p>
      </header>

      <FileUploader onFinished={() => setCompleted((n) => n + 1)} />

      <SampleClips onQueued={setSampleJobId} />

      {sampleJobId && (
        <section className="w-full rounded-lg border p-4">
          <JobTimeline
            jobId={sampleJobId}
            onFinished={() => setCompleted((n) => n + 1)}
          />
        </section>
      )}

      <section className="flex w-full flex-col gap-3">
        <h2 className="text-sm font-medium">Finished examples</h2>
        <DemoGallery refreshKey={completed} />
      </section>

      <Toaster position="bottom-right" richColors />
    </main>
  );
}

export default App;
