import { get } from "./client";

export const fetchLlmLogs = (params = {}) =>
  get("/api/logs/llm", { params });

export const fetchLlmLogDetail = (id) =>
  get(`/api/logs/llm/${id}`);

export const fetchEnrichmentLogs = (params = {}) =>
  get("/api/logs/enrichment", { params });

export const fetchEventLogs = (params = {}) =>
  get("/api/logs/events", { params });

/**
 * Returns an EventSource connected to /api/logs/stream.
 * The caller owns the EventSource and must call .close() on cleanup.
 */
export function openLogStream(token) {
  const url = `/api/logs/stream${token ? `?token=${encodeURIComponent(token)}` : ""}`;
  return new EventSource(url);
}
