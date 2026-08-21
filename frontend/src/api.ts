import type {
  Candidate,
  Detail,
  Outcome,
  OpportunityReadModel,
  PaperTrade,
  Signal,
  Summary,
  TradePlan,
} from "./types";
const get = async <T>(path: string, signal?: AbortSignal): Promise<T> => {
  const response = await fetch(`/api${path}`, { signal });
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json() as Promise<T>;
};
export const api = {
  summary: () => get<Summary>("/dashboard/summary"),
  universe: () => get<Record<string, unknown>>("/universe/summary"),
  candidates: () => get<Candidate[]>("/dashboard/candidates"),
  tradePlans: () => get<TradePlan[]>("/dashboard/trade-plans"),
  opportunities: (signal?: AbortSignal) => get<OpportunityReadModel>("/dashboard/opportunities", signal),
  snapshotStatus: (signal?: AbortSignal) => get<import("./types").SnapshotStatus>("/dashboard/snapshot-status", signal),
  tradePlan: (s: string) => get<TradePlan>(`/symbols/${s}/trade-plan`),
  detail: (s: string) => get<Detail>(`/symbols/${s}/detail`),
  adaptive: (s: string) =>
    get<Record<string, unknown>>(`/symbols/${s}/adaptive-decision`),
  adaptiveAnalytics: () => get<Record<string, unknown>>("/analytics/adaptive"),
  signals: (query = "") => get<Signal[]>(`/signals/history${query}`),
  daily: () => get<Record<string, unknown>[]>("/signals/daily-summary"),
  symbolResults: (s: string) => get<Signal[]>(`/symbols/${s}/results`),
  symbolShadow: (s: string) =>
    get<Record<string, unknown>>(`/symbols/${s}/shadow-status`),
  latestSymbolShadow: (s: string) =>
    get<Record<string, unknown>>(`/symbols/${s}/latest-shadow-prediction`),
  outcomes: () => get<Outcome[]>("/signals/outcomes"),
  trades: () => get<PaperTrade[]>("/paper/trades"),
  performance: () => get<Record<string, unknown>>("/performance/summary"),
  accuracy: () => get<Record<string, unknown>[]>("/analytics/scores"),
  ml: () => get<Record<string, unknown>>("/shadow/status"),
  evidence: () => get<Record<string, unknown>>("/research/evidence"),
  researchDaily: () => get<Record<string, unknown>[]>("/research/daily"),
  researchWeekly: () => get<Record<string, unknown>[]>("/research/weekly"),
  system: () => get<Record<string, unknown>>("/system/overview"),
};
