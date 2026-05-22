import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 30000,
});

apiClient.interceptors.request.use((config) => {
  const nextConfig = { ...config };
  if (API_TOKEN) {
    nextConfig.headers = {
      ...nextConfig.headers,
      Authorization: `Bearer ${API_TOKEN}`,
    };
  }
  return nextConfig;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error?.response?.data?.detail ||
      error?.response?.data?.error ||
      error?.message ||
      "Unknown API error";
    return Promise.reject(new Error(message));
  },
);

export async function get(url, config = {}) {
  const response = await apiClient.get(url, config);
  return response.data;
}

export async function post(url, data = {}, config = {}) {
  const response = await apiClient.post(url, data, config);
  return response.data;
}

export async function put(url, data = {}, config = {}) {
  const response = await apiClient.put(url, data, config);
  return response.data;
}

export function getApiBaseUrl() {
  return API_URL;
}

export function getApiToken() {
  return API_TOKEN;
}
