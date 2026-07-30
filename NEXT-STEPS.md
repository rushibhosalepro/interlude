# What's next, in plain language

A companion to [ARCHITECTURE.md](ARCHITECTURE.md). That file describes the finished
system. This one explains where we are right now, what a "worker" is, and what to
build next.

---

## Where we are today

The upload half is done and working:

1. Browser asks the API for a presigned URL
2. Browser sends the video **straight to Backblaze**, not through our server
3. Browser tells the API "it's uploaded", and the API checks it really landed

That's it. Right now, once a video is uploaded, **nothing happens to it.** It just
sits in the bucket. Everything in ARCHITECTURE.md (transcribing, finding silences,
writing descriptions) has not been built yet.

The next piece is the thing that picks up an uploaded video and starts working on
it. That thing is called a worker.

---

## What is a worker?

### The problem

When your browser calls an API, it waits for an answer. If the answer doesn't come
back in a second or two, the browser gives up and shows an error.

Our pipeline is not fast. For one video it has to:

- transcribe the speech
- find the silent gaps
- pull out frames with ffmpeg
- ask a vision model what's happening in each gap
- write narration, convert it to speech, measure it, retry if it doesn't fit
- mix the audio together

That takes **minutes**, sometimes many. There is no way to do that while the
browser waits.

### The solution

Split it into two parts.

**Part 1, the API.** Someone uploads a video. The API writes down "job number 47
needs processing" and immediately replies "got it". Takes 50 milliseconds. Browser
is happy.

**Part 2, the worker.** A separate loop running in the background that picks up job
47 and actually does the slow work. Nobody is waiting on it. It can take twenty
minutes if it needs to.

A worker is just a loop that runs forever:

```
loop forever:
    is there a job waiting?
    yes -> do the whole pipeline for it
    no  -> sleep until one arrives
```

That's genuinely all it is. Nothing clever.

### The restaurant version

The waiter takes your order and immediately goes back to the floor. He does not
stand at your table cooking. The kitchen cooks, in the background, at its own pace.

The API is the waiter. The worker is the kitchen. The job is the order ticket.

---

## How you build a worker in Python

There are a few standard options. Here they are, worst fit to best fit for us.

### Celery

The famous one. Very powerful. It needs a separate message broker program
(Redis or RabbitMQ) running alongside your app, plus its own config and its own
process to launch.

**Not for us.** It's built for running hundreds of jobs across many machines. We
run one job at a time on one machine. It would be a lot of setup for no benefit.

### RQ or arq

Lighter versions of the same idea. Still need Redis running.

**Not for us**, same reason. Another program to install and keep alive during a
hackathon demo.

### FastAPI's BackgroundTasks

Built into FastAPI, one line of code:

```python
background_tasks.add_task(process_video, key)
```

Tempting, but it's designed for quick things like sending a confirmation email.
There's no way to see progress, no way to cancel, and if the server restarts the
work vanishes with no record it ever existed.

**Not for us.** We need to show progress live, and we need to survive a restart.

### A background asyncio task (this is the one)

Python can run a loop in the background inside the same program as your API. No
extra software, no second process, no broker.

```python
# a list of jobs waiting their turn
queue = asyncio.Queue()

# the worker loop, started once when the app boots
async def worker_loop():
    while True:
        job_id = await queue.get()     # waits here until a job arrives
        await run_pipeline(job_id)     # the slow part
```

And the upload endpoint just adds to the queue and returns:

```python
await queue.put(job_id)
return {"jobId": job_id, "status": "queued"}
```

**This is what ARCHITECTURE.md already chose:** *"One worker, one job at a time.
No queue."* It's the right call, and the next section explains why it's not a
shortcut.

---

## The clever bit: where progress is stored

Normally a worker needs a database to remember what it has finished. If the
server crashes halfway through, the database tells it where to resume.

We don't have a database, and we don't need one, because **the files in Backblaze
already tell us.**

The worker asks Backblaze a series of yes/no questions:

| Question | If yes, that stage is done |
|---|---|
| Does `transcript.json` exist? | transcribing is finished |
| Does `gaps.json` exist? | gap detection is finished |
| Does the `frames/` folder exist? | keyframes are finished |
| Does `decisions.json` exist? | analysis is finished |
| Does `described-audio.m4a` exist? | mixing is finished |

