# job-agent

Tailors a resume and cover letter to each new job posting, using retrieval over your own
past applications, then keeps improving them until a blind reviewer would interview you.

```
Handshake saved search ──► new postings ──► fit check ──► vector retrieval over your bullet bank
                                                              │
               ┌──────────────────────────────────────────────┘
               ▼
   writer (fresh agent) ──► fact check ──► blind reviewer (fresh Fable agent) ──► score ≥ TARGET_SCORE? ──► .docx for you
        ▲                                                                              │ no
        └──────────── only that one critique ◄─────────────────────────────────────────┘
                      (after MAX_ITERATIONS rounds: keep the best draft, push-notify you)
```

## Design choices

- **Your material only.** Every resume line cites the bank items it came from. A
  deterministic fact check rejects any number, skill, tool, employer or title that isn't in
  your verified profile or past documents. Admitting a gap ("I haven't used Kubernetes")
  is allowed; claiming it isn't.
- **Blind, independent reviewers.** Each round's reviewer is a brand-new agent that sees only
  the job description, the resume and the cover letter. It never sees scores, earlier
  critiques, or that there were earlier rounds. The writer sees only the latest critique.
- **Real vector RAG, no API bills.** Embeddings come from a small local model
  (`BAAI/bge-small-en-v1.5` through fastembed). The index is a single `.npz` file. Search
  uses maximal marginal relevance so near-duplicate bullets from different resume versions
  don't crowd each other out, and each job on your resume always gets its own best bullets.
- **You submit.** Nothing is ever submitted for you. The agent drafts; you review and apply.
- **Personal data stays out of git.** Profile, bank, index, postings and drafts live in a
  private folder (`JOB_AGENT_DATA`), never in this repo.

## Setup

```bash
git clone https://github.com/dalyathan/job-agent && cd job-agent
uv venv && uv pip install -e '.[embed,dev]'      # or: pip install -e '.[embed,dev]'
mkdir -p ~/Documents/job-agent-data && cp .env.example ~/Documents/job-agent-data/.env
cp examples/profile.example.json ~/Documents/job-agent-data/profile.json   # fill in, then set "verified": true
export JOB_AGENT_DATA=~/Documents/job-agent-data

job-agent ingest --kind resume path/to/resumes/*.txt
job-agent ingest --kind cover_letter path/to/letters/*.txt
job-agent build-kb
```

## Settings (`.env` in your data folder)

| Variable | Default | Meaning |
|---|---|---|
| `TARGET_SCORE` | 9 | A draft passes when a blind reviewer scores it at least this (1–10) |
| `MAX_ITERATIONS` | 5 | Rounds before giving up and sending a push notification |
| `HANDSHAKE_SEARCH_URL` | | Your saved Handshake search |
| `HANDSHAKE_MAX_NEW_PER_RUN` | 15 | Cap on postings read per run |
| `MIN_FIT_SCORE` | 6 | Skip postings that fit worse than this |
| `TOP_K` | 14 | Bullets retrieved per job |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Local embedding model |

## Commands

| Command | Does |
|---|---|
| `check-profile` | Is the profile verified? Lists open questions |
| `ingest --kind resume\|cover_letter FILES` | Splits documents into bank items, folding near-duplicates |
| `build-kb` | Embeds the bank into the vector index |
| `seen` / `add-job` | De-duplicates and stores a posting (same company + title + location = same job) |
| `pending` | Jobs still to draft |
| `context JOB` | Retrieval: writes the writer's context packet |
| `factcheck JOB N` | Checks round N's draft against your material |
| `blind-packet JOB N` | Prints exactly what the blind reviewer may see |
| `record-review JOB N --file REPLY` | Stores the score and prints `pass`, `revise` or `give_up` |
| `finalize JOB` | Renders the best round to `.docx` and updates `tracker.csv` |
| `skip JOB --reason ...` | Marks a poor fit |

## Running it hourly

`prompts/runbook.md` is the instruction set for a scheduled Claude task that runs on your
Mac: it reads new postings from your Handshake saved search in your signed-in browser,
calls these commands, and starts the writer and Fable reviewer agents. `prompts/writer.md`,
`prompts/reviewer.md` and `prompts/fit.md` are the agents' prompts.

Note: Handshake's terms of service prohibit automated collection of job postings. Running
the collection step is at your own risk to your Handshake account.

## Tests

```bash
pytest
```
