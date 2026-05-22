#!/usr/bin/env bash
# E9 — Schedule sugerido para operación desatendida.
#
# Instalación sugerida:
#   1. chmod +x cron/schedule.sh
#   2. Editar los horarios si hace falta.
#   3. Copiar las líneas CRON_SUGERIDO a tu crontab con: crontab -e
#   4. Verificar con: crontab -l
#
# Este script define helpers y muestra el crontab actual al final para
# confirmar instalación. Los jobs sugeridos activan el venv antes de cada
# comando, escriben logs diarios y usan `rtk` como proxy de comandos.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

activate_venv() {
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
}

run_logged() {
  local name="$1"
  shift
  activate_venv
  local day
  day="$(date -u +%Y-%m-%d)"
  local logfile="$LOG_DIR/${name}_${day}.log"
  {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START $name"
    rtk "$@"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END $name"
  } >>"$logfile" 2>&1
}

# Jobs disponibles para invocación manual:
#   bash cron/schedule.sh collectors
#   bash cron/schedule.sh trigger
#   bash cron/schedule.sh dispatcher
#   bash cron/schedule.sh scoring
#   bash cron/schedule.sh transitions
#   bash cron/schedule.sh digest
#   bash cron/schedule.sh weekly
#   bash cron/schedule.sh health

case "${1:-show}" in
  collectors)
    run_logged collectors python collectors/run_all.py --collector all
    ;;
  trigger)
    run_logged trigger python enrichment/trigger.py
    ;;
  dispatcher)
    run_logged dispatcher python enrichment/dispatcher.py --once
    ;;
  scoring)
    run_logged scoring python intelligence/score_entities.py
    ;;
  transitions)
    run_logged transitions python intelligence/detect_transitions.py
    ;;
  digest)
    run_logged digest python intelligence/generate_digest.py
    ;;
  weekly)
    run_logged weekly python intelligence/trend_analyzer.py
    ;;
  health)
    run_logged health python scripts/health_check.py
    ;;
  show)
    cat <<'EOF'
# CRON_SUGERIDO
# m h  dom mon dow   comando
0 */4 * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh collectors
15 * * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh trigger
20 * * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh dispatcher
10 2 * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh scoring
20 2 * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh transitions
0 7 * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh digest
0 8 * * 1 cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh weekly
0 * * * * cd /Users/francofuji/Projects/developers-crm && bash cron/schedule.sh health
EOF
    ;;
  *)
    echo "Uso: bash cron/schedule.sh [collectors|trigger|dispatcher|scoring|transitions|digest|weekly|health|show]" >&2
    exit 1
    ;;
esac

echo
echo "# CRONTAB_ACTUAL"
crontab -l 2>/dev/null || echo "(sin crontab instalado)"
