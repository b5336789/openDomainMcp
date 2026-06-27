import { useEffect, useState } from "react";
import {
  api,
  SimulateResult,
  ValidationRun,
  ValidationScenario,
  ViewsMap,
} from "../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Label,
  PageHeader,
  Select,
  Textarea,
  useToast,
} from "../components/ui";
import { IconSimulator } from "../components/icons";

export default function Simulator() {
  const [views, setViews] = useState<ViewsMap | null>(null);
  const [view, setView] = useState("product");
  const [task, setTask] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SimulateResult | null>(null);
  const [scenarios, setScenarios] = useState<ValidationScenario[]>([]);
  const [scenarioRuns, setScenarioRuns] = useState<Record<string, ValidationRun>>({});
  const [scenarioName, setScenarioName] = useState("");
  const [savingScenario, setSavingScenario] = useState(false);
  const [runningScenario, setRunningScenario] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    api.views().then(setViews).catch((e) => toast.show(String(e), "red"));
    void loadScenarios();
  }, []);

  async function loadScenarios(selectedView = view) {
    try {
      setScenarios(await api.validationScenarios(selectedView));
    } catch (e) {
      toast.show(String(e), "red");
    }
  }

  async function run() {
    if (!task.trim()) return;
    setRunning(true);
    setResult(null);
    try {
      setResult(await api.simulate(view, task.trim()));
    } catch (e) {
      toast.show(String(e), "red");
    } finally {
      setRunning(false);
    }
  }

  async function saveScenario() {
    if (!result || !scenarioName.trim() || !task.trim()) return;
    setSavingScenario(true);
    try {
      const payload = await api.runValidation(view, task.trim(), scenarioName.trim());
      setResult(payload.result);
      setScenarios((prev) => {
        const without = prev.filter((scenario) => scenario.id !== payload.scenario.id);
        return [payload.scenario, ...without];
      });
      setScenarioRuns((prev) => ({ ...prev, [payload.scenario.id]: payload.run }));
      toast.show("Validation scenario saved", "green");
    } catch (e) {
      toast.show(String(e), "red");
    } finally {
      setSavingScenario(false);
    }
  }

  async function runSavedScenario(scenario: ValidationScenario) {
    setRunningScenario(scenario.id);
    try {
      const run = await api.runValidationScenario(scenario.id);
      setScenarioRuns((prev) => ({ ...prev, [scenario.id]: run }));
      toast.show(`Scenario ${run.status}`, run.status === "passed" ? "green" : "red");
    } catch (e) {
      toast.show(String(e), "red");
    } finally {
      setRunningScenario(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Agent Simulator"
        subtitle="Run a task against an MCP view and inspect the grounding it returns."
        icon={<IconSimulator />}
      />

      <Card className="space-y-3 p-5">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <div>
            <Label>Agent task</Label>
            <Textarea
              className="mt-1.5 h-20"
              placeholder="e.g. How do I roll back a failed deployment?"
              value={task}
              onChange={(e) => setTask(e.target.value)}
            />
          </div>
          <div className="sm:w-44">
            <Label>MCP view</Label>
            <Select
              className="mt-1.5"
              value={view}
              onChange={(e) => {
                setView(e.target.value);
                void loadScenarios(e.target.value);
              }}
            >
              {views &&
                Object.entries(views).map(([name, spec]) => (
                  <option key={name} value={name}>
                    {spec.title}
                  </option>
                ))}
            </Select>
          </div>
        </div>
        <div className="flex justify-end">
          <Button onClick={run} loading={running} disabled={!task.trim()}>
            Simulate
          </Button>
        </div>
      </Card>

      <Card className="space-y-3 p-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Validation scenarios
          </h3>
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
            Save representative tasks and rerun them before publishing this MCP view.
          </p>
        </div>
        {scenarios.length === 0 ? (
          <EmptyState
            icon={<IconSimulator className="h-6 w-6" />}
            title="No validation scenarios"
            hint="Run a simulation, name it, and save it as a reusable validation scenario."
          />
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {scenarios.map((scenario) => {
              const run = scenarioRuns[scenario.id];
              return (
                <div
                  key={scenario.id}
                  className="flex flex-wrap items-center gap-3 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-slate-900 dark:text-white">
                      {scenario.name}
                    </div>
                    <div className="truncate text-xs text-slate-400">
                      {scenario.query}
                    </div>
                    {run && (
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        latest {run.status} · {run.grounding_hits} hits
                      </div>
                    )}
                  </div>
                  {run && (
                    <Badge tone={run.status === "passed" ? "green" : "red"}>
                      {run.status}
                    </Badge>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={runningScenario === scenario.id}
                    disabled={runningScenario === scenario.id}
                    onClick={() => void runSavedScenario(scenario)}
                  >
                    Run scenario {scenario.name}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {result && (
        <>
          <Card className="space-y-3 p-4">
            <Label>
              Scenario name
              <Input
                className="mt-1.5"
                value={scenarioName}
                onChange={(e) => setScenarioName(e.target.value)}
                placeholder="e.g. Rollback guidance"
              />
            </Label>
            <div className="flex justify-end">
              <Button
                onClick={saveScenario}
                loading={savingScenario}
                disabled={!scenarioName.trim()}
              >
                Save validation scenario
              </Button>
            </div>
          </Card>

          <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
            <Stat label="Context hits" value={String(result.grounding.hits)} />
            <Stat label="Avg score" value={result.grounding.avg_score.toFixed(3)} />
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wide text-slate-400">
                Types
              </span>
              {result.grounding.knowledge_types.length ? (
                result.grounding.knowledge_types.map((t) => (
                  <Badge key={t} tone="brand">
                    {t}
                  </Badge>
                ))
              ) : (
                <Badge tone="amber">none</Badge>
              )}
            </div>
          </Card>

          {result.grounding.hits === 0 && (
            <EmptyState
              icon={<IconSimulator className="h-6 w-6" />}
              title="No grounding found"
              hint="This view returned nothing for the task — the agent would be ungrounded."
            />
          )}

          {result.tools.map((t) => (
            <div key={t.tool} className="space-y-2">
              <div className="flex items-center gap-2">
                <code className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-brand-700 dark:bg-slate-800 dark:text-brand-300">
                  {t.tool}()
                </code>
                <span className="text-xs text-slate-400">
                  {t.results.length} result{t.results.length === 1 ? "" : "s"}
                </span>
              </div>
              {t.results.length > 0 && (
                <Card className="divide-y divide-slate-100 dark:divide-slate-800">
                  {t.results.map((r) => (
                    <div key={r.id} className="p-3.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {r.metadata.knowledge_type && (
                          <Badge tone="brand">{r.metadata.knowledge_type}</Badge>
                        )}
                        <span className="truncate font-mono text-xs text-slate-500 dark:text-slate-400">
                          {r.metadata.source}
                          {r.metadata.symbol ? `::${r.metadata.symbol}` : ""}
                        </span>
                        <span className="ml-auto text-xs text-slate-400">
                          {r.score.toFixed(3)}
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                        {r.text.slice(0, 200)}
                      </div>
                    </div>
                  ))}
                </Card>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-lg font-semibold text-slate-900 dark:text-white">{value}</div>
    </div>
  );
}
