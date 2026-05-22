import { create } from "zustand";
import { fetchEcosystemStats } from "../api/intelligence";
import {
  fetchHealth as apiFetchHealth,
  fetchGithubRateLimit as apiFetchGithubRateLimit,
  fetchWorkerHealth as apiFetchWorkerHealth,
} from "../api/system";
import {
  fetchCacheStats as apiFetchCacheStats,
  fetchLlmStatus as apiFetchLlmStatus,
} from "../api/training";

const useSystemStore = create((set) => ({
  health: null,
  stats: null,
  isLoading: false,
  async fetchHealth() {
    set({ isLoading: true });
    try {
      const health = await apiFetchHealth();
      set({ health, isLoading: false });
      return health;
    } catch {
      set({ isLoading: false });
      return null;
    }
  },
  async fetchStats() {
    set({ isLoading: true });
    const [ecosystem, cache, worker, llm, githubRate] = await Promise.allSettled([
      fetchEcosystemStats(),
      apiFetchCacheStats(),
      apiFetchWorkerHealth(),
      apiFetchLlmStatus(),
      apiFetchGithubRateLimit(),
    ]);
    const resolve = (r) => (r.status === "fulfilled" ? r.value : null);
    const stats = {
      ecosystem: resolve(ecosystem),
      cache: resolve(cache),
      worker: resolve(worker),
      llm: resolve(llm),
      githubRate: resolve(githubRate),
    };
    set({ stats, isLoading: false });
    return stats;
  },
}));

export default useSystemStore;
