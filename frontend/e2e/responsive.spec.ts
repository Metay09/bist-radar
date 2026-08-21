import { expect, test } from "@playwright/test";
const summary = {
  provider: "Yahoo Finance via yfinance",
  provider_health: "RESEARCH_ONLY",
  paper_mode: true,
  research_only: true,
  market_open: false,
  data_timestamp: "2026-08-13T10:00:00Z",
  freshness: {
    state: "MARKET_CLOSED",
    age_minutes: 30,
    label: "Piyasa kapalı — son tamamlanmış veri",
  },
  counts: { VERY_STRONG_CANDIDATE: 1, PENDING_OUTCOMES: 19 },
  last_scan: "2026-08-13T10:05:00Z",
};
const candidate = {
  signal_id: "s1",
  symbol: "ASTOR",
  radar_score: 99,
  classification: "VERY_STRONG_CANDIDATE",
  price: 331,
  rvol: 2.95,
  early_momentum_score: 100,
  timestamp: "2026-08-13T10:00:00Z",
  data_quality: 100,
  market_regime: "NEUTRAL",
  daily_trend: "UPTREND",
  breakout_distance: -0.2,
  disposition: "SIGNAL_UPGRADED",
  lifecycle: "OUTCOME_PENDING",
};
const plan = {
  symbol: "ASTOR",
  timestamp: candidate.timestamp,
  reference_price: 331,
  entry_zone_low: 331.19,
  entry_zone_high: 331.97,
  breakout_trigger: 331.8,
  stop_price: 322.5,
  stop_distance_percent: 2.74,
  targets: [
    { price: 345.2, return_percent: 4.11 },
    { price: 354.28, return_percent: 6.85 },
    { price: 358.83, return_percent: 8.22 },
  ],
  risk_reward: 2.5,
  status: "BREAKOUT_ONAYI",
  explanation: [
    "Stop seviyesi son kısa vadeli dip ve 1,2 ATR dikkate alınarak hesaplandı.",
    "Hacim normal seviyenin yaklaşık 2,95 katında.",
  ],
  data_age_minutes: 632,
  stale: true,
  market_closed: true,
  research_only: true,
  position_sizing: {
    account_equity: 100000,
    max_risk_percent: 0.75,
    allowed_risk_amount: 750,
    suggested_position_value: 9998.54,
    estimated_quantity: 30,
    advisory_only: true,
  },
};
const detail = {
  symbol: "ASTOR",
  candidate,
  bars: [
    {
      timestamp: candidate.timestamp,
      open: 328,
      high: 333,
      low: 326,
      close: 331,
      volume: 1000,
    },
  ],
  progression: [],
  freshness: summary.freshness,
  trade_plan: plan,
};
async function mock(
  page: import("@playwright/test").Page,
  candidates = [candidate],
  summaryDelay = 0,
) {
  await page.route("**/api/**", async (route) => {
    const u = route.request().url();
    let body: unknown = [];
    if (u.includes("dashboard/summary")) {
      if (summaryDelay)
        await new Promise((resolve) => setTimeout(resolve, summaryDelay));
      body = summary;
    } else if (u.includes("symbols/ASTOR/detail")) body = detail;
    else if (u.includes("dashboard/candidates")) body = candidates;
    else if (u.includes("opportunities")) body = {
      snapshot_id: "s1", data_timestamp: candidate.timestamp,
      opportunities: candidates.map((item) => ({
        candidate: item, plan: { ...plan, symbol: item.symbol, timestamp: item.timestamp },
        snapshot_id: "s1", data_timestamp: candidate.timestamp,
      })),
    };
    else if (u.includes("signals/history")) body = [candidate];
    else if (u.includes("performance/summary"))
      body = {
        realized_pnl: 0,
        open_positions: 0,
        closed_trades: 0,
        mtm_equity: null,
      };
    else if (u.includes("ml/status"))
      body = { observations: 19, fully_labeled: 0 };
    else if (u.includes("system/overview"))
      body = { database: "HEALTHY", worker_jobs: [] };
    await route.fulfill({ json: body });
  });
}
for (const viewport of [
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 412, height: 915 },
  { width: 768, height: 1024 },
])
  test(`mobil responsive ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await mock(page);
    await page.addInitScript(() =>
      localStorage.setItem("bist-radar-tour-seen", "1"),
    );
    await page.goto("/");
    await expect(page.locator(".desktop-sidebar")).toBeHidden();
    await expect(page.locator(".bottom")).toBeVisible();
    await expect(page.locator(".desktop-table")).toBeHidden();
    await expect(page.locator(".signal-card")).toHaveCount(1);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await expect(page.getByText("Çok Güçlü Aday").last()).toBeVisible();
    await expect(
      page
        .locator(".mobile-signals")
        .getByText("Son tamamlanmış veriye göre kırılım"),
    ).toBeVisible();
  });
test("desktop sidebar ve tablo", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mock(page);
  await page.addInitScript(() =>
    localStorage.setItem("bist-radar-tour-seen", "1"),
  );
  await page.goto("/");
  await expect(page.locator(".desktop-sidebar")).toBeVisible();
  await expect(page.locator(".bottom")).toBeHidden();
  await expect(page.locator(".desktop-table")).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
});
test("detaydan dönünce Radar konumu korunur", async ({ page }) => {
  const candidates = [
    ...Array.from({ length: 14 }, (_, i) => ({
      ...candidate,
      symbol: `TEST${String(i).padStart(2, "0")}`,
      radar_score: 100 - i,
    })),
    { ...candidate, radar_score: 70 },
  ];
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page, candidates, 200);
  await page.addInitScript(() =>
    localStorage.setItem("bist-radar-tour-seen", "1"),
  );
  await page.goto("/");
  const link = page.getByLabel("ASTOR detayını aç");
  await link.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => scrollY);
  expect(before).toBeGreaterThan(500);
  await link.click();
  await expect(
    page.getByRole("heading", { name: "İşlem Planı" }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.locator(".signal-card")).toHaveCount(15);
  await expect
    .poll(() => page.evaluate(() => scrollY))
    .toBeGreaterThan(before - 100);
});
test("trade plan chart labels and production hygiene", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mock(page);
  await page.addInitScript(() =>
    localStorage.setItem("bist-radar-tour-seen", "1"),
  );
  await page.goto("/symbol/ASTOR");
  await expect(
    page.getByText("Son tamamlanmış veriye göre kırılım", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Veri 632 dk eski/)).toBeVisible();
  await expect(page.getByText("below_recent_swing_and_1_2_ATR")).toHaveCount(0);
  await page.getByRole("tab", { name: "GRAFİK" }).click();
  for (const text of [
    "Hedef 3",
    "Hedef 2",
    "Hedef 1",
    "Alım",
    "Stop",
    "Referans",
  ])
    await expect(
      page.locator("svg").getByText(text, { exact: false }),
    ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await page.goto("/portfolio");
  await expect(page.getByText("PERSIST_OPEN")).toHaveCount(0);
  await expect(page.getByText("PERSIST_CLOSED")).toHaveCount(0);
  await expect(page.locator("pre")).toHaveCount(0);
});
test("acceptance ekran görüntüleri", async ({ page }) => {
  await mock(page);
  await page.addInitScript(() =>
    localStorage.setItem("bist-radar-tour-seen", "1"),
  );
  await page.setViewportSize({ width: 360, height: 800 });
  for (const [name, path] of [
    ["radar", "/"],
    ["history", "/history"],
    ["tracking", "/tracking"],
    ["analysis", "/analysis"],
    ["system", "/system"],
  ]) {
    await page.goto(path);
    await expect(page.locator(".bottom")).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await expect(page.locator("pre")).toHaveCount(0);
    await expect(
      page.getByText("VERY_STRONG_CANDIDATE", { exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: `artifacts/android-360-${name}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.screenshot({
    path: "artifacts/desktop-radar.png",
    fullPage: true,
  });
});
