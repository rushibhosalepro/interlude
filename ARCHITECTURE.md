# Interlude

Audio description for video libraries that already have captions.

> You captioned 4,000 lectures. Your blind students still can't follow one of them. Interlude narrates what happens in the silences.

Built for the Backblaze Generative Media Hackathon. Deadline 4 Aug 2026, 2:30am IST.

---

## What it does

Point it at video you already own. It finds the silences between dialogue, decides which of those silences actually hide something visually important, writes narration that fits the gap, and returns a described audio track hosted on B2 plus an immutable provenance record.

It does not hand you files. It gives you a URL your existing player points at.

**Why captions aren't enough:** captions serve deaf viewers. They do nothing for blind viewers. When a lecturer points at the board and says "as you can see here," a captioned video still conveys nothing.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | React + Bun + shadcn |
| Backend | FastAPI, Python 3.13, uv |
| Storage | Backblaze B2 (S3-compatible, via boto3 and genblaze-s3) |
| Generation | Genblaze 0.4.4 |
| Media | ffmpeg / ffprobe as subprocesses |
| Index | Postgres, deferred until listing requires it |
| Deploy | Railway (container, needs ffmpeg in the image) |

---

## End-to-end flow

1. Browser requests a presigned PUT from `POST /api/presigned_url`
2. Browser uploads **directly to B2**. The video never passes through the server.
3. Client calls the completion endpoint, which verifies the object landed and queues a job
4. Worker pulls the source (or streams it from the presigned URL for short clips)
5. Pipeline runs, checkpointing every stage to B2
6. Each stage emits an SSE event driving the live timeline UI
7. Final track written to B2, provenance manifest written to the compliance bucket
8. Browser plays the finished track back from B2 by presigned GET. The server is not in that path.

---

## Storage layout

Two buckets, because two policies conflict: "delete this after 30 days" and "this can never change."

### `interlude-media`

Private, SSE-B2 encryption on, no Object Lock.

```
projects/{projectId}/source/{videoId}.mp4
projects/{projectId}/analysis/{videoId}/transcript.json
projects/{projectId}/analysis/{videoId}/gaps.json
projects/{projectId}/analysis/{videoId}/decisions.json
projects/{projectId}/analysis/{videoId}/coverage.json
projects/{projectId}/analysis/{videoId}/frames/{gapId}-{n}.jpg
projects/{projectId}/attempts/{gapId}/{n}/text.json
projects/{projectId}/attempts/{gapId}/{n}/audio.mp3
projects/{projectId}/final/{videoId}/descriptions.vtt
projects/{projectId}/final/{videoId}/described-audio.m4a
jobs/{jobId}/state.json
```

Lifecycle: expire `attempts/` after 30 days, keep `final/` and `analysis/` indefinitely.

**Note:** Genblaze's `ObjectStorageSink` writes generated assets using its own key strategy. The layout above applies to artifacts Genblaze does not produce: the uploaded source, ffmpeg keyframes, and the muxed output. Let the SDK own its own keys rather than fighting it.

### `interlude-compliance`

Private, SSE-B2 on, **Object Lock enabled**. One small file per completed video.

```
compliance/{projectId}/{videoId}/{iso8601}.json
```

This holds the Genblaze `Manifest`, not hand-rolled JSON. See below.

### B2 features and why each is present

| Feature | Reason |
|---|---|
| Presigned PUT | uploads bypass the server, no request timeouts or buffered gigabytes |
| Presigned GET | the customer's player fetches from B2 directly, so storage is the product surface |
| Object Lock | a compliance record that can be edited is worthless |
| Versioning | description revisions with lineage back to the attempt that produced them |
| Lifecycle rules | expire failed attempts, keep finals |
| Scoped app keys | one key per bucket, prefix-restricted. The master key never touches the app. |
| SSE-B2 encryption | free, transparent, zero code |

**B2 has no hot/cold tiers.** There is no Glacier equivalent and no storage classes. Do not claim tiering. The cost story is lifecycle expiry plus content-addressable dedup, and both are true.

---

## Genblaze usage

`pip install genblaze` (0.4.4) pulls `genblaze-core` and `genblaze-s3`. Repo: `github.com/backblaze-labs/genblaze`.

### Storage binding

```python
from genblaze_core import ObjectStorageSink, KeyStrategy
from genblaze_s3 import S3StorageBackend

storage = ObjectStorageSink(
    S3StorageBackend.for_backblaze("interlude-media"),
    key_strategy=KeyStrategy.CONTENT_ADDRESSABLE,
)
```

`CONTENT_ADDRESSABLE` deduplicates by hash. Identical description text produces an identical TTS render which lands on the same key, so re-runs of an edited video pay nothing for unchanged scenes. That is the cache story, and it is a documented SDK feature rather than something invented.

### Provenance

