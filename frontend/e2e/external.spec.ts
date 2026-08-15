import { expect, test } from "@playwright/test";

const externalUrl = process.env.EXTERNAL_ACCEPTANCE_URL;
test.skip(!externalUrl, "External acceptance URL is opt-in");
test.setTimeout(120_000);

test("yayındaki gerçek dashboard ekranları", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(externalUrl!);
  await page.evaluate(() => localStorage.setItem("bist-radar-tour-seen", "1"));
  for (const [name, path] of [
    ["radar", "/"],
      ["history", "/history"],
      ["tracking", "/tracking"],
    ["analysis", "/analysis"],
    ["system", "/system"],
  ]) {
    await page.goto(`${externalUrl}${path}`);
    await expect(page.locator(".desktop-sidebar")).toBeHidden();
    await expect(page.locator(".bottom")).toBeVisible();
    // The production dashboard polls health/data endpoints, so networkidle is
    // not a valid readiness signal.  The skeleton disappearing is the user-
    // visible contract that the route has finished loading.
    await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await expect(page.locator("pre")).toHaveCount(0);
    await expect(page.getByText("PERSIST_OPEN")).toHaveCount(0);
    await expect(page.getByText("PERSIST_CLOSED")).toHaveCount(0);
    await page.screenshot({
      path: `artifacts/android-360-${name}.png`,
      fullPage: true,
    });
  }
  const symbols = await page
    .goto(`${externalUrl}/api/dashboard/candidates`)
    .then(async () => page.locator("body").textContent())
    .then((text) =>
      JSON.parse(text || "[]").map((row: { symbol: string }) => row.symbol),
    );
  expect(new Set(symbols).size).toBe(symbols.length);
  expect(symbols.length).toBeGreaterThan(0);
  await page.goto(`${externalUrl}/symbol/${symbols[0]}`);
  await expect(page.getByText("below_recent_swing_and_1_2_ATR")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: /İşlem Planı/ }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/android-360-astor-plan.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "GRAFİK" }).click();
  for (const label of [
    "Hedef 3",
    "Hedef 2",
    "Hedef 1",
    "Alım",
    "Stop",
    "Referans",
  ])
    await expect(
      page.locator("svg").getByText(label, { exact: false }),
    ).toBeVisible();
  await page.screenshot({
    path: "artifacts/android-360-astor-chart.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(externalUrl!);
  await expect(page.locator(".desktop-sidebar")).toBeVisible();
  await page.screenshot({
    path: "artifacts/desktop-radar.png",
    fullPage: true,
  });
});

test("yayında detaydan dönünce Radar konumu korunur", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(externalUrl!);
  await page.evaluate(() => localStorage.setItem("bist-radar-tour-seen", "1"));
  await page.reload();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
  const cards = page.locator(".signal-card");
  expect(await cards.count()).toBeGreaterThan(5);
  const link = cards.last().locator(".card-link");
  await link.scrollIntoViewIfNeeded();
  const before = await page.evaluate(() => scrollY);
  expect(before).toBeGreaterThan(500);
  await link.click();
  await expect(
    page.getByRole("heading", { name: /İşlem Planı/ }),
  ).toBeVisible();
  await page.goBack();
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
  await expect
    .poll(() => page.evaluate(() => scrollY))
    .toBeGreaterThan(before - 100);
});
