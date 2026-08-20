import { expect, test } from "@playwright/test";

const stamp = "2026-08-21T10:00:00Z";
const candidate = {
  symbol: "TUPRS", radar_score: 98, classification: "VERY_STRONG_CANDIDATE",
  price: 200, rvol: 2.7, early_momentum_score: 92, timestamp: stamp,
  data_quality: 100, market_regime: "NEUTRAL", daily_trend: "UPTREND",
  breakout_distance: 0, disposition: "SIGNAL_CREATED",
};
const plan = {
  symbol: "TUPRS", timestamp: stamp, reference_price: 200,
  entry_zone_low: 198, entry_zone_high: 201, stop_price: 194,
  targets: [{ price: 209, return_percent: 4.5 }], risk_reward: 2.5,
  status: "BREAKOUT_ONAYI", explanation: [], stale: false,
  market_closed: false, research_only: true,
};
const summary = {
  provider: "test", provider_health: "RESEARCH_ONLY", paper_mode: true,
  research_only: true, market_open: true, data_timestamp: stamp,
  freshness: { state: "FRESH", age_minutes: 1, label: "Veri 1 dk yaşında" },
  counts: { VERY_STRONG_CANDIDATE: 1, PENDING_OUTCOMES: 0 }, last_scan: stamp,
};

async function commonRoute(page: import("@playwright/test").Page, planHandler: (route: import("@playwright/test").Route) => Promise<void>) {
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("trade-plans")) return planHandler(route);
    const body = url.includes("dashboard/candidates") ? [candidate]
      : url.includes("dashboard/summary") ? summary : [];
    await route.fulfill({ json: body });
  });
  await page.addInitScript(() => localStorage.setItem("bist-radar-tour-seen", "1"));
}

test("5 saniye geciken plan yanlış finansal karar üretmez", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await commonRoute(page, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 5000));
    await route.fulfill({ json: [plan] });
  });
  await page.goto("/");
  await expect(page.getByText("TUPRS").last()).toBeVisible();
  await expect(page.getByLabel("Radar puanı 98")).toBeVisible();
  await expect(page.getByText("Plan yükleniyor…").last()).toBeVisible();
  await expect(page.getByText("İşlem Uygun Değil")).toHaveCount(0);
  await page.screenshot({ path: "artifacts/radar-plan-loading-390.png", fullPage: true });
  await expect(page.getByText("Kırılım Gerçekleşti").last()).toBeVisible({ timeout: 7000 });
  await expect(page.getByText("198,00–201,00").first()).toBeVisible();
  await expect(page.getByText("194,00").first()).toBeVisible();
  await expect(page.getByText("209,00").first()).toBeVisible();
  await page.screenshot({ path: "artifacts/radar-plan-complete-390.png", fullPage: true });
});

test("502 sonrası bounded retry planı sayfa yenilemeden getirir", async ({ page }) => {
  let calls = 0;
  await commonRoute(page, async (route) => {
    calls += 1;
    if (calls === 1) await route.fulfill({ status: 502, body: "bad gateway" });
    else await route.fulfill({ json: [plan] });
  });
  await page.goto("/");
  await expect(page.getByText("İşlem Uygun Değil")).toHaveCount(0);
  await expect(page.getByText("Kırılım Gerçekleşti").first()).toBeVisible({ timeout: 4000 });
  expect(calls).toBe(2);
});

test("kalıcı plan hatası candidate görünürlüğünü korur", async ({ page }) => {
  let calls = 0;
  await commonRoute(page, async (route) => { calls += 1; await route.fulfill({ status: 503 }); });
  await page.goto("/");
  await expect(page.getByText("Plan verisi alınamadı").first()).toBeVisible({ timeout: 6000 });
  await expect(page.getByText("TUPRS").first()).toBeVisible();
  await expect(page.getByText("İşlem Uygun Değil")).toHaveCount(0);
  // React StrictMode's development-only effect probe may add one abandoned request.
  expect(calls).toBeGreaterThanOrEqual(3);
  expect(calls).toBeLessThanOrEqual(4);
});
