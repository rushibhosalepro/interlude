# How it works, in plain language

A companion to [ARCHITECTURE.md](ARCHITECTURE.md). That file is the spec. This
one explains how the thing actually behaves, and what is left.

Last updated 30 Jul 2026, after running a clip end to end.

---

## The short version

Upload a video. A few minutes later you get an audio track where a narrator
describes what happens in the silences, plus a tamper-evident record of exactly
which model produced each line.

Everything below already works.

---

## What happens when you upload

**1. The browser uploads straight to Backblaze.** Your server never touches the
video. It hands out a short-lived signed URL and steps out of the way, so there
are no request timeouts and no gigabytes buffered in memory.

**2. The API queues a job and replies immediately.** About 50 milliseconds. The
real work happens behind the response.

**3. A background worker picks it up.** One job at a time, an `asyncio` queue, no
Redis and no Celery. It is a loop that takes a job off a list and runs seven
stages in order.

---

## The seven stages

| Stage | What it does | Who does it |
|---|---|---|
| Transcribe | words with exact timestamps | Groq Whisper, hosted |
| Find gaps | silences longer than 1.5s | plain arithmetic, no model |
| Analyse | for each gap, fill or leave silent, and why | Gemini, watching the video |
| Describe | write it, say it, measure it, retry until it fits | Gemini + ElevenLabs |
| Coverage | could a listener actually reconstruct the scene? | Groq Llama |
| Mux | mix narration into the original soundtrack | ffmpeg |
| Publish | write the locked provenance record | Genblaze |

**There is no keyframe stage.** The whole video goes to Gemini, so the model sees
motion instead of one frozen frame per gap.

---

## The two loops, which are the actual product

**Loop 1, fit.** Narration has to physically fit the silence. If the gap is 4.6
seconds and the render comes out at 5.8, that is a failure, so it rewrites
shorter and tries again. No model judges this; it is arithmetic on the rendered
audio. If four rewrites do not fit, it speeds up delivery slightly, and if that
still fails it leaves the gap silent rather than talking over the dialogue.

Every attempt is kept, so the UI can show the failures struck through with their
measured durations. That is the thing worth watching in a demo.

**Loop 2, coverage.** Asks whether a blind listener would actually know what
happened, by replaying the audio-only experience to a *different* model and
checking which visual facts survive. Measured twice, dialogue alone versus
dialogue plus narration, because the lift is the interesting number.

The checker is Groq, the writer is Gemini. Grading your own homework proves
nothing.

---

## Why it survives a crash

There is no database. The worker works out where it got to by asking Backblaze
which files exist:

| Question | If yes, that stage is done |
|---|---|
| `transcript.json`? | transcribing finished |
| `gaps.json`? | gap detection finished |
| `decisions.json`? | analysis finished |
| `descriptions.json`? | the fit loop finished |
| `coverage.json`? | the coverage check finished |
| `described-audio.m4a`? | mixing finished |
| `manifest.json`? | published |

Kill the server mid-job, restart it, and it resumes at the first missing piece.
Verified: a re-run logs "already done, skipping" for each finished stage and
pays for nothing twice.

---

## What Genblaze does here

Genblaze is the sponsor SDK. It does two jobs.

**It orchestrates the narration step.** The text-to-speech call runs as a
`Pipeline` step with `ElevenLabsTTSProvider`, and an `ObjectStorageSink` writes
every render to Backblaze under a key derived from the content's hash.

**It writes the provenance record.** One `Manifest` per run listing every model
call, with a hash covering the whole thing, written into the Object Lock bucket
where it cannot be edited.

**The other four calls go direct, on purpose.** There is no Groq adapter, and the
Google adapter only generates images and video, not text. Those are stated
reasons, not apologies.

---

## Honest weak spots

**The cache hit rate reads 0%.** Content-addressable storage does dedupe
identical renders, proven directly. It never fires between runs because the
vision stage words the same facts differently each time, so the text differs, so
the render differs. Fixing it needs deterministic upstream generation.

**Estimated cost reads $0.00.** The ElevenLabs spec in `ModelRegistry` carries no
pricing.

**Object Lock is bypassable by our own key.** It is GOVERNANCE mode and the app
key holds `bypassGovernance`. COMPLIANCE mode would close that.

**The test clip is a poor showcase.** One describable gap in 115 seconds, and the
description is about an end title card. It exercises everything but demonstrates
little.

---

## What is left

1. Seed the gallery with finished examples and one-click samples. A judge must
   never land on an empty screen.
2. The OpenCourseWare run, which produces numbers worth publishing.
3. Deploy to Railway, with ffmpeg in the image. Do one throwaway deploy early.
4. Lifecycle rules on the media bucket, and scoped keys per bucket.
5. Demo video, and the write-up against criteria 3 and 4.
6. Record a fallback run, and rehearse the crash-resume take.

---

## Running it

```bash
cd backend && ./.venv/Scripts/python.exe main.py
cd frontend && bun dev
```

Both `.env` files must be filled in from their `.env.example`. Two things bite
repeatedly:

- `ELEVENLABS_VOICE_ID` must be a **premade** voice. Voice-library voices return
  402 on the free tier even though the id looks valid.
- Use `localhost`, not `127.0.0.1`, in `BUN_PUBLIC_API_URL`. They are different
  origins for CORS, and a killed server can leave an orphaned IPv4 listener that
  answers with stale code until you reboot.
