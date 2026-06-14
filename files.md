Root — opsgraph/
opsgraph/docker-compose.yml
opsgraph/Makefile
opsgraph/alembic.ini
opsgraph/pyproject.toml
opsgraph/.env.example
opsgraph/.gitignore
opsgraph/.pre-commit-config.yaml

App root — opsgraph/app/
opsgraph/app/main.py
opsgraph/app/cli.py

Core — opsgraph/app/core/
opsgraph/app/core/config.py
opsgraph/app/core/database.py
opsgraph/app/core/redis.py
opsgraph/app/core/logging.py
opsgraph/app/core/llm.py
opsgraph/app/core/security.py

Database models — opsgraph/app/db/models/
opsgraph/app/db/models/__init__.py
opsgraph/app/db/models/nodes.py
opsgraph/app/db/models/edges.py
opsgraph/app/db/models/embeddings.py

Database repositories — opsgraph/app/db/repositories/
opsgraph/app/db/repositories/base.py
opsgraph/app/db/repositories/edge_repository.py

Database migrations — opsgraph/app/db/migrations/
opsgraph/app/db/migrations/env.py

API routes — opsgraph/app/api/routes/
opsgraph/app/api/routes/health.py
opsgraph/app/api/routes/graph.py
opsgraph/app/api/routes/agents.py
opsgraph/app/api/routes/ingestion.py
opsgraph/app/api/routes/docs.py

Schemas — opsgraph/app/schemas/
opsgraph/app/schemas/__init__.py

Agents — opsgraph/app/agents/
opsgraph/app/agents/state.py
opsgraph/app/agents/dependency/dependency_graph.py
opsgraph/app/agents/decision/decision_graph.py
opsgraph/app/agents/risk/risk_graph.py
opsgraph/app/agents/onboarding/onboarding_graph.py

Ingestion — opsgraph/app/ingestion/
opsgraph/app/ingestion/base_connector.py
opsgraph/app/ingestion/connectors/slack/connector.py
opsgraph/app/ingestion/connectors/github/connector.py
opsgraph/app/ingestion/connectors/jira/connector.py
opsgraph/app/ingestion/connectors/gdocs/connector.py
opsgraph/app/ingestion/queue/tasks.py
opsgraph/app/ingestion/queue/worker.py

Memory — opsgraph/app/memory/
opsgraph/app/memory/vector/embedder.py
opsgraph/app/memory/retrieval/retriever.py

Infra — opsgraph/infra/
opsgraph/infra/docker/Dockerfile
opsgraph/infra/docker/Dockerfile.worker
opsgraph/infra/postgres/init.sql
opsgraph/infra/redis/redis.conf

Tests — opsgraph/tests/
opsgraph/tests/conftest.py
opsgraph/tests/unit/test_agents.py
opsgraph/tests/integration/test_ingestion.py

Scripts — opsgraph/scripts/
opsgraph/scripts/seed_dev_data.py