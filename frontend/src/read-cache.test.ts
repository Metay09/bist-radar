import { beforeEach, describe, expect, it } from "vitest";
import { cachedRequest, clearReadCacheForTests, readCached } from "./read-cache";

beforeEach(() => {
  sessionStorage.clear();
  clearReadCacheForTests();
});

describe("snapshot read cache", () => {
  it("deduplicates concurrent reads for the same resource", async () => {
    let calls = 0;
    const load = async () => { calls += 1; return { value: 1 }; };
    const [first, second] = await Promise.all([
      cachedRequest("radar", load),
      cachedRequest("radar", load),
    ]);
    expect(calls).toBe(1);
    expect(first.data).toEqual(second.data);
  });

  it("keeps the newest snapshot when an older response finishes later", async () => {
    let releaseOld!: (value: { snapshot_id: string; data_timestamp: string }) => void;
    const old = new Promise<{ snapshot_id: string; data_timestamp: string }>((resolve) => { releaseOld = resolve; });
    const first = cachedRequest("radar", () => old);
    const newer = await cachedRequest("radar", async () => ({
      snapshot_id: "B", data_timestamp: "2026-08-21T11:15:00Z",
    }), true);
    releaseOld({ snapshot_id: "A", data_timestamp: "2026-08-21T11:00:00Z" });
    await first;
    expect(newer.data.snapshot_id).toBe("B");
    expect(readCached<{ snapshot_id: string }>("radar")?.data.snapshot_id).toBe("B");
  });

  it("restores a same-session snapshot from session cache", async () => {
    const stamp = new Date().toISOString();
    await cachedRequest("radar", async () => ({ snapshot_id: "current", data_timestamp: stamp }));
    clearReadCacheForTests();
    expect(readCached<{ snapshot_id: string }>("radar")?.data.snapshot_id).toBe("current");
  });
});
