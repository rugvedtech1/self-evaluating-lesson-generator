# 📘 Self-Evaluating Lesson Content Generator

[![tests](https://github.com/rugvedtech1/self-evaluating-lesson-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/rugvedtech1/self-evaluating-lesson-generator/actions/workflows/tests.yml)

| | |
|---|---|
| **Live app** | https://self-evaluating-leappn-generator-acksh7hcp6pokvvytgxrfr.streamlit.app/ |
| **API health** | https://lesson-generator-api.onrender.com/health |
| **Sample lesson (approved by the evaluator)** | [docs/lesson-intro-to-rag.md](docs/lesson-intro-to-rag.md) |
| **Demo video** | _Coming soon (recording in progress)_ |

> Free hosting: the backend sleeps after 15 minutes without traffic, so the first request can take about a minute.

A learner chats with an intake assistant, which builds a **learner profile** (education level, English level, technical background, AI knowledge, preferred style). After the learner confirms it, a **Generator** writes a beginner-friendly lesson and an **Evaluator** grades it against a **six-criterion PASS/FAIL rubric**. A **Decision Gate** approves the lesson, sends it back for revision with specific feedback, or rejects the run after **three attempts**. Every attempt and verdict is kept in a **rejection log**. Across many runs, the system **learns from recurring failures**: it proposes a better generator prompt, **validates it before activating it**, and supports **rollback**.

"Introduction to RAG" is the sample topic, with eight required concepts. Any other topic uses the generic rubric.

---

## Architecture

```mermaid
flowchart LR
  L["Learner"] --> S["Streamlit frontend"]
  S -- "HTTPS + Supabase JWT" --> A["FastAPI backend"]
  A -- "JWT verified locally via JWKS" --> SA["Supabase Auth"]
  A --> I["Intake assistant"]
  A --> W["LangGraph lesson workflow"]
  W --> G["Generator"] --> E["Evaluator"] --> D{"Decision Gate"}
  D -- "PASS" --> AP["Approved lesson"]
  D -- "FAIL, attempts left" --> G
  D -- "FAIL on attempt 3" --> RJ["Rejected run"]
  A --> DB[("Supabase Postgres with RLS")]
  W --> CP[("LangGraph checkpoints")]
  EV["Self-evolution"] --> DB
```

| Layer | Technology |
|---|---|
| Frontend | Streamlit (session tokens in `session_state`, automatic token refresh, polling, typewriter display) |
| Backend | FastAPI, Pydantic, SQLAlchemy 2, Alembic |
| Auth | Supabase Auth; the backend verifies ES256 JWTs locally against the project JWKS |
| Database | Supabase Postgres, **row-level security on every table** |
| Workflow | LangGraph with the Postgres checkpointer (private `langgraph` schema) |
| LLMs | LangChain `init_chat_model` + structured output. Intake `gpt-4o-mini`; Generator and Evaluator `gpt-4.1-mini` |
| Tests / CI | Pytest (318 tests), GitHub Actions with a Postgres service container |
| Hosting | Render (API), Streamlit Community Cloud (UI) |

## How a lesson is produced

1. **Intake.** Python decides which profile field to ask about next (fixed order, never repeated, at most two tries before "Not specified"). The LLM only extracts facts and words the question. Values it infers, such as "no technical background" for an 8th-grade student, are labelled *(inferred)* and never overwrite what the learner said.
2. **Confirmation.** The learner confirms the profile, and generation starts in the background (`202 Accepted`). The UI polls for progress.
3. **Generation.** The Generator uses the **active versioned prompt**, the topic's required concepts and the learner profile. On a revision it also gets the previous lesson and the Evaluator's feedback.
4. **Evaluation, in three layers:**
   - **Python structural checks** (title, sections, length, summary). A structural hard fail overrides the AI.
   - **The AI judge** returns a verdict, a reason and **evidence quotes** for each criterion and each required concept. It does **not** return an overall verdict.
   - **Python decides.** Evidence must actually appear in the lesson (anchored matching). Every concept must be judged exactly once, and a failed concept forces Topic coverage to FAIL. **Overall PASS only if all six criteria pass.**
5. **Decision Gate.** PASS means approved. FAIL with attempts left means regenerate with feedback. FAIL on attempt 3 means rejected. **Technical failures** (API down, invalid output after retries) are recorded as errors, **never** as quality verdicts.

### The rubric (no partial credit)

| Criterion | Passes when |
|---|---|
| Accuracy and grounding | Technically correct; no invented facts, studies or sources |
| Beginner friendliness | Suits the learner's level: short sentences, one idea at a time |
| Practical examples | Concrete examples, each walked through and linked to the concept |
| Jargon explanation | Every technical term or abbreviation is defined when first used |
| Topic coverage | Every required concept is actually explained, not just named |
| Teaching flow | Introduction, basics before advanced ideas, connected sections, summary |

## Self-evolution and prompt management

Open **⚙️ System learning** in the app, or use the CLI.

1. **Aggregate.** FAIL evaluations from runs that used the **currently active** generator prompt are counted per pattern (a failed criterion, or a specific missing concept).
2. **Detect.** A pattern counts as recurring at **3 occurrences** (`EVOLUTION_MIN_OCCURRENCES`).
3. **Propose.** A **playbook** adds one pre-written, targeted rule per recurring pattern to the active prompt, producing a candidate version. It's deliberately rule-based rather than an LLM rewriting prompts: it's auditable, can't be manipulated through user content, and can't drift.
4. **Validate.** The candidate writes lessons for a fixed set of validation learner profiles, and the real Evaluator judges them. **Every case must PASS on a single attempt.**
5. **Activate or reject.** It's activated automatically only if validation passes, and the previous version is retired. If validation fails, the candidate is rejected and the active prompt is unchanged. A technical error leaves it as a draft.
6. **Rollback.** Admins can restore the previous validated version. A rejected version can never become active.

Every version is kept with its reason and validation report. A running lesson keeps the prompt version it started with. Only emails in `ADMIN_EMAILS` can run evolution or roll back; anyone logged in can view the data.

**Privacy:** the learning memory (`failure_patterns`) holds only rubric keys, counts, timestamps and fixed wording from the rubric and topic configuration. It never holds user IDs, messages, profiles, lesson text or the evaluator's free-text reasons. Tests enforce this.

## Security and user isolation

- Every user-owned table has **RLS policies** keyed on `auth.uid()`. System tables (`prompt_versions`, `failure_patterns`) have RLS enabled with **no** policies, so only the backend can access them. LangGraph tables live in a private schema.
- The backend also filters every query by the authenticated user. Another user's chat returns **404**, so its existence isn't revealed. Tests cover cross-user access.
- Secrets live only in `.env` and the hosting dashboards. The backend uses the Supabase **publishable** key, never a secret or service-role key.

## Run it locally

Requirements: Python 3.12, Docker (for the test database), a Supabase project and an OpenAI API key.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in your own values (never commit .env)
```

| Variable | Purpose |
|---|---|
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Supabase project (Auth). Turn off "Confirm email" for local testing |
| `DATABASE_URL` | Supabase **session pooler** URL (`postgresql+psycopg://…?sslmode=require`) |
| `OPENAI_API_KEY`, `INTAKE_MODEL`, `GENERATOR_MODEL`, `EVALUATOR_MODEL` | LLM access and model choice |
| `BACKEND_URL`, `REQUEST_TIMEOUT_SECONDS` | Where the frontend finds the API |
| `RECOVER_RUNS_ON_STARTUP` | Resume interrupted lesson runs from their checkpoints |
| `ADMIN_EMAILS` | Comma-separated emails allowed to run evolution and rollback |
| `DEMO_FLAW_MODE`, `DEMO_FLAW_CASE` | Recording demos only; see below. Default `off` |
| `TEST_DATABASE_URL` | Local throwaway Postgres for the test suite |

```bash
(cd backend && alembic upgrade head)            # tables, RLS policies, langgraph schema

uvicorn app.main:app --app-dir backend --reload --reload-dir backend --port 8001
streamlit run frontend/streamlit_app.py          # in a second terminal
```

## Tests

```bash
docker run -d --name lesson-gen-test-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=lesson_test \
  -p 127.0.0.1:54329:5432 postgres:16
# .env: TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:54329/lesson_test

pytest -q                                   # 318 passed, 4 skipped (the live LLM tests)
RUN_LIVE_LLM_TESTS=1 pytest -m live -q      # optional: real LLM calls, costs a few cents
```

- The test fixtures create a Supabase stub (`auth.users`, `auth.uid()`, the `anon`/`authenticated` roles), run the migrations, and roll back each test inside a transaction. A guard refuses any non-localhost database.
- CI runs the same suite against a Postgres service container and **fails if the database tests are skipped**.

**Evaluator quality check** (a known dataset: one good lesson plus six lessons, each with one deliberate flaw):

```bash
PYTHONPATH=backend python -m app.evaluator.cli            # expects 7/7
PYTHONPATH=backend python -m app.evolution.cli status     # patterns + prompt versions (free)
PYTHONPATH=backend python -m app.evolution.cli validate   # validate the active prompt (~$0.02)
```

## Demo mode (for recordings)

Recurring failures and regenerations are rare with a good prompt, so `DEMO_FLAW_MODE` (server-side only, default `off`) replaces Generator attempts with a **known-flawed lesson from the evaluation dataset**, labelled in the lesson with a *Demo mode* banner. `first` flaws attempt 1 only, so you see a rejection, regeneration with feedback and approval. `all` flaws every attempt, so the run is rejected after 3. **Only the Generator is replaced.** The Evaluator, Decision Gate, rejection log and pattern counting all run for real, and prompt validation never uses demo mode.

## Deployment

- **Backend on Render (free web service).**
  - Build: `pip install -r backend/requirements.txt`
  - Start: `uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT`
  - Health check: `/health`
  - Set `PYTHON_VERSION=3.12.3` and the variables above, without `TEST_DATABASE_URL`.
- **Frontend on Streamlit Community Cloud.** Entry point `frontend/streamlit_app.py` (dependencies come from `frontend/requirements.txt`). Secrets: `BACKEND_URL` and `REQUEST_TIMEOUT_SECONDS = "90"`, to allow for the backend's cold start.
- **Cost control.** OpenAI credit is prepaid. After recording the demo, disable new sign-ups in Supabase Auth and share a reviewer account, so strangers can't use up the credit.

## Design decisions and trade-offs

- **Python decides, the LLM judges.** The AI gives per-criterion verdicts with evidence, and code computes the overall result, so one hallucinated "PASS" can't approve a lesson.
- **Typewriter display instead of token streaming.** A lesson must pass evaluation before the learner sees it, so streaming raw generator output would show unapproved text.
- **Rule-based prompt evolution behind a validation gate**, rather than letting an LLM edit production prompts.
- **Background tasks plus checkpoints instead of a job queue** (no Redis or Celery). Each graph node uses its own short transaction, and saves are idempotent, so a resumed run never duplicates attempts.
- **"Confirm email" is off** so reviewers can sign up and log in immediately. A production deployment should turn it back on.

## Known limitations

- **The evaluator can be lenient.** It's an LLM from the same family as the generator. It once passed a fairly dense lesson for a 4th-grade profile. A stronger evaluator model or a stricter beginner rubric would help.
- **LLM variance.** Strict single-attempt validation can sometimes reject a good candidate prompt by chance. Running each case several times and comparing the candidate with the active prompt would be more robust, at about 3× the cost.
- **The playbook only knows pre-written fixes.** An LLM proposer could be added behind the same validation gate. Patterns are counted per failed evaluation, so a run rejected after three attempts counts three times.
- **Built for a single backend instance.** Background runs and startup recovery assume one process. Several instances would need a shared queue or locking.
- **Only "Introduction to RAG" has a concept list.** Other topics are judged on the generic rubric.
- **Free-tier hosting** sleeps when idle.

## Project layout

backend/app/
api/ FastAPI routes (auth, chats, lesson runs, system learning)
intake/ learner-profile intake assistant
generator/ lesson generator (versioned prompt)
evaluator/ structural checks, AI judge, evidence verification, dataset, CLI
workflows/ LangGraph graph, decision gate, runner, recovery, demo mode
evolution/ failure patterns, playbook, validation, evolution cycle, CLI
services/ database operations (chats, profiles, lessons, prompts)
models/ SQLAlchemy models; migrations/ Alembic (tables + RLS)
backend/tests/ 318 tests
frontend/ Streamlit app (auth, chat, evaluation details, system learning)
docs/ sample approved lesson

