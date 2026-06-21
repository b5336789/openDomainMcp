import { expect, test } from "@playwright/test";
import { installApiMocks } from "./helpers/mockApi";

const NAV_LABELS = [
  "Dashboard",
  "Ingest",
  "Explore",
  "Ask",
  "Browse / Edit",
  "Articles",
  "Review",
  "Graph",
  "Advisor",
  "MCP Builder",
  "Simulator",
  "Metrics",
  "Settings",
];

test.describe("smoke", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page);
  });

  test("renders every sidebar nav link", async ({ page }) => {
    await page.goto("/");

    const sidebar = page.locator("aside");
    for (const label of NAV_LABELS) {
      await expect(
        sidebar.getByRole("link", { name: label, exact: true }),
      ).toBeVisible();
    }
  });

  test("pipeline card shows live values from stats/sources/settings", async ({
    page,
  }) => {
    await page.goto("/");

    // Scope to the Pipeline card (outer Card uses rounded-xl; stage boxes
    // use rounded-lg) so the assertions don't collide with the stat cards.
    const card = page
      .locator("div.rounded-xl")
      .filter({ has: page.getByRole("heading", { name: "Pipeline" }) });

    // Each stage reports a real, current value rather than a fixed hint.
    await expect(card.getByText("2 sources")).toBeVisible(); // load: sources.length
    await expect(card.getByText("1,234 chunks")).toBeVisible(); // split: stats.count
    await expect(card.getByText("on", { exact: true })).toBeVisible(); // extract: extract_knowledge
    await expect(card.getByText("all-MiniLM-L6-v2")).toBeVisible(); // embed: embedder
    await expect(card.getByText("default", { exact: true })).toBeVisible(); // store: collection
    await expect(card.getByText("hybrid")).toBeVisible(); // search: search_mode
  });

  test("dashboard shows stats and the sources section", async ({ page }) => {
    await page.goto("/");

    // Stat cards from /api/stats. Scope to the stats grid: the same values
    // now legitimately also appear in the Pipeline card stages.
    const statsSection = page
      .locator("section")
      .filter({ has: page.getByText("Indexed chunks") });
    await expect(statsSection.getByText("Indexed chunks")).toBeVisible();
    await expect(statsSection.getByText("1,234", { exact: true })).toBeVisible();
    await expect(statsSection.getByText("all-MiniLM-L6-v2")).toBeVisible();

    // Sources section from /api/sources.
    await expect(
      page.getByRole("heading", { name: /Sources/ }),
    ).toBeVisible();
    await expect(page.getByText("docs/deploy.md")).toBeVisible();
    await expect(page.getByText("runbooks/rollback.md")).toBeVisible();
  });
});
