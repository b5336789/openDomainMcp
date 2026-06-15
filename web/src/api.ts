// Typed helpers around the FastAPI backend.

export interface Stats {
  collection: string;
  count: number;
  embedder: string;
  dim: number;
  data_dir: string;
  extract_knowledge: boolean;
}

export interface SearchResult {
  id: string;
  text: string;
  score: number;
  metadata: Record<string, string>;
}

export interface SearchFilters {
  kind?: string | null;
  language?: string | null;
  source_contains?: string | null;
}

export interface Item {
  id: string;
  text: string;
  metadata: Record<string, string>;
}

export interface SettingsView {
  editable: Record<string, string | number | boolean>;
  collection: string;
  embedder_backend: string;
  data_dir: string;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => fetch("/api/stats").then(json<Stats>),

  search: (query: string, top_k: number, filters: SearchFilters = {}) =>
    fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, top_k, ...filters }),
    }).then(json<SearchResult[]>),

  items: (limit: number, offset: number, kind: string | null) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (kind) params.set("kind", kind);
    return fetch(`/api/items?${params}`).then(json<Item[]>);
  },

  updateItem: (id: string, metadata: Record<string, string>) =>
    fetch(`/api/items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metadata }),
    }).then(json<Item>),

  deleteItem: (id: string) =>
    fetch(`/api/items/${id}`, { method: "DELETE" }).then(json<{ deleted: string }>),

  upload: (files: FileList) => {
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    return fetch("/api/upload", { method: "POST", body: form }).then(
      json<{ path: string; files: string[] }>
    );
  },

  getSettings: () => fetch("/api/settings").then(json<SettingsView>),

  patchSettings: (values: Record<string, string | number | boolean>) =>
    fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    }).then(json<{ updated: string[] }>),
};

// Stream ingest progress via Server-Sent Events. Returns an unsubscribe fn.
export function ingestStream(
  path: string,
  onEvent: (e: Record<string, unknown>) => void,
  onDone: () => void,
  sync = false
): () => void {
  const url = `/api/ingest/stream?path=${encodeURIComponent(path)}&sync=${sync}`;
  const source = new EventSource(url);
  const handler = (ev: MessageEvent) => {
    try {
      onEvent(JSON.parse(ev.data));
    } catch {
      /* ignore keep-alive */
    }
  };
  // The backend names events by stage; listen to the ones we render.
  ["load", "split", "extract", "embed", "store", "prune", "skip", "error", "done", "report"].forEach(
    (name) => source.addEventListener(name, handler as EventListener)
  );
  source.addEventListener("report", () => {
    source.close();
    onDone();
  });
  source.onerror = () => {
    source.close();
    onDone();
  };
  return () => source.close();
}
