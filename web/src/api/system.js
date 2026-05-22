import { get, post, put } from "./client";

export function fetchHealth() {
  return get("/api/health");
}

export function fetchConfig() {
  return get("/api/config");
}

export function updateConfig(config) {
  return put("/api/config", { config });
}

export function fetchGithubRateLimit() {
  return get("/api/system/github-rate-limit");
}

export function fetchWorkerHealth() {
  return get("/api/system/worker-health");
}

export function fetchSystemMetrics() {
  return get("/api/system/metrics");
}

export function fetchTaxonomy(params = {}) {
  return get("/api/taxonomy", { params });
}

export function createTaxonomyPackage(name, definition) {
  return post(`/api/taxonomy/${encodeURIComponent(name)}`, definition);
}

export function updateTaxonomyPackage(name, definition) {
  return put(`/api/taxonomy/${encodeURIComponent(name)}`, definition);
}
