"""
Tipos canónicos del sistema de inteligencia de developers.

REGLA: este es el único lugar donde se definen dataclasses y enums.
Importar desde aquí en todos los demás módulos.
Nunca redefinir estas estructuras en otros archivos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── Enums ─────────────────────────────────────────────────────


class Archetype(str, Enum):
    SOLO_AGENT_BUILDER   = "solo_agent_builder"
    AUTOMATION_BUILDER   = "automation_builder"
    MCP_PLATFORM_BUILDER = "mcp_platform_builder"
    TECHNICAL_FOUNDER    = "technical_founder"
    AI_AGENCY_BUILDER    = "ai_agency_builder"
    GROWTH_ENGINEER      = "growth_engineer"
    UNKNOWN              = "unknown"


class PainCategory(str, Enum):
    API_COST      = "api_cost"
    SCALING       = "scaling"
    AUTH          = "auth"
    OBSERVABILITY = "observability"
    RELIABILITY   = "reliability"


class MaturityTier(str, Enum):
    PROTOTYPE    = "prototype"     # 0–25 pts
    EARLY        = "early"         # 26–45 pts
    INTERMEDIATE = "intermediate"  # 46–65 pts
    PRODUCTION   = "production"    # 66–80 pts
    SCALE_READY  = "scale_ready"   # 81–100 pts

    @classmethod
    def from_score(cls, score: float) -> "MaturityTier":
        if score <= 25:
            return cls.PROTOTYPE
        elif score <= 45:
            return cls.EARLY
        elif score <= 65:
            return cls.INTERMEDIATE
        elif score <= 80:
            return cls.PRODUCTION
        else:
            return cls.SCALE_READY


class IntentTier(str, Enum):
    HOT     = "hot"      # >= 60
    WARM    = "warm"     # 40–59
    COLD    = "cold"     # 20–39
    MONITOR = "monitor"  # < 20

    @classmethod
    def from_score(cls, score: float) -> "IntentTier":
        if score >= 60:
            return cls.HOT
        elif score >= 40:
            return cls.WARM
        elif score >= 20:
            return cls.COLD
        else:
            return cls.MONITOR


class DeveloperStatus(str, Enum):
    DISCOVERED  = "DISCOVERED"
    PROFILED    = "PROFILED"
    MONITORED   = "MONITORED"
    WARM        = "WARM"
    QUALIFIED   = "QUALIFIED"
    OUTREACHED  = "OUTREACHED"
    ENGAGED     = "ENGAGED"
    CLOSED      = "CLOSED"


class TrajectoryDirection(str, Enum):
    ACCELERATING  = "accelerating"   # 7d > 30d > 0
    STEADY_RISING = "steady_rising"  # 30d > 0, consistent
    PLATEAU       = "plateau"        # velocity near 0, score > 50
    DECLINING     = "declining"      # negative velocity
    SPIKE_AND_FALL = "spike_and_fall"  # high 7d, low 30d
    INSUFFICIENT_DATA = "insufficient_data"


class ProductType(str, Enum):
    WEB_APP   = "web_app"
    LIBRARY   = "library"
    CLI       = "cli"
    AGENT     = "agent"
    API       = "api"
    MOBILE    = "mobile"
    FRAMEWORK = "framework"
    PLUGIN    = "plugin"
    UNKNOWN   = "unknown"


class EnrichmentType(str, Enum):
    FULL         = "full"
    PARTIAL      = "partial"
    PAIN_CHECK   = "pain_check"
    README_ONLY  = "readme_only"


# ── Core data structures ───────────────────────────────────────


@dataclass
class StackSnapshot:
    """
    Resultado del análisis heurístico de archivos de dependencias.
    Producido por enrichment/dependency_parser.py.
    """
    primary_language:    Optional[str]       = None
    secondary_languages: list[str]           = field(default_factory=list)

    # Dependencias de runtime clasificadas por categoría
    runtime_deps: dict[str, list[str]] = field(default_factory=lambda: {
        "ai_llm":             [],
        "ai_framework":       [],
        "browser_automation": [],
        "database":           [],
        "payments":           [],
        "auth":               [],
        "queues":             [],
        "monitoring":         [],
        "logging":            [],
        "analytics":          [],
        "email":              [],
        "http_client":        [],
        "validation":         [],
        "infra":              [],
    })

    # Dependencias de desarrollo
    dev_deps: dict[str, list[str]] = field(default_factory=lambda: {
        "testing": [],
        "linting": [],
        "bundler": [],
    })

    # Packages no encontrados en la taxonomía — revisar manualmente
    unclassified: list[str] = field(default_factory=list)

    # Señales derivadas del stack
    budget_signals:    list[str] = field(default_factory=list)
    archetype_signals: list[str] = field(default_factory=list)
    scaling_signals:   list[str] = field(default_factory=list)
    pain_signals:      list[str] = field(default_factory=list)

    maturity_modifier: int = 0  # puntos extra/menos al maturity score

    # Metadata del archivo analizado
    file_found:    Optional[str] = None  # package.json|requirements.txt|pyproject.toml
    raw_count:     int           = 0     # total de dependencias encontradas

    def has_payments(self) -> bool:
        return len(self.runtime_deps.get("payments", [])) > 0

    def has_auth(self) -> bool:
        return len(self.runtime_deps.get("auth", [])) > 0

    def has_queues(self) -> bool:
        return len(self.runtime_deps.get("queues", [])) > 0

    def has_monitoring(self) -> bool:
        return len(self.runtime_deps.get("monitoring", [])) > 0

    def has_tests(self) -> bool:
        return len(self.dev_deps.get("testing", [])) > 0

    def has_ai(self) -> bool:
        return (
            len(self.runtime_deps.get("ai_llm", [])) > 0
            or len(self.runtime_deps.get("ai_framework", [])) > 0
        )

    def has_automation(self) -> bool:
        return len(self.runtime_deps.get("browser_automation", [])) > 0

    def taxonomy_coverage(self) -> float:
        """Fracción de packages clasificados. < 0.8 indica taxonomía incompleta."""
        total = self.raw_count
        if total == 0:
            return 1.0
        unclassified = len(self.unclassified)
        return (total - unclassified) / total


@dataclass
class PainSignal:
    """
    Señal de dolor técnico con evidencia explícita obligatoria.

    INVARIANTE: evidence nunca puede ser vacío ni None.
    Si no hay evidencia, no se crea el objeto.
    """
    category:     PainCategory
    description:  str
    evidence:     str           # cita directa o file+line. OBLIGATORIO.
    evidence_source: str        # github_issue|readme|dependency_combination|commit
    confidence:   float         # 0.0–1.0

    corroborating_signals: list[str] = field(default_factory=list)
    signal_age_days:       Optional[int] = None

    def __post_init__(self) -> None:
        if not self.evidence or not self.evidence.strip():
            raise ValueError(
                f"PainSignal.evidence es obligatorio. "
                f"Categoría: {self.category}. "
                f"No crear PainSignal sin evidencia explícita."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"PainSignal.confidence debe ser 0.0–1.0, "
                f"recibido: {self.confidence}"
            )

    @property
    def is_usable(self) -> bool:
        """True si la señal supera el umbral mínimo de confianza."""
        return self.confidence >= 0.6


@dataclass
class ArchetypeResult:
    """
    Resultado de la clasificación de arquetipo.
    Producido por enrichment/archetype_classifier.py.
    """
    primary:   Archetype
    confidence: float

    secondary:             Optional[Archetype] = None
    classification_method: str                 = "heuristic"
    # heuristic | llm_disambiguated
    signals_used:          list[str]           = field(default_factory=list)
    reasoning:             Optional[str]       = None  # solo cuando llm_disambiguated

    @property
    def is_confident(self) -> bool:
        """True si no necesitó LLM para clasificar."""
        return self.confidence >= 0.75


@dataclass
class MaturityResult:
    """
    Score y tier de madurez técnica.
    Producido por enrichment/dependency_parser.py (compute_maturity_score).
    """
    score: int
    tier:  MaturityTier

    # Señales individuales
    has_tests:              bool = False
    has_e2e_tests:          bool = False
    has_type_safety:        bool = False
    has_observability:      bool = False
    has_ci_cd:              bool = False
    has_deploy_step:        bool = False
    has_multi_env:          bool = False
    has_docker:             bool = False
    has_payments:           bool = False
    has_auth:               bool = False
    has_analytics:          bool = False
    is_actively_maintained: bool = False

    last_commit_days_ago:    Optional[int] = None
    release_frequency_days:  Optional[int] = None
    contributors_count:      int           = 1

    # Desglose de puntos para debugging
    breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def is_targetable(self) -> bool:
        """
        True si la madurez sugiere que el developer tiene presupuesto
        y puede tomar decisiones de herramientas. Sweet spot: 46–80 pts.
        """
        return 46 <= self.score <= 80


@dataclass
class IssueData:
    """
    Datos de un issue de GitHub para análisis de pain signals.
    """
    number:         int
    title:          str
    labels:         list[str]
    created_at:     str
    updated_at:     str
    comments_count: int
    has_linked_pr:  bool
    url:            str

    @property
    def age_days(self) -> int:
        from datetime import datetime, timezone
        try:
            created = datetime.fromisoformat(
                self.created_at.replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)
            return (now - created).days
        except Exception:
            return 0

    @property
    def is_stale(self) -> bool:
        """Issue abierto sin PR vinculado por más de 30 días."""
        return self.age_days > 30 and not self.has_linked_pr


@dataclass
class RepoProfile:
    """
    Perfil completo de un repositorio fetched desde GitHub API.
    Producido por enrichment/github_profile.py.
    """
    full_name:        str
    owner:            str
    primary_language: Optional[str]
    topics:           list[str]
    description:      Optional[str]
    homepage:         Optional[str]
    stars:            int
    forks:            int
    open_issues_count: int
    last_push:        Optional[str]
    created_at:       str

    # Archivos de infraestructura presentes
    has_ci:                bool = False
    has_docker:            bool = False
    has_env_example:       bool = False
    has_changelog:         bool = False
    has_docs_folder:       bool = False
    has_contributing:      bool = False
    has_readme:            bool = False

    # Servicios detectados en .env.example
    env_example_services:  list[str] = field(default_factory=list)

    # Issues fetched
    open_issues:           list[IssueData] = field(default_factory=list)

    # Contenido de README (si se fetched)
    readme_content:        Optional[str] = None
    readme_word_count:     int           = 0

    @property
    def is_active(self) -> bool:
        """Tuvo actividad en los últimos 30 días."""
        if not self.last_push:
            return False
        from datetime import datetime, timezone
        try:
            pushed = datetime.fromisoformat(
                self.last_push.replace("Z", "+00:00")
            )
            days = (datetime.now(timezone.utc) - pushed).days
            return days <= 30
        except Exception:
            return False


@dataclass
class ReadmeIntel:
    """
    Inteligencia extraída del README por LLM.
    Producido por enrichment/readme_extractor.py.
    IMPORTANTE: todos los campos son Optional — nunca fabricar valores.
    """
    product_type:         Optional[ProductType] = None
    target_user:          Optional[str]         = None
    pain_solved:          Optional[str]         = None
    limitations:          list[str]             = field(default_factory=list)
    roadmap_items:        list[str]             = field(default_factory=list)
    has_demo:             bool                  = False
    readme_quality_score: int                   = 0  # 0–10, LLM-rated

    # Evidencia que justifica cada claim no-null
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return any([
            self.product_type is not None,
            self.target_user is not None,
            self.pain_solved is not None,
            len(self.limitations) > 0,
        ])


@dataclass
class OutreachContext:
    """
    Contexto y recomendaciones para generación de outreach.
    Producido como último paso del pipeline de enriquecimiento.
    """
    recommended_angle:  str        # e.g. "api_cost_reduction"
    specific_hooks:     list[str]  = field(default_factory=list)
    vocabulary_to_use:  list[str]  = field(default_factory=list)
    vocabulary_to_avoid: list[str] = field(default_factory=list)
    channel_priority:   list[str]  = field(default_factory=lambda: ["email"])
    tone:               str        = "peer_technical"
    # peer_technical | founder_to_founder | educational

    @property
    def has_hooks(self) -> bool:
        return len(self.specific_hooks) > 0


@dataclass
class EntityMemory:
    """
    Objeto de memoria persistido en entity_memory.memory.
    Resume el estado accionable más reciente de una entidad.
    """
    narrative: str
    stack_history: list[dict] = field(default_factory=list)
    confirmed_pain_signals: list[dict] = field(default_factory=list)
    transitions_observed: list[dict] = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    contact_history: list[dict] = field(default_factory=list)
    recommended_angle: str = "monitor"
    specific_hooks: list[str] = field(default_factory=list)
    operator_notes: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    """
    Resultado completo de un ciclo de enriquecimiento.
    Contiene todos los sub-resultados y metadata de la ejecución.
    """
    developer_id: str

    # Sub-resultados (None si no se pudo obtener)
    stack:            Optional[StackSnapshot]   = None
    repo_profile:     Optional[RepoProfile]     = None
    maturity:         Optional[MaturityResult]  = None
    pain_signals:     list[PainSignal]          = field(default_factory=list)
    archetype:        Optional[ArchetypeResult] = None
    readme_intel:     Optional[ReadmeIntel]     = None
    outreach_context: Optional[OutreachContext] = None

    # Metadata de ejecución
    llm_calls_made:     int       = 0
    input_tokens_used:  int       = 0
    output_tokens_used: int       = 0
    sources_fetched:    list[str] = field(default_factory=list)
    sources_failed:     list[str] = field(default_factory=list)
    overall_confidence: float     = 0.0
    enrichment_type:    str       = "full"

    @property
    def ready_for_outreach(self) -> bool:
        """
        True si el enriquecimiento es suficiente para generar outreach.
        Requiere: archetype con confidence >= 0.6 + al menos 1 pain signal usable.
        """
        has_archetype = (
            self.archetype is not None
            and self.archetype.confidence >= 0.6
            and self.archetype.primary != Archetype.UNKNOWN
        )
        has_pain = any(s.is_usable for s in self.pain_signals)
        return has_archetype and has_pain

    @property
    def usable_pain_signals(self) -> list[PainSignal]:
        """Solo señales que superan el umbral de confianza."""
        return [s for s in self.pain_signals if s.is_usable]

    def estimated_cost_usd(self) -> float:
        """Costo estimado de LLM para este enriquecimiento (Haiku pricing)."""
        return (
            (self.input_tokens_used / 1000 * 0.00025)
            + (self.output_tokens_used / 1000 * 0.00125)
        )
