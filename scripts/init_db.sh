#!/usr/bin/env bash
set -e

echo "Esperando PostgreSQL..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-devint}"; do
  sleep 1
done

echo "PostgreSQL listo. Corriendo migración..."
python db/migrate.py
echo "✅ Base de datos inicializada."
