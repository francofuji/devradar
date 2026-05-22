import { get, post } from "./client";

export function fetchEntities(params = {}) {
  return get("/api/entities", { params });
}

export function fetchEntity(handle) {
  return get(`/api/entities/${handle}`);
}

export function addEntityNote(handle, payload) {
  return post(`/api/entities/${handle}/note`, payload);
}

export function updateLinkedIn(handle, payload) {
  return post(`/api/entities/${handle}/linkedin`, payload);
}

export function disqualifyEntity(handle, payload) {
  return post(`/api/entities/${handle}/disqualify`, payload);
}

export function enqueueEnrichment(handle, payload) {
  return post(`/api/entities/${handle}/enrich`, payload);
}
