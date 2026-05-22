import { get, post } from "./client";

export function fetchTrainingStats() {
  return get("/api/training/stats");
}

export function fetchTrainingExamples(params = {}) {
  return get("/api/training/examples", { params });
}

export function exportTraining(payload) {
  return post("/api/training/export", payload);
}

export function fetchLlmStatus() {
  return get("/api/llm/status");
}

export function fetchCacheStats() {
  return get("/api/llm/cache-stats");
}

export function fetchLlmModels() {
  return get("/api/llm/models");
}

export function testLlm(payload) {
  return post("/api/llm/test", payload);
}

export function fetchRegisteredModels() {
  return get("/api/training/models");
}

export function activateModel(modelId) {
  return post(`/api/training/models/${modelId}/activate`, {});
}

export function launchTraining(payload) {
  return post("/api/training/launch", payload);
}