Every run produces a `Manifest`: a canonical, hash-verified document capturing provider, model, prompt, parameters and timestamps, with a SHA-256 and a `verify()` method. It embeds into mp4, mp3, wav, png.

**The manifest is the compliance artifact.** Do not hand-roll an audit record. Persist the manifest to the Object Lock bucket and you have provenance using the sponsor's headline feature for its actual purpose.

`EmbedPolicy` controls what the manifest exposes, which matters since prompts may contain customer content.

### Lineage

`Run` carries `run_id`, `tenant_id` and `parent_run_id`. The fit loop's retry chain maps directly onto `parent_run_id`: attempt 2 points at attempt 1. The loop's history is first-class SDK data, not bolted-on metadata.

### Provider roles

Five roles, deliberately not all one vendor.

| Role | Package |
|---|---|
| Speech-to-text | **no adapter listed.** Verify. If absent, call Whisper directly and say so in the write-up. |
| Vision (facts + fill/skip) | `genblaze-openai` or `genblaze-google` |
| Description writing | `genblaze-openai` |
| Coverage checker | `genblaze-google` — **must differ from the writer** |
| TTS | `genblaze-elevenlabs` |

Grading your own output with the model that wrote it is worthless and a judge will notice.

`ModelRegistry` carries pricing, so cost per run comes free. `Tracer` / `OTelTracer` give per-stage timing.

### Env var conflict

Genblaze reads `B2_KEY_ID`, `B2_APP_KEY`, `B2_BUCKET`, `B2_REGION`.

The existing `.env` uses `BACKBLAZE_APPLICATION_KEY_ID`, `BACKBLAZE_APPLICATION_KEY`, etc. Either set both sets or map them at startup. This will bite on the first Genblaze call otherwise.

---

## Pipeline

| Stage | Input | Output | Provider |
|---|---|---|---|
| Transcribe | source | word-level timestamps | STT |
| Find gaps | transcript | silences >= 1.5s | deterministic |
| Keyframes | video + gaps | frames at gap midpoints and scene changes | ffmpeg |
| Analyse | frames + surrounding dialogue | essential visual facts | vision |
| **Filter** | facts per gap | fill or leave silent | vision, same call |
| Write | facts + word budget | candidate description | text |
| Narrate | description | audio, measured | TTS |
| Check | audio-only text + facts | coverage score | second text provider |
| Mux | original + descriptions | described audio, ducked | ffmpeg |
| Publish | tracks + manifest | presigned URLs, audit record | B2 |

---

## The loops

This is what separates Interlude from a pipeline. Build these before any UI.

### Stage 0: the filter

Most silences should stay silent. A 4-second gap showing two people sitting where they already were does not need "they are still sitting at the table." Over-narration is the classic failure of bad audio description.

The vision step answers two questions in order: does anything visually essential happen here that the dialogue does not already convey, and if so what exactly. Expect most gaps to come back "skip."

### Loop 1: fit (hard, deterministic)

Narration must fit the silence. If the gap is 3.2s and the render is 4.1s, it fails. No judge model involved.

```
for each gap to fill:
    budget_words = gap_seconds * 2.6
    for attempt in 1..4:
        text  = write_description(facts, budget_words)
        audio = tts(text)
        dur   = ffprobe_duration(audio)
        if dur <= gap_seconds - 0.2:
            commit(text, audio); break
        budget_words *= (gap_seconds - 0.2) / dur
    else:
        try speed 1.0-1.15x
        else drop to the single most essential clause
```

Calibrate 2.6 words/second against the actual voice you pick rather than assuming it.

### Loop 2: comprehension

Good audio description means a listener can reconstruct the scene from audio alone. Test exactly that.

```
essential_facts = vision_model(frames)
audio_only_text = interleave(dialogue, committed_descriptions)
recovered       = checker_model(audio_only_text, essential_facts)
coverage        = len(recovered) / len(essential_facts)

if coverage < 0.85:
    regenerate the gaps covering the missing facts, re-run
```

---

## Worker state

Two kinds, and separating them is what lets Postgres wait.

### Derived state: B2 is the truth

Most of what the worker needs is answerable by "does this artifact exist yet?"

| Stage | Complete when this exists |
|---|---|
| Transcribed | `analysis/{videoId}/transcript.json` |
| Gaps found | `analysis/{videoId}/gaps.json` |
| Keyframes | `analysis/{videoId}/frames/` |
| Analysed | `analysis/{videoId}/decisions.json` |
| Described | per gap: a committed attempt under `attempts/{gapId}/` |
| Coverage checked | `analysis/{videoId}/coverage.json` |
| Muxed | `final/{videoId}/described-audio.m4a` |
| Published | manifest in the compliance bucket |

On startup the worker walks that list and resumes at the first gap. No database required. **This is the crash-resume story.** State was never in a database, it is in the artifacts.

