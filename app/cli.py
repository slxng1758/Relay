"""
opsgraph CLI – database management, dev server, seeding, and token issuance.

Installed as the `opsgraph` console script (see `pyproject.toml`).
"""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console

app = typer.Typer(help="opsgraph operational graph CLI")
db_app = typer.Typer(help="Database management")
tokens_app = typer.Typer(help="Issue auth tokens")
app.add_typer(db_app, name="db")
app.add_typer(tokens_app, name="tokens")

console = Console()


@db_app.command("init")
def db_init() -> None:
    """Create all tables directly from the ORM models (dev/test only)."""
    from app.core.database import init_db

    asyncio.run(init_db())
    console.print("[green]Database tables created.[/green]")


@db_app.command("upgrade")
def db_upgrade(revision: str = typer.Argument("head")) -> None:
    """Apply Alembic migrations up to `revision` (default: head)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, revision)
    console.print(f"[green]Database upgraded to '{revision}'.[/green]")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the API with uvicorn."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


@app.command()
def seed() -> None:
    """Populate the database with sample dev data."""
    from scripts.seed_dev_data import main as seed_main

    asyncio.run(seed_main())


@tokens_app.command("create")
def tokens_create(
    subject: str = typer.Argument(..., help="Subject ('sub' claim) for the token"),
    expires_minutes: int = typer.Option(None, help="Override the default expiry"),
) -> None:
    """Issue a JWT bearer token for `subject`."""
    from app.core.security import create_access_token

    token = create_access_token(subject, expires_minutes=expires_minutes)
    console.print(token)


if __name__ == "__main__":
    app()