So when the worker starts up, it walks that list and picks up at the first missing
piece. Everything already done is skipped, and none of it gets paid for twice.

This is why you can **kill the server mid-job, restart it, and it carries on.**
ARCHITECTURE.md lists that as a demo requirement, restarting the worker on camera.
It works because progress was never in the worker's memory, it's in the files.

To avoid asking Backblaze a dozen questions every time, we also write a small
summary file, `jobs/{jobId}/state.json`, after each stage. That's a shortcut, not
a second source of truth. If it's missing or looks wrong, fall back to checking
the files directly.

---

## Two things that will bite

**1. ffmpeg will freeze everything if you call it wrong.**

Normal Python waits for a program to finish, and while waiting, nothing else in
your app can run. So an ffmpeg call would freeze the live progress updates going
to the browser, exactly when a judge is watching them.

Use `asyncio.create_subprocess_exec` instead of `subprocess.run`, so the rest of
the app keeps running while ffmpeg does its thing.

**2. Only run one server process.**

The job queue lives in the app's memory. If you start the server with
`uvicorn --workers 4`, you get four separate apps each with their own private
queue, and jobs vanish into whichever one happened to answer. Keep it to one
process. Your current setup already does this.

---

## One thing blocks all of it

Right now uploaded videos are saved with names like:

```
uploads/2026/07/28/8409a9da3c134834a43f970dcd77a09a.mp4
```

But ARCHITECTURE.md expects:

```
projects/{projectId}/source/{videoId}.mp4
```

This matters more than it looks. The worker finds its progress by looking for
files next to the source, like `projects/{projectId}/analysis/{videoId}/transcript.json`.
With the current naming there's no project folder to look inside, so the whole
resume mechanism has nowhere to live.

It also unlocks two things ARCHITECTURE.md asks for: application keys restricted
to a single project, and lifecycle rules that delete `attempts/` without touching
`final/`.

Change this **before** building the worker. Nothing important has been uploaded
yet, so it costs nothing now and gets expensive later.

### The one decision needed

Where does `projectId` come from?

- **Option A:** the backend makes one up for every upload. Simplest. Every video
  is its own project. Good enough for the hackathon.
- **Option B:** the frontend sends one, so several videos can share a project.
  Needed later if you want a "project" screen listing multiple videos.

Option A is recommended unless you already know the demo shows grouped videos.

---

## The plan, in order

**1. Apply the bucket CORS rules**

Until this is done the browser cannot upload at all, so nothing downstream can be
tested. The script is written and ready:

```bash
cd backend && ./.venv/Scripts/python.exe scripts/set_b2_cors.py
```

**2. Change the key layout to `projects/{projectId}/source/{videoId}.mp4`**

Small change to `create_presigned_url`. Needs the decision above.

**3. Build the worker skeleton with a fake pipeline**

Just the queue, the background loop, and `jobs/{jobId}/state.json`. The "pipeline"
at this stage is a few stages that sleep for five seconds each and write a file.

Doing it fake first is deliberate. You can prove restart-and-resume works in
seconds instead of waiting minutes for real transcription, and you'll be debugging
one new thing at a time instead of three.

**4. Add the live progress stream (SSE) and the timeline UI**

`sse-starlette` is already installed. The browser subscribes to a job and watches
the stages tick over. Still driven by the fake pipeline.

At this point both demo requirements from ARCHITECTURE.md are provably working:
the visible loop, and resume after restart.

**5. Replace the fake stages with real ones**

Transcribe, then gap detection, then keyframes. One at a time, with the
surrounding machinery already known to work.

**6. Then the two loops**

Fit loop first, then the coverage loop.

---

## Summary

- A worker is a background loop that does slow work after the API has replied
- Ours will be a plain asyncio task inside the existing FastAPI app, no Redis,
  no Celery, no extra process
- It remembers progress by checking which files exist in Backblaze, not a database
- Which is what makes crash-resume work, and that's a demo requirement
- Fix the key naming first, it blocks everything else
- Build it with fake stages first, prove resume and live progress, then plug in
  the real pipeline
