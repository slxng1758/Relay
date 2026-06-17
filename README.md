# Relay

**Multi-Agent AI for Continuity During Team Transitions**

Teams lose context constantly — engineers leave, projects get reassigned, and
the "why did we do it this way?" knowledge walks out the door with them. Relay
builds a living **operational knowledge graph** of your org by ingesting
Slack, GitHub, Jira, and Google Docs, then runs a set of LangGraph agents on
top of it to answer the questions that usually require pinging five people on
Slack.

## What it does

Relay continuously ingests activity from your tools and links it into a graph
of **Teams, People, Services, Repositories, Decisions, Tasks, and Documents**.
Four agents query that graph on demand:

| Agent                      | Endpoint                           | What it answers                                                                                                                                                       |
| -------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dependency Mapper**      | `POST /api/agents/dependency`      | "What does this service depend on, and is anything circular or unusually risky?" Walks the service dependency graph, detects cycles, and produces a risk score.       |
| **Decision Archaeologist** | `POST /api/agents/decisions/query` | "Why was this built this way?" Retrieves relevant past decisions (via semantic + keyword search), builds a timeline, and flags superseded decisions.                  |
| **Risk Auditor**           | `POST /api/agents/risk`            | "What's about to break?" Scans for signals like overdue tasks and unowned services across a team, service, or the whole org, scores and ranks them.                   |
| **Onboarding Generator**   | `POST /api/agents/onboarding`      | "Get this person up to speed." Generates a tailored onboarding or handoff doc for a person joining a team, grounded in the team's real services, decisions, and docs. |

All agent calls are authenticated with a JWT bearer token.

## Architecture

```
Slack / GitHub / Jira / Google Drive
              │
   ┌──────────▼──────────┐
   │  Ingestion connectors │  (real API clients, ARQ background workers)
   └──────────┬──────────┘
              │ upsert nodes & edges
   ┌──────────▼──────────┐
   │ Postgres + pgvector  │  operational knowledge graph + embeddings
   └──────────┬──────────┘
              │
   ┌──────────▼──────────┐
   │  LangGraph agents     │  dependency / decision / risk / onboarding
   └──────────┬──────────┘
              │
   ┌──────────▼──────────┐
   │     FastAPI          │  /api/agents, /api/graph, /api/ingestion
   └───────────────────────┘
```

**Stack:** FastAPI · LangGraph · SQLAlchemy (async) · PostgreSQL + pgvector ·
Redis + ARQ · sentence-transformers · structlog

## Project structure

```
.
├── app/
│   ├── agents/        # LangGraph agent graphs (dependency, decision, risk, onboarding)
│   ├── api/           # FastAPI routes & middleware
│   ├── core/          # config, db, redis, logging, security, llm
│   ├── db/             # ORM models, repositories, Alembic migrations
│   ├── ingestion/      # Slack/GitHub/Jira/GDocs connectors + ARQ worker
│   ├── memory/         # embeddings + hybrid (semantic + keyword) retrieval
│   ├── schemas/         # Pydantic request/response models
│   └── main.py / cli.py
├── infra/              # Dockerfiles, Postgres init, Redis config
├── scripts/            # seed_dev_data.py
└── tests/              # unit / integration / e2e
```

## Quick start

### Prerequisites

- Docker + Docker Compose
- Python 3.11+ (only needed if running outside Docker)

### 1. Configure

```bash
git clone https://github.com/slxng1758/relay.git
cd relay
cp .env.example .env
```

The defaults work out of the box for local dev. To enable real ingestion, add
your own tokens to `.env` (`SLACK_BOT_TOKEN`, `GITHUB_TOKEN`, `JIRA_*`,
`GOOGLE_*`) — otherwise the app and agents still run fine against seed data.

### 2. Run everything

```bash
docker compose up -d --build
docker compose exec api opsgraph db upgrade   # create schema
docker compose exec api opsgraph seed         # load sample data (optional)
```

- API: http://localhost:8000 (interactive docs at `/docs`)
- Health check: `curl localhost:8000/health`

### 3. Get an auth token

`opsgraph tokens create <subject>` prints a signed JWT to stdout — capture it
into a variable:

```bash
TOKEN=$(docker compose exec api opsgraph tokens create demo-user | tr -d '\r')
```

### 4. Call an agent

```bash
# Find the seeded "auth-service" id, then ask the dependency agent about it
curl -s "localhost:8000/api/graph/nodes/service" | jq

curl -X POST localhost:8000/api/agents/risk \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"scope": "global"}'
```

### Browse the graph directly

```bash
curl "localhost:8000/api/graph/search?q=jwt&types=decision,task"
curl "localhost:8000/api/graph/nodes/team"
curl "localhost:8000/api/graph/nodes/decision/<id>/edges"
```

## Running locally without Docker

```bash
docker compose up -d postgres redis   # still need these two
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
opsgraph db upgrade
opsgraph seed
opsgraph serve --reload
```

Run the ingestion worker separately:

```bash
python -m app.ingestion.queue.worker
```

## Tests

```bash
pytest tests/unit          # pure logic, no services required
pytest tests/e2e           # API smoke test
pytest tests/integration   # requires Postgres (docker compose up -d postgres)
```

## License

MIT
