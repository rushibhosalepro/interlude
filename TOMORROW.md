# What to do tomorrow

Plain version. Read top to bottom, do the steps in order.

---

## First: nothing is broken in the code

Right now the app can't read files from Backblaze. That is **not a bug**. Your
Backblaze account hit its daily download limit.

Your caps page showed this:

```
Download Bandwidth    1 GB of 1 GB     <- FULL, this is the problem
Class B Transactions  1,359 of 2,500   <- fine
Storage               972 MB of 10 GB  <- fine
```

You get 1 GB of downloads free per day. We used it all up testing.

**Fix:** Backblaze dashboard → Caps & Alerts → Edit Caps → raise
"Daily Download Bandwidth" to 20 GB.

It costs about 1 cent per GB after the first free GB. So even a busy day is a
few cents.

Or just wait, it resets every day on its own.

**Do this before judging too.** If judges load your page, each one downloads a
5 MB video. A hundred views is half a gigabyte. If the cap hits during judging,
your page breaks and it looks like your app is broken.

---

## What I changed on the page today

Two things. Both come from the winners document you have.

### 1. A new panel: "Left silent on purpose"

**What it does:** shows the silences your app decided NOT to talk over, and the
reason why.

It will look roughly like this:

```
LEFT SILENT ON PURPOSE · 11 OF 14

0:14 · 2.1s   nothing changes, the speaker stays where they were
0:38 · 3.4s   the diagram was already described out loud
1:02 · 1.9s   decorative title the speaker reads anyway

Description density 21%. Restraint is correct, so this should be low.
```

**Why it matters:** your big claim is "we only narrate when it's actually
needed". But the page only showed what it DID narrate. That proves nothing.

Now it shows the decisions it made to stay quiet. That is proof, not a claim.

The winning project ComplianceOS did the same thing: it showed 8 specific
findings by name instead of saying "it finds problems".

**Where the text comes from:** your app already saved a reason for every skipped
gap. It was sitting unused in the data. I just put it on screen.

### 2. The Original / Described switch now sits on top

**What changed:** it used to be a tiny button next to the play button. Now it is
big, above the video, with a line of text next to it saying:

> Switch to **Original** to hear what a blind student gets today.

**Why it matters:** this one click IS your whole product. Same moment in the
video, one click, and a judge hears the difference between silence and
narration. That is your best 10 seconds. It should not be hiding.

---

## The one thing blocking everything

Your demo video is a coding interview clip. It has **one** gap, about a logo at
the end.

So your page currently says:

> 1 of 1 silences narrated, 0 left silent on purpose

That is the opposite of your argument. It says you narrate everything.

And the new "left silent" panel **will not even show up**, because there are no
skipped gaps to list.

**You need a better clip.** Something where a teacher is drawing on a board and
pausing. That gives you 10 to 15 gaps, and most will be skipped. Then:

- the page says something like "3 of 14 narrated, 11 left silent on purpose"
- the new panel appears and fills with real reasons
- the density number becomes low, which is the point
- you get a real number for the write-up

One clip fixes all four.

---

## About clip length (this is not what you think)

Your 17 minute video did not fail for being 17 minutes. It failed for being a
big **file**.

Two different limits, and only one of them bites:

| Step | Limit | What it applies to |
|---|---|---|
| Transcribe | 25 MB | the **audio**, which we now extract first. A 39 minute lecture is 8.9 MB of audio. Basically never a problem. |
| Analyse | 18 MB | the **video file**. This is the one that stops you. |

So a longer clip is fine if the file is small enough. Roughly:

```
 2 min  ->  fits easily
 4 min  ->  fits, normal quality
 6 min  ->  fits if you shrink it a bit
10 min  ->  fits only if you shrink it a lot
17 min  ->  would look bad, not worth it
```

To shrink a clip automatically, add `--fit`:

```bash
cd backend
./.venv/Scripts/python.exe scripts/seed_samples.py "C:\path	o\lecture.mp4" --id lecture --seconds 240 --fit
```

That drops it to 854 pixels wide and picks a bitrate that fits. The vision model
does not need HD to see someone drawing on a board.

**Four minutes is the sweet spot.** Long enough for 10 to 15 gaps, small enough
to fit without looking rough.

---

## Steps for tomorrow, in order

**Step 1. Raise the Backblaze cap.** (2 minutes)
Dashboard → Caps & Alerts → Edit Caps → Daily Download Bandwidth → 20 GB.

**Step 2. Fix the voice ID.** (30 seconds)
Open `backend/.env`. Find this line:

```
ELEVENLABS_VOICE_ID=...
```

Change it to:

```
ELEVENLABS_VOICE_ID=pNInz6obpgDQGcFmaJgB
```

Your current voice is from the ElevenLabs "voice library", which free accounts
cannot use through the API. Every run dies because of this. It has failed three
times already.

**Step 3. Find a good clip.**
A lecture where someone draws, writes, or points at things. Four minutes is
fine. See the section below on length, it is about file size, not minutes.

**Step 4. Start the servers.**

```bash
cd backend
MAX_CLIP_SECONDS=300 uv run .\main.py
```

```bash
cd frontend
bun dev
```

**Step 5. Upload the clip and watch it run.**
It takes a few minutes. Watch the fit loop in the timeline.

**Step 6. Tell me it's done.**
Then I can check the new panel actually looks right with real data. I could not
test it today because reads were blocked.

---

## What is still left after that

- **Demo video.** Screen recording, about 90 seconds. I wrote a shot list in the
  chat: start on Original in a silence, click Described, then show the fit loop
  running live, then the numbers, then restart the worker to show it resume.
- **Write-up.** Four sections, one per judging criterion.
- **Replace "4,000 lectures"** in the headline with a real number from your run.
- **Deploy** if the submission form asks for a live link. Check whether it does.

---

## Things that are done and working

You do not need to worry about these:

- Upload straight to Backblaze, no server in the middle
- All 7 pipeline steps
- Both loops, the rewrite loop and the coverage check
- Restart the app mid-job and it carries on where it left off
- The provenance record locked in the second bucket
- The judge page layout
- One-click sample clips, so judges never have to upload anything
