import { useState } from "react";
import { askStream, Citation } from "../api";

export default function Ask() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function run() {
    if (!query) return;
    setLoading(true);
    setError(null);
    setAnswer("");
    setCitations([]);
    askStream(
      query,
      6,
      (text) => setAnswer((prev) => prev + text),
      (cites) => setCitations(cites),
      (detail) => setError(detail),
      () => setLoading(false)
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold">Ask</h2>
      <p className="text-sm text-slate-500">
        Retrieves the most relevant chunks and has Claude compose a cited answer.
      </p>

      <div className="flex gap-2">
        <input
          className="flex-1 rounded border px-3 py-2"
          placeholder="Ask a question about the indexed knowledge…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <button onClick={run} className="rounded bg-slate-900 px-4 py-2 text-white">
          Ask
        </button>
      </div>

      {loading && !answer && <p className="text-slate-500 animate-pulse">Thinking…</p>}
      {error && <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      {answer && (
        <div className="space-y-4">
          <div className="rounded-lg border bg-white p-4 whitespace-pre-wrap leading-relaxed">
            {answer}
            {loading && <span className="animate-pulse">▍</span>}
          </div>
          {citations.length > 0 && (
            <div className="rounded-lg border bg-white p-4">
              <h3 className="text-sm font-medium text-slate-500 mb-2">Sources</h3>
              <ol className="space-y-1 text-sm">
                {citations.map((c) => (
                  <li key={c.n} className="font-mono text-slate-700">
                    [{c.n}] {c.source}
                    {c.symbol ? `::${c.symbol}` : ""}{" "}
                    <span className="text-slate-400">score {c.score.toFixed(3)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
