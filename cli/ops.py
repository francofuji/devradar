"""
E9 — CLI operacional para el sistema de inteligencia.
"""
from __future__ import annotations

import json
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_this_dir)
sys.path.insert(0, _project_root)

from datetime import datetime, timezone

import click

from db.events import emit_event
from db import db_cursor
from db.memory_queries import get_latest_memory
from db.queries import (
    get_active_signals,
    get_developer,
    get_primary_repo_by_owner,
    update_developer_profile_fields,
    update_developer_status,
)
from enrichment.full_enrichment import run_full_enrichment
from enrichment.memory_writer import update_memory_on_event
from enrichment.partial_enrichment import run_partial_enrichment


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_developer(entity: str):
    developer = get_developer(entity)
    if developer is None:
        raise click.ClickException(f"Developer no encontrado: {entity}")
    return developer


def _render_block(title: str, lines: list[str]) -> None:
    click.echo(title)
    for line in lines:
        click.echo(line)
    click.echo()


def _memory_or_fail(entity: str) -> dict:
    memory = get_latest_memory(entity)
    if not memory:
        raise click.ClickException(f"No hay memoria activa para {entity}")
    return memory


@click.group(help="CLI operacional para inspección, notas, outreach y re-enrichment.")
def cli() -> None:
    pass


