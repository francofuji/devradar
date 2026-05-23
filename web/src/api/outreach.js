import { get, post } from "./client";

export function fetchOutreachQueue() {
  return get("/api/outreach/queue");
}

export function fetchDraft(handle) {
  return get(`/api/outreach/${handle}/draft`);
}

export function regenerateDraft(handle) {
  return post(`/api/outreach/${handle}/draft/regenerate`, {});
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
