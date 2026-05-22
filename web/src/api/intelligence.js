import { get } from "./client";

export function fetchLatestDigest() {
  return get("/api/digest/latest");
}

export function fetchDigestByDate(date) {
  return get(`/api/digest/${date}`);
}

export function fetchAlerts() {
  return get("/api/alerts");
}

export function fetchLatestTrends() {
  return get("/api/trends/latest");
}

export function fetchEcosystemStats() {
  return get("/api/ecosystem/stats");
}
