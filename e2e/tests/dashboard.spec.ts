import { expect, test } from "@playwright/test";

import { ask, expectAnswers, fakeAskResponse, jsonError, results, COMPOSER } from "./helpers";

const REVENUE = "What were the top 10 customers by revenue?";
const ACTIVE = "How many active vehicles do we have?";
const MONTHLY = "Show monthly revenue for the last 12 months.";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  await page.reload();
});

test.describe("asking questions", () => {
  test("shows examples first, then a KPI answer for a count question", async ({ page }) => {
    await expect(page.getByRole("region", { name: "What can I ask" })).toBeVisible();

    await ask(page, ACTIVE);

    await expectAnswers(page, 1);
    await expect(results(page).getByText("Active Vehicles")).toBeVisible();
    await expect(page.getByRole("region", { name: "What can I ask" })).toHaveCount(0);
  });

  test("renders a chart and a table for a ranking question and can show the SQL", async ({ page }) => {
    await ask(page, REVENUE);

    await expectAnswers(page, 1);
    await expect(results(page).getByRole("figure")).toBeVisible();
    await expect(results(page).getByRole("table")).toBeVisible();
    expect(await results(page).getByRole("row").count()).toBeGreaterThan(2);

    await results(page).getByRole("button", { name: /generated sql/i }).click();
    await expect(results(page).getByText(/SELECT c\.company_name/)).toBeVisible();
  });

  test("keeps earlier answers visible after follow-up questions", async ({ page }) => {
    await ask(page, REVENUE);
    await expectAnswers(page, 1);
    await ask(page, ACTIVE);
    await expectAnswers(page, 2);
    await ask(page, MONTHLY);
    await expectAnswers(page, 3);

    // The first answer is still there, with its own table.
    await expect(results(page).first().getByRole("table")).toBeVisible();
    await expect(page.getByText(REVENUE).first()).toBeVisible();
  });

  test("an unanswerable question gets guidance, not a stack trace", async ({ page }) => {
    await ask(page, "Tell me something the mock provider cannot answer");

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("alert")).not.toContainText("Traceback");
  });
});

test.describe("conversation lifecycle", () => {
  test("a reload restores the conversation text and explains that data is not stored", async ({ page }) => {
    await ask(page, REVENUE);
    await expectAnswers(page, 1);

    await page.reload();

    await expect(page.getByText(REVENUE).first()).toBeVisible();
    await expect(page.getByText(/data for this answer is not stored/i)).toBeVisible();
    await expectAnswers(page, 0);
  });

  test("a conversation can be deleted and stays gone after a reload", async ({ page }) => {
    await ask(page, ACTIVE);
    await expectAnswers(page, 1);

    await page.getByRole("button", { name: /delete conversation/i }).click();
    await expectAnswers(page, 0);
    await page.reload();

    await expect(page.getByRole("region", { name: "What can I ask" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Recent conversations" })).toHaveCount(0);
  });

  test("answers can be rated", async ({ page }) => {
    await ask(page, ACTIVE);
    await expectAnswers(page, 1);

    await page.getByRole("button", { name: "Helpful" }).click();

    await expect(page.getByText("Thanks for the feedback.")).toBeVisible();
  });
});

test.describe("results", () => {
  test("downloads the result as CSV", async ({ page }) => {
    await ask(page, REVENUE);
    await expectAnswers(page, 1);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: /export csv/i }).click(),
    ]);

    expect(download.suggestedFilename()).toMatch(/\.csv$/);
  });

  test("paginates a large result", async ({ page }) => {
    await page.route("**/api/v1/analytics/ask", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fakeAskResponse(120)) }),
    );

    await ask(page, "Revenue by customer");

    await expect(page.getByText("Page 1 of 3")).toBeVisible();
    expect(await results(page).getByRole("row").count()).toBe(51);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText("Customer 51")).toBeVisible();
    await expect(page.getByText("Page 2 of 3")).toBeVisible();
  });

  test("marks a truncated result", async ({ page }) => {
    await page.route("**/api/v1/analytics/ask", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(fakeAskResponse(60, { truncated: true })),
      }),
    );

    await ask(page, "Revenue by customer");

    await expect(page.getByText(/The result was cut at 60 rows/)).toBeVisible();
  });
});

test.describe("error states", () => {
  test("a 401 asks for an access token and retries the question with it", async ({ page }) => {
    const authorizations: (string | undefined)[] = [];
    await page.route("**/api/v1/analytics/ask", (route) => {
      const header = route.request().headers()["authorization"];
      authorizations.push(header);
      return header
        ? route.continue()
        : jsonError(route, 401, "UNAUTHENTICATED", "Authentication is required.");
    });

    await ask(page, ACTIVE);
    await expect(page.getByRole("alert", { name: /sign in required/i })).toBeVisible();

    await page.getByLabel("Access token").fill("e2e-token");
    await page.getByRole("button", { name: "Continue" }).click();

    await expectAnswers(page, 1);
    expect(authorizations).toEqual([undefined, "Bearer e2e-token"]);
  });

  test("a 429 shows a countdown and enables Retry when it ends", async ({ page }) => {
    let calls = 0;
    await page.route("**/api/v1/analytics/ask", (route) => {
      calls += 1;
      return calls === 1
        ? jsonError(route, 429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please retry later.", {
            "Retry-After": "2",
          })
        : route.continue();
    });

    await ask(page, ACTIVE);

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Try again in");
    await expect(page.getByRole("button", { name: "Retry" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Retry" })).toBeEnabled({ timeout: 10_000 });
    await page.getByRole("button", { name: "Retry" }).click();
    await expectAnswers(page, 1);
  });

  test("a 504 explains the timeout and offers a retry", async ({ page }) => {
    let calls = 0;
    await page.route("**/api/v1/analytics/ask", (route) => {
      calls += 1;
      return calls === 1
        ? jsonError(route, 504, "REQUEST_DEADLINE_EXCEEDED", "The request took too long to complete.")
        : route.continue();
    });

    await ask(page, ACTIVE);

    await expect(page.getByRole("alert")).toContainText("Try a narrower question");
    await page.getByRole("button", { name: "Retry" }).click();
    await expectAnswers(page, 1);
  });

  test("a failed query generation shows guidance and no retry", async ({ page }) => {
    await page.route("**/api/v1/analytics/ask", (route) =>
      jsonError(route, 422, "QUERY_GENERATION_FAILED", "I couldn't produce a valid query for that question."),
    );

    await ask(page, "Do something impossible");

    await expect(page.getByRole("alert", { name: /could not answer this question/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  });
});

test.describe("the public surface", () => {
  test("pages carry the security headers", async ({ request }) => {
    const response = await request.get("/");
    const headers = response.headers();

    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
  });

  test.describe("routes the browser must not reach", () => {
    for (const path of [
      "/api/v1/analytics/query",
      "/api/v1/analytics/validate",
      "/api/v1/analytics/generate",
      "/api/v1/metrics",
      "/api/v1/metrics/prometheus",
      "/api/v1/health/diagnostics",
    ]) {
      test(`${path} is not proxied`, async ({ request }) => {
        const response = await request.get(path);

        expect(response.status()).toBe(404);
      });
    }
  });

  test("the composer is labelled and usable by keyboard", async ({ page }) => {
    await page.getByLabel(COMPOSER).fill(ACTIVE);
    await page.getByLabel(COMPOSER).press("Tab");
    await expect(page.getByRole("button", { name: /run analytics query/i })).toBeFocused();
    await page.keyboard.press("Enter");

    await expectAnswers(page, 1);
  });
});