@cli.command(help="Muestra un resumen legible de una entidad.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
def show(entity: str) -> None:
    developer = _require_developer(entity)
    memory = get_latest_memory(entity)
    signals = get_active_signals(entity)

    summary_lines = [
        f"Entity: {developer['id']}",
        f"Status: {developer['status']}",
        f"Intent score: {developer['intent_score']}",
        f"Maturity score: {developer['maturity_score']}",
        f"Trajectory: {developer['trajectory_direction'] or 'n/a'}",
        f"Archetype: {developer['archetype'] or 'n/a'}",
        f"Last active: {developer['last_active'] or 'n/a'}",
        f"Outreach status: {developer['outreach_status']}",
    ]
    _render_block("Summary", summary_lines)

    pain_lines: list[str] = []
    if memory:
        for item in (memory.get("confirmed_pain_signals") or [])[:3]:
            pain_lines.append(
                f"- {item.get('category')}: {item.get('description')} | evidence: {item.get('evidence')}"
            )
    if not pain_lines:
        pain_lines = [
            f"- {row['category']} / {row['signal_type']} | evidence: {row['evidence'] or 'n/a'}"
            for row in signals[:3]
        ] or ["- Sin pain signals o señales activas recientes"]
    _render_block("Pain Signals", pain_lines)

    narrative = (
        (memory or {}).get("narrative")
        or (memory or {}).get("_summary")
        or "Sin narrativa disponible"
    )
    _render_block("Narrative", [narrative])

    hooks = (memory or {}).get("specific_hooks") or []
    _render_block("Specific Hooks", [f"- {hook}" for hook in hooks] or ["- Sin hooks específicos"])


@cli.command(help="Agrega una nota del operador y versiona memoria.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
@click.option("--text", required=True, help="Texto de la nota.")
def note(entity: str, text: str) -> None:
    _require_developer(entity)
    emit_event(
        "developer.note_added",
        entity,
        "developer",
        {"text": text},
        source="manual",
        source_url=f"cli://note/{entity}/{_now_iso()}",
    )
    version = update_memory_on_event(entity, "developer.note_added", {"text": text})
    if version is None:
        raise click.ClickException(f"No se pudo actualizar la memoria para {entity}")
    click.echo(f"Nota agregada. Memoria actualizada a v{version}.")


@cli.command(help="Captura contexto manual de LinkedIn para una entidad.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
def linkedin(entity: str) -> None:
    _require_developer(entity)
    title = click.prompt("Job title")
    company = click.prompt("Company")
    team_size = click.prompt("Team size", type=click.Choice(["1", "2-5", "6-20", "21-50", "50+"]))
    notes = click.prompt("Notes", default="", show_default=False)
    payload = {
        "title": title,
        "company": company,
        "team_size": team_size,
        "notes": notes,
        "updated_at": _now_iso(),
    }
    update_developer_profile_fields(entity, linkedin_manual=payload, last_active=_now_iso())
    click.echo("LinkedIn manual actualizado.")


@cli.command(help="Marca una entidad como descalificada y registra la razón.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
@click.option("--reason", required=True, help="Razón de descalificación.")
def disqualify(entity: str, reason: str) -> None:
    _require_developer(entity)
    update_developer_profile_fields(
        entity,
        outreach_status="disqualified",
        status="CLOSED",
        last_active=_now_iso(),
    )
    emit_event(
        "developer.disqualified",
        entity,
        "developer",
        {"reason": reason},
        source="manual",
        source_url=f"cli://disqualify/{entity}/{_now_iso()}",
    )
    version = update_memory_on_event(entity, "developer.disqualified", {"reason": reason})
    click.echo(
        f"Entidad descalificada. Memoria {'actualizada a v' + str(version) if version else 'sin memoria activa'}."
    )


@cli.command(help="Registra que se envió outreach por un canal determinado.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
@click.option("--channel", required=True, type=click.Choice(["email", "twitter", "linkedin"]))
def outreach(entity: str, channel: str) -> None:
    _require_developer(entity)
    payload = {
        "channel": channel,
        "draft_id": f"{entity}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    }
    update_developer_profile_fields(
        entity,
        outreach_status="sent",
        status="OUTREACHED",
        last_active=_now_iso(),
    )
    emit_event(
        "outreach.message_sent",
        entity,
        "developer",
        payload,
        source="manual",
        source_url=f"cli://outreach/{entity}/{channel}/{_now_iso()}",
    )
    version = update_memory_on_event(entity, "outreach.message_sent", payload)
    click.echo(
        f"Outreach registrado por {channel}. Memoria {'actualizada a v' + str(version) if version else 'sin memoria activa'}."
    )


@cli.command(help="Registra una reply y actualiza estado/memoria.")
@click.option("--entity", required=True, help="GitHub handle del developer.")
@click.option("--outcome", required=True, type=click.Choice(["positive", "negative", "neutral"]))
@click.option("--notes", required=True, help="Notas de la reply.")
def reply(entity: str, outcome: str, notes: str) -> None:
    _require_developer(entity)
    status = "ENGAGED" if outcome == "positive" else None
    update_developer_profile_fields(
        entity,
        outreach_status="replied",
        status=status,
        last_active=_now_iso(),
    )
    payload = {
        "outcome": outcome,
        "notes": notes,
    }
    emit_event(
        "outreach.reply_received",
        entity,
        "developer",
        payload,
        source="manual",
        source_url=f"cli://reply/{entity}/{outcome}/{_now_iso()}",
    )
    version = update_memory_on_event(entity, "outreach.reply_received", payload)
    click.echo(
        f"Reply registrada ({outcome}). Memoria {'actualizada a v' + str(version) if version else 'sin memoria activa'}."
    )


@cli.command(help="Ejecuta enriquecimiento inmediato sin pasar por la queue.")
@click.option("--entity", required=True, help="GitHub handle del developer o owner/repo.")
@click.option("--mode", required=True, type=click.Choice(["full", "partial"]))
def enrich(entity: str, mode: str) -> None:
    click.echo(f"Enrichment requested | entity={entity} mode={mode}")
    if mode == "full":
        result = run_full_enrichment(entity)
        click.echo(
            "Full enrichment finished | "
            f"developer={result.developer_id} "
            f"sources_fetched={len(result.sources_fetched)} "
            f"pain_signals={len(result.pain_signals)} "
            f"archetype={result.archetype.primary.value if result.archetype else 'n/a'}"
        )
        return

    repo = get_primary_repo_by_owner(entity.split("/")[0] if "/" in entity else entity)
    partial_target = repo["id"] if repo else entity
    ok = run_partial_enrichment(partial_target, "manual.partial")
    if not ok:
        raise click.ClickException(f"Partial enrichment falló para {partial_target}")
    click.echo(f"Partial enrichment finished | target={partial_target}")


@cli.command(name="training-stats", help="Muestra estadísticas de ejemplos de fine-tuning.")
def training_stats() -> None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                task_type,
                COUNT(*) AS total_examples,
                COUNT(*) FILTER (WHERE COALESCE(quality_score, 0) >= 0.7) AS high_quality_examples,
                AVG(CASE WHEN was_edited THEN 1.0 ELSE 0.0 END) AS avg_edit_rate
            FROM fine_tuning_examples
            GROUP BY task_type
            ORDER BY task_type
            """
        )
        rows = cur.fetchall()

        cur.execute(
            """
            SELECT COUNT(*) AS total_examples
            FROM fine_tuning_examples
            WHERE COALESCE(quality_score, 0) >= 0.7
            """
        )
        total_high_quality = int(cur.fetchone()["total_examples"])

    if not rows:
        click.echo("No hay ejemplos de fine-tuning todavía.")
        click.echo("ETA hacia 150 ejemplos: faltan 150 ejemplos de calidad.")
        return

    _render_block(
        "Training Stats",
        [
            (
                f"- {row['task_type']}: total={row['total_examples']} "
                f"quality>=0.7={row['high_quality_examples']} "
                f"edit_rate_promedio={float(row['avg_edit_rate'] or 0.0):.2%}"
            )
            for row in rows
        ],
    )

    remaining = max(0, 150 - total_high_quality)
    click.echo(f"Ejemplos de calidad acumulados: {total_high_quality}")
    click.echo(f"ETA hacia 150 ejemplos: faltan {remaining} ejemplos de calidad.")


if __name__ == "__main__":
    cli()
