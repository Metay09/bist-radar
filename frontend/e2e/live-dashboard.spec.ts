import { expect, test, type Page, type Route } from "@playwright/test";

const stampA = "2026-08-21T11:00:00Z";
const stampB = "2026-08-21T11:15:00Z";
const candidate = (symbol: string, stamp = stampA, score = 98) => ({
  symbol, radar_score: score, classification: "VERY_STRONG_CANDIDATE", price: score + 100,
  rvol: 2.7, early_momentum_score: 92, timestamp: stamp, data_quality: 100,
  market_regime: "NEUTRAL", daily_trend: "UPTREND", breakout_distance: 0,
  disposition: "SIGNAL_CREATED",
});
const plan = (symbol: string, stamp = stampA) => ({
  symbol, timestamp: stamp, reference_price: 200, entry_zone_low: 198,
  entry_zone_high: 201, stop_price: 194, targets: [{ price: 209, return_percent: 4.5 }],
  risk_reward: 2.5, status: "BREAKOUT_ONAYI", explanation: [], stale: false,
  market_closed: false, research_only: true,
});
const summary = (stamp = stampA) => ({
  provider: "test", provider_health: "HEALTHY", paper_mode: true, research_only: true,
  market_open: true, data_timestamp: stamp,
  freshness: { state: "FRESH", age_minutes: 1, label: "Veri 1 dk yaşında" },
  counts: { VERY_STRONG_CANDIDATE: 20, PENDING_OUTCOMES: 0 }, last_scan: stamp,
});
const symbols = ["TUPRS", "ASELS", "THYAO", "SISE", "EREGL", "BIMAS", "FROTO", "KCHOL", "SAHOL", "TCELL", "AKBNK", "YKBNK", "ISCTR", "GARAN", "PETKM", "ASTOR", "ENKAI", "TOASO", "TAVHL", "PGSUS"];
const opportunities = (stamp: string, id: string) => ({
  snapshot_id: id, data_timestamp: stamp,
  opportunities: symbols.map((symbol, index) => ({
    candidate: candidate(symbol, stamp, 98 - index), plan: plan(symbol, stamp),
    snapshot_id: id, data_timestamp: stamp,
  })),
});

async function init(page: Page) {
  await page.addInitScript(() => localStorage.setItem("bist-radar-tour-seen", "1"));
}

async function fallback(route: Route, stamp = stampA) {
  const url = route.request().url();
  const symbol = /\/symbols\/([^/]+)/.exec(url)?.[1] || "TUPRS";
  const body = url.includes("dashboard/summary") ? summary(stamp)
    : url.includes("dashboard/candidates") ? symbols.map((item, i) => candidate(item, stamp, 98 - i))
    : url.includes("universe/summary") ? { eligible_for_radar: 20, coverage_percent: 100 }
    : url.includes("/detail") ? { symbol, candidate: candidate(symbol, stamp), bars: [], progression: [], freshness: summary(stamp).freshness, trade_plan: plan(symbol, stamp) }
    : [];
  await route.fulfill({ json: body });
}

test("cold, warm, refresh and snapshot update remain coherent", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await init(page);
  let current = "A";
  let delayOpportunity = true;
  let opportunityCalls = 0;
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("snapshot-status")) return route.fulfill({ json: {
      snapshot_id: current, data_timestamp: current === "A" ? stampA : stampB,
      generated_at: current === "A" ? stampA : stampB, market_open: true,
      freshness: summary().freshness,
    }});
    if (url.includes("opportunities")) {
      opportunityCalls += 1;
      if (delayOpportunity) await new Promise((resolve) => setTimeout(resolve, 700));
      return route.fulfill({ json: opportunities(current === "A" ? stampA : stampB, current) });
    }
    if (url.includes("/detail")) {
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
    return fallback(route, current === "A" ? stampA : stampB);
  });
  await page.goto("/");
  await expect(page.getByText("Plan yükleniyor…").last()).toBeVisible();
  await page.screenshot({ path: "artifacts/mobile-radar-loading.png", fullPage: true });
  await expect(page.getByText("Kırılım Gerçekleşti").last()).toBeVisible();
  await page.screenshot({ path: "artifacts/mobile-radar-loaded.png", fullPage: true });

  await page.getByLabel("Sembol ara").fill("TUP");
  await page.getByLabel("Radar sıralaması").selectOption("radar");
  await page.getByLabel("TUPRS detayını aç").click();
  await expect(page.getByText("Son Radar görünümü").first()).toBeVisible();
  await page.screenshot({ path: "artifacts/mobile-symbol-warm-open.png", fullPage: true });
  await page.goBack();
  await expect(page.getByLabel("Sembol ara")).toHaveValue("TUP");
  await expect(page.getByLabel("Radar sıralaması")).toHaveValue("radar");
  await expect(page.getByText("TUPRS").last()).toBeVisible();

  delayOpportunity = true;
  current = "B";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByText("↻ Güncelleniyor")).toBeVisible();
  await page.screenshot({ path: "artifacts/mobile-radar-refreshing.png", fullPage: true });
  await expect(page.locator(".fresh").first()).toContainText("14:15", { timeout: 4000 });
  await page.screenshot({ path: "artifacts/mobile-radar-updated.png", fullPage: true });
  expect(opportunityCalls).toBeLessThanOrEqual(4);
});

test("502 retry preserves candidates and recovers", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await init(page);
  let calls = 0;
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("opportunities")) {
      calls += 1;
      if (calls === 1) return route.fulfill({ status: 502 });
      return route.fulfill({ json: opportunities(stampA, "A") });
    }
    if (url.includes("snapshot-status")) return route.fulfill({ json: { snapshot_id: "A", data_timestamp: stampA, generated_at: stampA, market_open: true, freshness: summary().freshness } });
    return fallback(route);
  });
  await page.goto("/");
  await expect(page.getByText("İşlem Uygun Değil")).toHaveCount(0);
  await expect(page.getByText("Kırılım Gerçekleşti").last()).toBeVisible({ timeout: 4000 });
  await page.screenshot({ path: "artifacts/mobile-radar-error-retry.png", fullPage: true });
  expect(calls).toBe(2);
});

test("desktop snapshot is stable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await init(page);
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("opportunities")) return route.fulfill({ json: opportunities(stampB, "B") });
    if (url.includes("snapshot-status")) return route.fulfill({ json: { snapshot_id: "B", data_timestamp: stampB, generated_at: stampB, market_open: true, freshness: summary(stampB).freshness } });
    return fallback(route, stampB);
  });
  await page.goto("/");
  await expect(page.getByText("Kırılım Gerçekleşti").first()).toBeVisible();
  await page.screenshot({ path: "artifacts/desktop-radar-updated.png", fullPage: true });
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 1440);
});