The description stage is per-gap rather than global, so a crash after gap 12 of 40 resumes at 13 having paid for zero repeated TTS.

### Live state: memory is fine

Current gap, attempt number, percentage, the metrics ticking up for the timeline. This is a view, not truth. Hold it in a dict keyed by job id and push it over SSE. If the process dies the UI reconnects and the worker rebuilds the view from B2.

### The optimization

Pure derivation means many `head_object` calls. Write `jobs/{jobId}/state.json` after every stage:

```json
{
  "jobId": "...",
  "sourceKey": "projects/.../source/abc.mp4",
  "stage": "describing",
  "gaps": { "total": 40, "toFill": 13, "committed": 12 },
  "metrics": { "firstPassFit": 0.62, "coverageBefore": 0.41 }
}
```

A cache over derived state, not a second source of truth. Trust it on resume, fall back to artifact checks if missing or stale. It also holds the four published numbers, so the UI and the write-up both read from it.

### When Postgres earns its place

Only for questions B2 cannot answer cheaply: list every job for a user, sort by date, filter by status. Add it when listing gets annoying. The design does not change, because Postgres is an index over the same B2 truth.

### Process model

One worker, one job at a time. No queue.

ffmpeg calls are blocking. Use `asyncio.create_subprocess_exec` or an executor. Blocking the event loop freezes the SSE stream, which is precisely when a judge is watching.

---

## Metrics

Four numbers, measured and published honestly including the unflattering ones.

| Metric | Meaning |
|---|---|
| **Fit rate** | fraction of descriptions fitting their gap, first pass vs final |
| **Fact coverage** | essential visual facts recoverable from audio alone, before vs after |
| **Description density** | fraction of eligible gaps deliberately filled. Restraint is correct behaviour. |
| **Cache hit rate** | unchanged segments reusing committed descriptions on re-run |

The 1 Aug OpenCourseWare run is where these come from. See `../interlude-build-spec.md`.

---

## Outputs

Interlude does not re-render the video.

- **`described-audio.m4a`** — the real deliverable. Original audio with narration mixed into the gaps, ducked. This is how broadcast audio description works.
- **`descriptions.vtt`** — machine-readable, the auditable record. Browser support for `<track kind="descriptions">` is weak and most players will not speak it, so never make this the demo output.
- **Full MP4 with described audio** — optional, opt-in, doubles storage per video.

---

## Environment

```
BACKBLAZE_APPLICATION_KEY_ID=
BACKBLAZE_APPLICATION_KEY=
BACKBLAZE_ENDPOINT_URL=      # host only, no bucket path
BACKBLAZE_REGION=
BACKBLAZE_MEDIA_BUCKET=interlude-media
BACKBLAZE_COMPLIANCE_BUCKET=interlude-compliance

B2_KEY_ID=                   # Genblaze reads these names
B2_APP_KEY=
B2_BUCKET=interlude-media
B2_REGION=
```

Provider keys per the Genblaze adapters in use.

---

## CORS

Two separate systems. Debug them separately: a blocked call to `/api/presigned_url` is FastAPI, a blocked PUT to `backblazeb2.com` is the bucket rule.

**B2 bucket** (Bucket Settings → CORS Rules):

```json
[
  {
    "corsRuleName": "interludeDev",
    "allowedOrigins": ["http://localhost:3000"],
    "allowedOperations": ["s3_put", "s3_get", "s3_head"],
    "allowedHeaders": ["*"],
    "exposeHeaders": ["etag"],
    "maxAgeSeconds": 3600
  }
]
```

Origins must match exactly including scheme and port, no trailing slash. `"*"` cannot be mixed with specific origins.

**FastAPI:** `CORSMiddleware` in `main.py` before the router include.

---

## Status

**Done**
- Two B2 buckets created, Object Lock on compliance
- `POST /api/presigned_url` with content-type allowlist and server-controlled keys

**Next**
- CORS on bucket and API
- Completion endpoint: verify the object landed, queue the job
- Transcribe, gap detection, keyframes
- Loop 1, then Loop 2
- Mux, publish, manifest to Object Lock
- Timeline UI over SSE
- OpenCourseWare run

**Deferred**
- Postgres
- Dockerfile
- Size limits, env validation

---

## Demo requirements

Non-negotiable, from the winner analysis in `../winners-analysis.md`.

- No login, or credentials at the top of the description
- Pre-seeded finished examples so no judge lands on an empty screen
- One-click sample videos. Requiring judges to supply input is what sank a previous submission.
- Live processing capped at 60 to 90 second clips
- The loop must be **visible**: failed attempts struck through with their numbers, retries in green, coverage climbing
- A recorded fallback run in case a provider is down during judging
- Restart the worker mid-job on camera to show it resume
