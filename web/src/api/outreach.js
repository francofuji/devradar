import { get, post } from "./client";

export function fetchOutreachQueue() {
  return get("/api/outreach/queue");
}

export function fetchDraft(handle) {
  return get(`/api/outreach/${handle}/draft`);
}

export function approveDraft(handle, payload) {
  return post(`/api/outreach/${handle}/draft/approve`, payload);
}

export function registerReply(handle, payload) {
  return post(`/api/outreach/${handle}/reply`, payload);
}
