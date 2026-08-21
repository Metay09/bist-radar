export type CachedRead<T> = {
  data: T;
  fetchedAt: number;
  snapshotId?: string;
  dataTimestamp?: string | null;
  sessionDate?: string;
};

const memory = new Map<string, CachedRead<unknown>>();
const inFlight = new Map<string, { promise: Promise<unknown>; controller: AbortController }>();
const generations = new Map<string, number>();
const SESSION_PREFIX = "bist-radar-read:";
const SESSION_TTL_MS = 8 * 60 * 60 * 1000;

const metadata = (value: unknown) => {
  const row = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    snapshotId: typeof row.snapshot_id === "string" ? row.snapshot_id : undefined,
    dataTimestamp: typeof row.data_timestamp === "string" ? row.data_timestamp : null,
  };
};

const sessionDay = (stamp?: string | null) => stamp
  ? new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul" }).format(new Date(stamp))
  : null;

const usable = (entry: CachedRead<unknown>) => {
  if (Date.now() - entry.fetchedAt > SESSION_TTL_MS) return false;
  return !entry.sessionDate || entry.sessionDate === sessionDay(new Date().toISOString());
};

export function readCached<T>(key: string): CachedRead<T> | undefined {
  const found = memory.get(key);
  if (found && usable(found)) return found as CachedRead<T>;
  try {
    const raw = sessionStorage.getItem(`${SESSION_PREFIX}${key}`);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as CachedRead<T>;
    if (!usable(parsed)) {
      sessionStorage.removeItem(`${SESSION_PREFIX}${key}`);
      return undefined;
    }
    memory.set(key, parsed);
    return parsed;
  } catch {
    return undefined;
  }
}

function writeCached<T>(key: string, data: T, generation: number): CachedRead<T> {
  const currentGeneration = generations.get(key) || 0;
  const existing = memory.get(key);
  const nextMeta = metadata(data);
  const existingTime = existing?.dataTimestamp ? Date.parse(existing.dataTimestamp) : 0;
  const nextTime = nextMeta.dataTimestamp ? Date.parse(nextMeta.dataTimestamp) : 0;
  if (generation < currentGeneration || (existingTime && nextTime && nextTime < existingTime)) {
    return existing as CachedRead<T>;
  }
  generations.set(key, generation);
  const entry = {
    data, fetchedAt: Date.now(), ...nextMeta,
    sessionDate: sessionDay(new Date().toISOString()) || undefined,
  };
  memory.set(key, entry);
  try { sessionStorage.setItem(`${SESSION_PREFIX}${key}`, JSON.stringify(entry)); } catch { /* memory cache remains valid */ }
  return entry;
}

export function cachedRequest<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  supersede = false,
): Promise<CachedRead<T>> {
  const active = inFlight.get(key);
  if (active && !supersede) return active.promise as Promise<CachedRead<T>>;
  if (active) active.controller.abort();
  const generation = (generations.get(key) || 0) + 1;
  generations.set(key, generation);
  const controller = new AbortController();
  const request = load(controller.signal)
    .then((data) => writeCached(key, data, generation))
    .finally(() => {
      if (inFlight.get(key)?.promise === request) inFlight.delete(key);
    });
  inFlight.set(key, { promise: request, controller });
  return request;
}

export function clearReadCacheForTests() {
  memory.clear();
  inFlight.clear();
  generations.clear();
}
