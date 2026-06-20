import { expect, test } from "@playwright/test";
import { installApiMocks } from "./helpers/mockApi";

const ARTICLES = [
  {
    id: "a1",
    title: "Order Approval Rule",
    topic: "order approval",
    business_relevance: 0.9,
    cross_validated: true,
    sources: ["rules.md:1", "approve.py:5"],
    body: "Orders above $10k require manager sign-off.",
  },
  {
    id: "a2",
    title: "PDF Export Limit",
    topic: "pdf export",
    business_relevance: 0.4,
    cross_validated: false,
    sources: ["billing.py:12"],
    body: "Free-tier customers cannot export to PDF.",
  },
];

test.describe("articles page", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page, { "GET /api/articles": ARTICLES });
  });

  test("lists articles and opens one to read its body", async ({ page }) => {
    await page.goto("/#/articles");

    await expect(page.getByRole("heading", { name: "Articles" })).toBeVisible();
    // Highest relevance first; first article auto-selected → its body shows.
    await expect(page.getByText("Orders above $10k require manager sign-off.")).toBeVisible();
    await expect(page.getByText("cross-validated")).toBeVisible();

    // Selecting the second article shows its body.
    await page.getByRole("button", { name: /PDF Export Limit/ }).click();
    await expect(page.getByText("Free-tier customers cannot export to PDF.")).toBeVisible();
    await expect(page.getByText("billing.py:12")).toBeVisible();
  });

  test("shows the empty state when there are no articles", async ({ page }) => {
    await installApiMocks(page, { "GET /api/articles": [] });
    await page.goto("/#/articles");
    await expect(page.getByText("No articles yet")).toBeVisible();
  });
});
