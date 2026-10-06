import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ask, expectAnswers, fakeAskResponse } from "./helpers";

/**
 * Automated WCAG 2.x A/AA checks. Only serious and critical violations fail the build; moderate
 * and minor findings are attached to the test output so they can be triaged without blocking.
 * Automated checks catch roughly a third of accessibility problems; they do not replace a manual
 * keyboard and screen-reader pass.
 */
async function scan(page: Page, name: string, testInfo: import("@playwright/test").TestInfo) {
  const scanResults = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  await testInfo.attach(`axe-${name}.json`, {
    body: JSON.stringify(scanResults.violations, null, 2),
    contentType: "application/json",
  });
  const blocking = scanResults.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(
    blocking.map((violation) => `${violation.id}: ${violation.help} (${violation.nodes.length} nodes)`),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  await page.reload();
});

test("the empty dashboard has no serious or critical violations", async ({ page }, testInfo) => {
  await expect(page.getByRole("region", { name: "What can I ask" })).toBeVisible();

  await scan(page, "empty", testInfo);
});

test("a chart-and-table answer has no serious or critical violations", async ({ page }, testInfo) => {
  await ask(page, "What were the top 10 customers by revenue?");
  await expectAnswers(page, 1);

  await scan(page, "answer", testInfo);
});

test("a 1,000-row paginated answer has no serious or critical violations", async ({ page }, testInfo) => {
  await page.route("**/api/v1/analytics/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeAskResponse(1000, { truncated: true })),
    }),
  );
  await ask(page, "Revenue by customer");
  await expectAnswers(page, 1);

  await scan(page, "large", testInfo);
});

test("rendering 1,000 rows stays within the interaction budget", async ({ page }) => {
  await page.route("**/api/v1/analytics/ask", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fakeAskResponse(1000)),
    }),
  );

  const started = Date.now();
  await ask(page, "Revenue by customer");
  await expectAnswers(page, 1);
  const rendered = Date.now() - started;
  const bodyRows = await page.getByRole("table").getByRole("row").count();

  // Pagination keeps the DOM small regardless of result size. The time budget is generous for
  // shared CI runners; docs/operations.md records the budget and how to re-measure it.
  expect(bodyRows).toBe(51);
  expect(rendered).toBeLessThan(5_000);
});
