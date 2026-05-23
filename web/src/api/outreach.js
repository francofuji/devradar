import { get, post } from "./client";

export function fetchOutreachQueue() {
  return get("/api/outreach/queue");
}

export function fetchContacted() {
  return get("/api/outreach/contacted");
}

export function fetchDraft(handle) {
  return get(`/api/outreach/${handle}/draft`, { timeout: 120000 });
}

export function regenerateDraft(handle) {
  return post(`/api/outreach/${handle}/draft/regenerate`, {}, { timeout: 120000 });
}

export function approveDraft(handle, payload) {
  return post(`/api/outreach/${handle}/draft/approve`, payload);
}

export function registerReply(handle, payload) {
  return post(`/api/outreach/${handle}/reply`, payload);
}

export function fetchDraftPrompt(handle) {
  return get(`/api/outreach/${handle}/draft/prompt`);
}
