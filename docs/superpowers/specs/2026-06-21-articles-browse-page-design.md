# Articles Browse Page (read-only)

**Date:** 2026-06-21
**Status:** Design approved (outline), pending spec review

## Problem

The synthesis feature (#20) produces business-meaning **articles**, and #21 made
them feed `ask`/`search`. But a human still cannot *read* them: articles live only
in the `<base>__articles` Chroma collection, with no API and no UI. This is the
second of the two synthesis follow-ups — the "給人看" half — and completes the
"both readable and retrievable" goal from the original synthesis brief.

## Goal

A read-only web page that lists the synthesized articles and lets a user read any
one in full, with its source citations. MVP: browse + read + keyword filter.

## Non-Goals (MVP)

- No generate/regenerate of articles from the UI.
- No delete/manage of articles.
- No per-article deep-link route, and no separate detail endpoint.
- No markdown rendering library — article bodies render as preformatted prose
  (`whitespace-pre-wrap`), matching how `Ask.tsx` renders answers.

## Architecture

One backend endpoint + one React page, following existing conventions. Articles are
read from the collection-scoped sibling
`ctx.store.sibling(f"{ctx.store.stats()['collection']}__articles")`; because `ctx`
already reflects the active collection (via the existing `withCollection` header),
collection scoping is automatic.

## Backend — `GET /api/articles`

Added to `src/opendomainmcp/api/app.py` inside `create_app` (next to `/api/items`),
matching the existing decorator style.

- Build the article sibling store from `ctx.store`.
- Return `article_store.get_items(limit, offset)` mapped to a flat list of records:
  ```
  {
    "id": str,
    "title": str,            # metadata.title
    "topic": str,            # metadata.topic
    "business_relevance": float,   # metadata.business_relevance (0 if absent)
    "cross_validated": bool, # metadata.cross_validated
    "sources": list[str],    # metadata.sources split on " | " ([] if absent)
    "body": str,             # the stored document text (the article body)
  }
  ```
- Accept optional `limit`/`offset` query params (default `limit=200, offset=0`) for
  parity with `/api/items`; articles are modest in count so the page loads all by
  default.
- **Empty / never-synthesized:** the sibling `get_or_create_collection` yields an
  empty collection → returns `[]`. No crash (Fail-Loud is satisfied: an empty list
  is the honest answer, and the page shows an explicit empty state).
- A record missing expected metadata (e.g. no `title`) falls back to `topic` then
  `id` for the display label — never raises.

`get_items` returns `{"id", "text", "metadata"}` per row (existing shape); `text`
is the body, `metadata` carries the article fields written by
`Article.metadata()` (`title`, `topic`, `business_relevance`, `cross_validated`,
`sources` joined by `" | "`).

## Frontend

### `web/src/api.ts`
- Add an `Article` interface mirroring the endpoint record.
- Add `api.articles()` → `GET /api/articles` through the existing `withCollection`
  helper and `headers()`, matching the style of `api.items(...)`.

### `web/src/pages/Articles.tsx`
A single page with in-page master/detail (mirrors `Browse.tsx` structure and reuses
`components/ui.tsx`):
- Loads `api.articles()` on mount; `Skeleton` while loading; `EmptyState`
  ("No articles yet — run `synthesize` to generate them.") when empty.
- **List (master):** one `Card` per article showing `title`, `topic`, a
  `business_relevance` `Badge`, and a `cross-validated` `Badge` when true.
- **Reader (detail):** selecting an article shows its `body` in a
  `whitespace-pre-wrap` block (same treatment as `Ask.tsx`) and its `sources` as a
  `file:line` list.
- **Filter:** a client-side keyword `Input` filtering the loaded list over
  title/topic/body (no server round-trip).
- `PageHeader` titled "Articles".

### `web/src/App.tsx` + `web/src/components/icons.tsx`
- Add a nav entry `{ to: "/articles", label: "Articles", icon: IconArticles }` to the
  nav array and the corresponding `<Route path="/articles" element={<Articles />} />`.
- Add an `IconArticles` (a document/article glyph) to `icons.tsx`, consistent with
  the existing icon set.

## Testing

### Backend (pytest, offline)
In `tests/test_api.py`, reusing the existing `client`/`store` fixtures:
- Seed the article sibling (`store.sibling(f"{store.stats()['collection']}__articles")`)
  with one `Article`; `GET /api/articles` returns it with all mapped fields
  (`title`, `topic`, `business_relevance`, `cross_validated`, `sources` as a list,
  `body`).
- With no articles seeded, `GET /api/articles` returns `[]` (200, empty).

### Frontend
- **Gate:** `npm run build` (TypeScript compiles, page wired into routes).
- **Smoke (Playwright):** add `web/tests/articles.spec.ts` mirroring the existing
  `web/tests/smoke.spec.ts` + `web/tests/helpers` pattern — navigate to `/articles`,
  assert the page header renders and (against a seeded/mock backend per the existing
  helper convention) a listed article opens its body. Confirm the helper/mock
  approach the other specs use during planning and match it.

## Open questions for spec review

1. Nav placement: put "Articles" right after "Ask" (reading-oriented) or after
   "Browse / Edit" (content-oriented)?
2. Should the list show a short body preview/snippet on each card, or only
   title/topic/badges (cleaner)?
3. Sort order of the list: by `business_relevance` desc (most relevant first), or by
   title A–Z?
