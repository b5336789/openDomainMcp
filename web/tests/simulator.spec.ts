import { expect, test } from "@playwright/test";
import { DEFAULT_VIEWS, installApiMocks } from "./helpers/mockApi";

const SIMULATE_RESULT = {
  view: "product",
  grounding: {
    hits: 3,
    avg_score: 0.812,
    knowledge_types: ["Runbook", "Workflow"],
  },
  tools: [
    {
      tool: "search_features",
      results: [
        {
          id: "chunk-1",
          text: "To roll back a failed deployment, revert to the last green build.",
          score: 0.91,
          metadata: {
            knowledge_type: "Runbook",
            source: "runbooks/rollback.md",
          },
        },
        {
          id: "chunk-2",
          text: "Deployments are gated behind an approval workflow.",
          score: 0.71,
          metadata: {
            knowledge_type: "Workflow",
            source: "docs/deploy.md",
          },
        },
      ],
    },
  ],
};

const SCENARIO = {
  id: "scenario-1",
  collection: "default",
  view: "operations",
  name: "Rollback",
  query: "How do I roll back a failed deployment?",
  created_at: 1814052000,
};

const RUN = {
  id: "run-1",
  scenario_id: "scenario-1",
  collection: "default",
  view: "operations",
  query: "How do I roll back a failed deployment?",
  status: "passed",
  grounding_hits: 3,
  avg_score: 0.812,
  tool_results: 2,
  knowledge_types: ["Runbook", "Workflow"],
  error: "",
  created_at: 1814052001,
};

test.describe("simulator", () => {
  test.beforeEach(async ({ page }) => {
    await installApiMocks(page, {
      "GET /api/views": DEFAULT_VIEWS,
      "POST /api/simulate": SIMULATE_RESULT,
      "GET /api/validation/scenarios": [{ ...SCENARIO, latest_run: RUN }],
      "POST /api/validation/run": {
        scenario: { ...SCENARIO, latest_run: RUN },
        run: RUN,
        result: SIMULATE_RESULT,
        summary: {
          collection: "default",
          view: "operations",
          status: "passed",
          scenario_count: 1,
          latest_run_count: 1,
          passed: 1,
          failed: 0,
          pass_rate: 1,
          latest_run: RUN,
        },
      },
      "POST /api/validation/scenarios/scenario-1/run": RUN,
    });
  });

  test("simulates a task and renders grounding hits + tool results", async ({
    page,
  }) => {
    await page.goto("/#/simulator");

    await expect(
      page.getByRole("heading", { name: "Agent Simulator" }),
    ).toBeVisible();

    // Wait for the views dropdown to populate from /api/views.
    await expect(
      page.getByRole("option", { name: "Product View" }),
    ).toBeAttached();

    await page
      .getByPlaceholder("e.g. How do I roll back a failed deployment?")
      .fill("How do I roll back a failed deployment?");

    // The page renders a single <select> for the MCP view (the collection
    // switcher select lives in the sidebar <aside>).
    await page
      .locator("main select")
      .selectOption({ label: "Operations View" });

    await page.getByRole("button", { name: "Simulate" }).click();

    // Grounding summary card.
    await expect(page.getByText("Context hits")).toBeVisible();
    await expect(page.getByText("0.812")).toBeVisible();

    // Tool name + results.
    await expect(page.getByText("search_features()")).toBeVisible();
    await expect(
      page.getByText(
        "To roll back a failed deployment, revert to the last green build.",
      ),
    ).toBeVisible();
    await expect(
      page.getByText("Deployments are gated behind an approval workflow."),
    ).toBeVisible();
  });

  test("saves and runs validation scenarios", async ({ page }) => {
    await page.goto("/#/simulator");
    await expect(page.getByRole("heading", { name: "Validation scenarios" })).toBeVisible();
    await expect(page.getByText("Rollback", { exact: true })).toBeVisible();
    await expect(page.getByText("latest passed · 3 hits")).toBeVisible();

    await page
      .getByPlaceholder("e.g. How do I roll back a failed deployment?")
      .fill("How do I roll back a failed deployment?");
    await page.locator("main select").selectOption({ label: "Operations View" });
    await page.getByRole("button", { name: "Simulate" }).click();

    await page.getByLabel("Scenario name").fill("Rollback");
    await page.getByRole("button", { name: "Save validation scenario" }).click();
    await expect(page.getByText("passed", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Run scenario Rollback" }).click();
    await expect(page.getByText("latest passed")).toBeVisible();
  });
});
