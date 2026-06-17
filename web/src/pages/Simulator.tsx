import { useEffect, useState } from "react";
import { api, SimulateResult, ViewsMap } from "../api";
import {
  Badge,
  Button,
  Card,
  EmptyState,
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
  const toast = useToast();

  useEffect(() => {
    api.views().then(setViews).catch((e) => toast.show(String(e), "red"));
  }, []);

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
              onChange={(e) => setView(e.target.value)}
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

      {result && (
        <>
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
