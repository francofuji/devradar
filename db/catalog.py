"""
Catálogo de event_type válidos del sistema.
emit_event() valida contra este set antes de escribir.
Para agregar un nuevo tipo: añadir aquí y documentar en CLAUDE.md.
"""

VALID_EVENT_TYPES: set[str] = {
    # Discovery
    "developer.discovered",
    "repository.discovered",

    # Activity — developer
    "developer.product_launched",
    "developer.article_published",
    "developer.job_changed",
    "developer.funding_announced",

    # Activity — repository
    "repo.stars_spiked",
    "repo.issue_count_changed",
    "repo.commit_detected",
    "repo.dependency_changed",
    "repo.release_published",
    "repo.topic_added",

    # Enrichment
    "enrichment.completed",
    "enrichment.failed",
    "enrichment.stack_updated",
    "enrichment.pain_signal_added",
    "enrichment.archetype_assigned",
    "enrichment.state_transition",
    "developer.architectural_reconfiguration",

    # Intent
    "developer.intent_threshold_crossed",

    # System / outreach
    "outreach.message_sent",
    "outreach.reply_received",
    "developer.disqualified",
    "developer.note_added",

    # Testing (solo en desarrollo)
    "test.event",
}

# Mapa event_type → event_category
EVENT_CATEGORIES: dict[str, str] = {
    "developer.discovered":                   "discovery",
    "repository.discovered":                  "discovery",
    "developer.product_launched":             "activity",
    "developer.article_published":            "activity",
    "developer.job_changed":                  "activity",
    "developer.funding_announced":            "activity",
    "repo.stars_spiked":                      "activity",
    "repo.issue_count_changed":               "activity",
    "repo.commit_detected":                   "activity",
    "repo.dependency_changed":                "activity",
    "repo.release_published":                 "activity",
    "repo.topic_added":                       "activity",
    "enrichment.completed":                   "enrichment",
    "enrichment.failed":                      "enrichment",
    "enrichment.stack_updated":               "enrichment",
    "enrichment.pain_signal_added":           "enrichment",
    "enrichment.archetype_assigned":          "enrichment",
    "enrichment.state_transition":            "enrichment",
    "developer.architectural_reconfiguration":"enrichment",
    "developer.intent_threshold_crossed":     "intent",
    "outreach.message_sent":                  "system",
    "outreach.reply_received":                "system",
    "developer.disqualified":                 "system",
    "developer.note_added":                   "system",
    "test.event":                             "system",
}


def validate_event_type(event_type: str) -> None:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(
            f"event_type '{event_type}' no está en el catálogo. "
            f"Agregar a db/catalog.py si es un tipo nuevo."
        )


def get_category(event_type: str) -> str:
    return EVENT_CATEGORIES.get(event_type, "system")
