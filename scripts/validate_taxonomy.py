"""
Valida la integridad de taxonomy/dependencies.json.
Corre con: python scripts/validate_taxonomy.py
"""
import json
import sys
from pathlib import Path

VALID_CATEGORIES = {
    "ai_llm", "ai_framework", "ai_observability", "browser_automation",
    "testing", "payments", "auth", "database", "queues", "caching",
    "monitoring", "logging", "analytics", "email", "validation", "infra", "mcp"
}

VALID_ARCHETYPE_SIGNALS = {
    "solo_agent_builder", "automation_builder", "mcp_platform_builder",
    "technical_founder", "ai_agency_builder", "growth_engineer"
}

VALID_BUDGET_SIGNALS = {None, "possible", "confirmed"}

REQUIRED_FIELDS = {
    "category", "subcategory", "budget_signal",
    "archetype_signals", "maturity_modifier",
    "intent_weight", "scaling_signal", "pain_category",
    "runtime_only", "note"
}


def validate():
    taxonomy_path = Path("taxonomy/dependencies.json")
    if not taxonomy_path.exists():
        print("ERROR: taxonomy/dependencies.json no existe")
        sys.exit(1)

    with open(taxonomy_path) as f:
        data = json.load(f)

    packages = data.get("packages", {})
    errors = []
    warnings = []

    for pkg_name, pkg in packages.items():
        # Campos requeridos
        missing = REQUIRED_FIELDS - set(pkg.keys())
        if missing:
            errors.append(f"{pkg_name}: campos faltantes: {missing}")
            continue

        # Categoría válida
        if pkg["category"] not in VALID_CATEGORIES:
            errors.append(f"{pkg_name}: categoría inválida: {pkg['category']}")

        # Budget signal válido
        if pkg["budget_signal"] not in VALID_BUDGET_SIGNALS:
            errors.append(f"{pkg_name}: budget_signal inválido: {pkg['budget_signal']}")

        # Archetype signals válidos
        for sig in pkg.get("archetype_signals", []):
            if sig not in VALID_ARCHETYPE_SIGNALS:
                errors.append(f"{pkg_name}: archetype_signal inválido: {sig}")

        # intent_weight razonable
        if not 0 <= pkg.get("intent_weight", 0) <= 30:
            warnings.append(f"{pkg_name}: intent_weight fuera de rango 0-30: {pkg['intent_weight']}")

        # maturity_modifier razonable
        if not -10 <= pkg.get("maturity_modifier", 0) <= 15:
            warnings.append(f"{pkg_name}: maturity_modifier fuera de rango: {pkg['maturity_modifier']}")

    # Estadísticas
    total = len(packages)
    by_category = {}
    for pkg in packages.values():
        cat = pkg.get("category", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1

    with_budget = sum(1 for p in packages.values() if p.get("budget_signal"))
    with_archetype = sum(1 for p in packages.values() if p.get("archetype_signals"))
    with_intent = sum(1 for p in packages.values() if p.get("intent_weight", 0) > 0)
    scaling = sum(1 for p in packages.values() if p.get("scaling_signal"))

    print(f"\n📦 Taxonomía: {total} packages")
    print(f"\nDistribución por categoría:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat:25s} {count:3d}")

    print(f"\nCobertura de señales:")
    print(f"  Con budget_signal:    {with_budget:3d} ({with_budget/total*100:.0f}%)")
    print(f"  Con archetype_signal: {with_archetype:3d} ({with_archetype/total*100:.0f}%)")
    print(f"  Con intent_weight>0:  {with_intent:3d} ({with_intent/total*100:.0f}%)")
    print(f"  Con scaling_signal:   {scaling:3d} ({scaling/total*100:.0f}%)")

    if warnings:
        print(f"\n⚠️  {len(warnings)} warnings:")
        for w in warnings:
            print(f"  {w}")

    if errors:
        print(f"\n❌ {len(errors)} errores críticos:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"\n✅ Taxonomía válida. Sin errores críticos.")


if __name__ == "__main__":
    validate()
