"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type PersonRecord = {
  person_id: string;
  employee_id: string;
  full_name: string;
  department: string | null;
  is_active: boolean;
  enrollment_version: number;
  created_at: string;
  updated_at: string;
};

export type AttendanceRecord = {
  attendance_id: string;
  employee_id: string;
  punch_type: string;
  timestamp: string;
  similarity_score: number;
  threshold: number;
  client_device_id: string;
  pipeline_version: string;
  evidence_id: string;
  attendance_session_id: string | null;
};

export type ModelRecord = {
  model_id: string;
  model_version: string;
  artifact_sha256: string;
  artifact_path: string;
  license_name: string;
  source_url: string;
  permitted_use: string;
  preprocessing_id: string;
  active: boolean;
  registered_at: string;
};

export type HealthPayload = {
  status?: string;
  database?: unknown;
  threshold_status?: unknown;
  ready_for_attendance?: boolean;
  model_components?: Record<string, unknown>;
  [key: string]: unknown;
};

type ListPayload<T> = { items: T[]; limit: number; offset: number };
type ModelPayload = { runtime_components: Record<string, unknown>; registry: ModelRecord[] };

type AdminContextValue = {
  apiBase: string;
  setApiBase: (value: string) => void;
  apiKey: string;
  setApiKey: (value: string) => void;
  isConnected: boolean;
  connectionError: string | null;
  requestJson: <T>(path: string, init?: RequestInit) => Promise<T>;
  getHealth: () => Promise<HealthPayload>;
  connect: () => Promise<void>;
};

const AdminContext = createContext<AdminContextValue | null>(null);
const initialApiBase = process.env.NEXT_PUBLIC_FRS_API_BASE_URL || "http://127.0.0.1:8000";

export function AdminProvider({ children }: { children: ReactNode }) {
  const [apiBase, setApiBaseState] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        return window.sessionStorage.getItem("frs_api_base") || initialApiBase;
      } catch {
        return initialApiBase;
      }
    }
    return initialApiBase;
  });
  const [apiKey, setApiKeyState] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        return window.sessionStorage.getItem("frs_admin_key") || "";
      } catch {
        return "";
      }
    }
    return "";
  });
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const setApiKey = useCallback((value: string) => {
    setApiKeyState(value);
    try {
      if (value) {
        window.sessionStorage.setItem("frs_admin_key", value);
      } else {
        window.sessionStorage.removeItem("frs_admin_key");
      }
    } catch {
      // Ignore
    }
  }, []);

  const setApiBase = useCallback((value: string) => {
    setApiBaseState(value);
    setIsConnected(false);
    setConnectionError(null);
    try {
      if (value) {
        window.sessionStorage.setItem("frs_api_base", value);
      } else {
        window.sessionStorage.removeItem("frs_api_base");
      }
    } catch {
      // Ignore
    }
  }, []);

  const normalizedBase = apiBase.trim().replace(/\/+$/, "");

  const requestJson = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    if (!normalizedBase) throw new Error("Enter the FastAPI base URL first.");
    const headers = new Headers(init.headers);
    if (apiKey.trim()) headers.set("Authorization", `Bearer ${apiKey.trim()}`);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(`${normalizedBase}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
    const payload: unknown = await response.json().catch(() => ({ detail: "Server returned a non-JSON response." }));
    if (!response.ok) {
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? String((payload as { detail: unknown }).detail)
          : response.statusText;
      throw new Error(`HTTP ${response.status}: ${detail}`);
    }
    return payload as T;
  }, [normalizedBase, apiKey]);

  const getHealth = useCallback(async () => {
    if (!normalizedBase) throw new Error("Enter the FastAPI base URL first.");
    const response = await fetch(`${normalizedBase}/health`, { cache: "no-store" });
    const payload: unknown = await response.json().catch(() => ({ detail: "Backend returned a non-JSON response." }));
    if (!response.ok) {
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? String((payload as { detail: unknown }).detail)
          : response.statusText;
      throw new Error(`Health check failed: HTTP ${response.status}: ${detail}`);
    }
    return payload as HealthPayload;
  }, [normalizedBase]);

  const connect = useCallback(async () => {
    setConnectionError(null);
    try {
      if (!apiKey.trim()) throw new Error("Enter the administrator bearer key.");
      await requestJson<ListPayload<PersonRecord>>("/api/v1/admin/people?limit=1");
      setIsConnected(true);
    } catch (error) {
      setIsConnected(false);
      const message = error instanceof Error ? error.message : "Could not connect to the admin API.";
      setConnectionError(message);
      throw error;
    }
  }, [apiKey, requestJson]);

  const value = useMemo(() => ({
    apiBase,
    setApiBase,
    apiKey,
    setApiKey,
    isConnected,
    connectionError,
    requestJson,
    getHealth,
    connect,
  }), [apiBase, setApiBase, apiKey, setApiKey, isConnected, connectionError, requestJson, getHealth, connect]);

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
}

export function useAdmin() {
  const value = useContext(AdminContext);
  if (!value) throw new Error("useAdmin must be used within AdminProvider.");
  return value;
}

export type { ListPayload, ModelPayload };
