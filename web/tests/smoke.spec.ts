import { expect, test } from "@playwright/test";
import { installApiMocks } from "./helpers/mockApi";

const NAV_LABELS = [
  "Command Center",
  "Source Intake",
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

  test("renders command center readiness", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Command Center" }),
    ).toBeVisible();
    await expect(page.getByText("needs review")).toBeVisible();
    await expect(page.getByText("72", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Review pending knowledge before publishing MCP views."),
    ).toBeVisible();
  });

  test("shows source, review, job, and graph health summaries", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByText("Sources", { exact: true })).toBeVisible();
    await expect(page.getByText("2", { exact: true })).toBeVisible();
    await expect(page.getByText("60 chunks")).toBeVisible();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
    await expect(page.getByText("80%")).toBeVisible();
    await expect(page.getByText("10 pending")).toBeVisible();
    await expect(page.getByText("Jobs", { exact: true })).toBeVisible();
    await expect(page.getByText("0 active")).toBeVisible();
    await expect(page.getByText("Graph", { exact: true })).toBeVisible();
    await expect(page.getByText("available")).toBeVisible();
  });
});
