# Hourly run (instructions for the scheduled Claude task)

You are running job-agent for the owner of this repo. Work quietly; the owner reads the
tracker and push notifications, not this session. Never submit an application, message
anyone, or change anything on Handshake. Never put personal data in the git repo.

Locations on the owner's Mac (through the device shell, `mcp__remote-devices__device_bash`):
- code: `$HOME/mnt/Documents/job-agent` (this repo)
- private data: `$HOME/mnt/Documents/job-agent-data` (profile, bank, index, jobs, tracker, `.env`)

Every shell call starts fresh, so begin each one with:
```bash
cd $HOME/mnt/Documents/job-agent && set -a && . ../job-agent-data/.env && set +a && \
export JOB_AGENT_DATA=$HOME/mnt/Documents/job-agent-data && source .venv/bin/activate
```
(abbreviated below as `$SETUP`). Each call must finish in under 3 minutes.

## 0. Preflight
1. Load tools with ToolSearch in one call: device_bash, the built-in browser tools
   (`mcp__remote-devices__Claude_Browser__*`; fall back to Claude in Chrome), `PushNotification`.
2. `cd $HOME/mnt/Documents/job-agent && git pull --ff-only` (first run: clone it, then
   `uv venv && uv pip install -e '.[embed]'`).
3. `$SETUP && job-agent check-profile`. If it exits 2 (not verified): if
   `../job-agent-data/.notified-unverified` is older than 24h or missing, push-notify
   "job-agent: verify profile.json before I can draft anything" and touch that file. Stop.

## 1. Collect new Handshake postings
1. Open `$HANDSHAKE_SEARCH_URL` (from `.env`) in the browser. If you see a sign-in page,
   captcha or warning, push-notify "Handshake needs you to sign in" and skip to step 2.
2. Read the result list, newest first. For each posting, up to `$HANDSHAKE_MAX_NEW_PER_RUN`:
   - `job-agent seen --company ... --title ... --location ...`. If seen, skip it.
   - Otherwise open the posting, read its full text (`get_page_text`), and save it:
     `job-agent add-job --company ... --title ... --location ... --url ... --deadline ... --file <tmpfile>`.
   - Act like a person reading: wait 20-60 seconds between postings, open at most one
     tab at a time, don't page past the first results page.
3. Stop reading as soon as you reach a posting you have already seen.

## 2. Draft applications
`job-agent pending` lists jobs to work on. Handle at most 4 per run, oldest first.

For each job:

**Fit check.** Give `prompts/fit.md` plus `jobs/<id>/job.json` text and `profile.json` to a
fresh subagent. If `apply` is false or `fit_score < $MIN_FIT_SCORE`, run
`job-agent skip <id> --reason "<why>"` and move on.

**Context.** `job-agent context <id>`.

**Rounds n = 1, 2, ... (the loop):**
1. *Write.* Start a fresh subagent (default model) with `prompts/writer.md` and
   `context.json`. For n > 1 also give it `iter-<n-1>/draft.json` and ONLY the critique
   and top_fixes from `iter-<n-1>/review.json`. Never give it scores, the round number,
   or any older critique. Save its JSON to `iter-<n>/draft.json`.
2. *Fact check.* `job-agent factcheck <id> <n>`. If it exits 1, start a fresh writer
   subagent with the draft and the error list ("fix these; change nothing else"), save,
   re-check. After 2 failed fixes, run `job-agent skip <id> --status needs_you --reason
   "failed fact check"`, push-notify
   "<company> – <title>: draft failed the fact check, see jobs/<id>", and move on.
3. *Blind review.* Run `job-agent blind-packet <id> <n>`. Start a brand-new subagent with
   `model: "fable"` whose entire prompt is `prompts/reviewer.md` with `{{BLIND_PACKET}}`
   replaced by that output. Give it nothing else: no profile, no history, no other
   reviewers, no hint that there were earlier rounds. Save its reply to a temp file.
4. *Decide.* `job-agent record-review <id> <n> --file <reply>` prints the decision:
   - `pass`: `job-agent finalize <id>`. Done with this job.
   - `revise`: next round.
   - `give_up` (reached `$MAX_ITERATIONS` below `$TARGET_SCORE`): `job-agent finalize <id>`
     (renders the best-scoring round) and push-notify the `notification` text.

## 3. Finish
Reply with a two-line summary: postings collected, drafts ready, jobs needing the owner.
