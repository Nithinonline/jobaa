import type { Dashboard, Job, ProfileData, ProfileResponse, Resume, User } from "./types";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const TOKEN_KEY = "jobaa_token";

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  signup: (username: string, email: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({ username, email, password }),
    }),
  me: () => request<User>("/api/auth/me"),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  profile: () => request<ProfileResponse>("/api/profile"),
  saveProfile: (profile: ProfileData) =>
    request<ProfileResponse>("/api/profile", {
      method: "PUT",
      body: JSON.stringify({ profile }),
    }),
  importProfile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ProfileResponse>("/api/profile/import", { method: "POST", body });
  },
  resumes: () => request<Resume[]>("/api/resumes"),
  jobs: (status?: string) => request<Job[]>(`/api/jobs${status ? `?status=${status}` : ""}`),
  updateJob: (id: number, status: Job["status"]) =>
    request<{ status: string }>(`/api/jobs/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  searchJobs: (options: { location: string; remote_only: boolean; max_age_days: number; top_n: number }) =>
    request<{ results: Job[]; source_errors: string[]; fallback_note: string | null }>("/api/jobs/search", {
      method: "POST",
      body: JSON.stringify(options),
    }),
};

export async function streamTailor(
  fields: { jd_text: string; jd_title: string; jd_url: string; file: File | null },
  onProgress: (value: Record<string, { status: string; detail: string }>) => void,
): Promise<Record<string, unknown>> {
  const token = getToken();
  const body = new FormData();
  body.append("jd_text", fields.jd_text);
  body.append("jd_title", fields.jd_title);
  body.append("jd_url", fields.jd_url);
  if (fields.file) body.append("file", fields.file);
  const response = await fetch(`${API_URL}/api/tailor`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(result?.detail || `Request failed (${response.status})`);
  }
  if (!response.body) throw new Error("Your browser could not open the progress stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Record<string, unknown> | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() || "";
    for (const message of messages) {
      const line = message.split("\n").find((part) => part.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6)) as {
        type: string;
        data?: Record<string, unknown> & Record<string, { status: string; detail: string }>;
        message?: string;
      };
      if (event.type === "progress" && event.data) onProgress(event.data);
      if (event.type === "error") throw new Error(event.message || "Resume tailoring failed.");
      if (event.type === "complete" && event.data) result = event.data;
    }
    if (done) break;
  }
  if (!result) throw new Error("The tailoring service ended without returning a resume.");
  return result;
}

export async function downloadResume(id: number, format: "md" | "pdf" | "docx") {
  const token = getToken();
  const response = await fetch(`${API_URL}/api/resumes/${id}/download?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1] || `resume.${format}`;
  link.click();
  URL.revokeObjectURL(link.href);
}
