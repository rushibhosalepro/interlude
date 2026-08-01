# Interlude

**Audio description for lecture video, generated automatically.**

You captioned 4,000 lectures. Your blind students still can't follow one of them.
Captions serve deaf viewers. They do nothing for a blind student, who needs the
opposite: the things that happen on screen while nobody is speaking. Interlude
finds those silences, decides which ones actually hide something visual, writes
narration short enough to fit inside the gap, and hands back the lecture with a
described audio track.

Built for the **Backblaze Generative Media Hackathon** (Genblaze on B2).

- **Live app:** https://interlude-beta.vercel.app
- **Demo video:** see the Devpost submission

---

## What it does

1. Transcribe the lecture and find the silences between words.
2. For each silence, a vision model decides *fill or leave silent* — most stay
   silent, because over-narration is the classic failure of audio description.
3. Write a description, synthesise it, and **measure the audio** — if it runs
   past the gap it rewrites shorter until it fits.
4. A **second, different** model listens to the described audio with no video
   and reports which visual facts it can recover. That is the honest test of a
   good description, so it grades itself against it.
5. Mux the described track back onto the video and serve it from Backblaze B2,
   with an immutable provenance record of every model call.

## Stack

| Layer | Choice |
|---|---|
| Frontend | React + Bun, deployed on Vercel |
| Backend | FastAPI, Python 3.13, uv, deployed on Railway (Docker) |
| Storage | Backblaze B2 (S3-compatible), Object Lock on the provenance bucket |
| Orchestration | Genblaze SDK (TTS pipeline + provenance manifest) |
| Models | Groq Whisper (STT), Google Gemini (vision + writing), Groq Llama (coverage checker), ElevenLabs (TTS) |
| Media | ffmpeg / ffprobe |

Architecture, the two loops, and the B2/Genblaze design are documented in the
Devpost write-up.

## Run it locally

Prerequisites: [Bun](https://bun.sh), [uv](https://docs.astral.sh/uv/), and
**ffmpeg** on your PATH.

**Backend**

```bash
cd backend
cp .env.example .env      # fill in B2 keys, GOOGLE_API_KEY, GROQ_API_KEY, ELEVENLABS_API_KEY
uv sync
uv run uvicorn main:app --reload --port 3001
```

**Frontend**

```bash
cd frontend
cp .env.example .env      # set BUN_PUBLIC_API_URL=http://localhost:3001
bun install
bun dev
```

Open http://localhost:3000. Three described lectures are there to watch; two of
them run the full pipeline with one click, no upload needed.

## Backblaze B2 setup

Two buckets:

- `interlude-media` — source uploads, analysis artifacts, every description
  attempt, and the final described video. Lifecycle-expire the attempts.
- `interlude-compliance` — one immutable provenance record per run, **Object
  Lock enabled**.

Apply the browser-upload CORS rules with `backend/scripts/set_b2_cors.py`
(reads `CORS_ORIGINS`).

## Deploy

- **Backend → Railway:** root directory `backend`, it builds `backend/Dockerfile`
  (ffmpeg included). Set the env vars; do **not** set `PORT` (Railway injects it).
- **Frontend → Vercel:** root directory `frontend`, `vercel.json` sets the build.
  Set `BUN_PUBLIC_API_URL` to the Railway URL, then add the Vercel origin to
  both `CORS_ORIGINS` (Railway) and the B2 bucket CORS rule.

## License

MIT. See [LICENSE](LICENSE). Demo lectures are from MIT OpenCourseWare
(CC BY-NC-SA); descriptions are generated and not endorsed by MIT.
