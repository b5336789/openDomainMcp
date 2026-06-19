# OpenDomainMCP — 開發過程記錄（Development Log）

> 本文件詳細記錄本輪「完成 PRD 所有功能」開發衝刺的過程：目標、現況盤點、
> 並行排程、各 wave 的任務、驗證結果與決策。產品需求見 [PRD.md](./PRD.md)，
> 任務清單見 [TASKS.md](./TASKS.md)，架構見 [ARCHITECTURE.md](./ARCHITECTURE.md)。

---

## 0. 衝刺目標（2026-06-19）

- 完成 PRD 列出的**所有**功能。
- 開發過程詳細記錄（本檔）。
- 各種技術文件與系統功能詳細說明放上網頁（`docs/*.html` 自動生成 + 前端建置）。
- 無相依的任務盡量並行（每個 subagent 持有互斥檔案集，避免合併衝突）。

## 1. 起始現況盤點

測試基線：`pytest` → **187 passed, 3 skipped**（3 skipped 為需要 MariaDB 連線的圖儲存整合測試）。

TASKS.md 狀態欄已過時：實際上 Entity Graph（4.1/4.2/4.3）、Workflow Graph（4.6/4.7，
PR #14）、Graph API（4.9）、Metrics 骨架（5.4）、Evals（5.8）皆已併入。

經 grep 驗證，**真正未完成**的任務共 18 項：

| 任務 | 說明 | 主要檔案 |
|------|------|----------|
| 3.2 | Wiki export 擷取 | `ingest/wiki.py`(新)、`loader.py` |
| 3.3 | 舊資料 review 回填 CLI | `cli.py`、`store/` |
| 3.6 | Workspace 來源登錄 | `api/app.py`、`web/Dashboard.tsx` |
| 4.4 | 程式碼相依抽取 | `graph/deps.py`(新)、`code_splitter.py`、`pipeline.py` |
| 4.5 | trace_dependency 升級 | `views/__init__.py` |
| 4.8 | 圖瀏覽 UI | `web/pages/Graph.tsx`(新) |
| 5.1 | Advisor 彙整器 | `advisor/`(新) |
| 5.2 | Advisor MCP 工具 | `server.py` |
| 5.3 | Advisor API + UI | `api/app.py`、`web/pages/Advisor.tsx`(新) |
| 5.5 | Product 指標 | `metrics/`、`api/app.py` |
| 5.6 | Agent 指標 | `metrics/`、`api/app.py` |
| 5.7 | 指標儀表板 | `web/pages/Metrics.tsx`(新) |
| 6.1 | 動態 MCP 端點發布 | `server.py`、`api/app.py`、`McpBuilder.tsx` |
| 6.2 | 權限/角色（RBAC） | `api/app.py`、`config.py` |
| 6.3 | 多租戶隔離 | `context.py`、`store/` |
| 6.4 | E2E 前端測試 | `web/tests/`(新) |
| 6.5 | CLI Git/Zip 文件補強 | `cli.py` |
| 6.7 | 觀測性/日誌 | `api/app.py` |

## 2. 並行排程策略

熱點檔案 `api/app.py`（被 3.6/5.3/5.5/5.6/6.1/6.2/6.7 共用）、前端 wiring
（`App.tsx`/`api.ts`/`main.tsx`）無法安全並行。策略：

- **後端純新模組 + 互斥檔案** → 並行 subagent（共享工作樹、檔案集互斥）。
- **`api/app.py`、前端 wiring** → 由主控（我）序列整合，避免合併衝突。

### Wave 1（5 個並行 subagent，檔案集互斥）

| Agent | 任務 | 持有檔案 |
|-------|------|----------|
| A1 | 3.2 Wiki 擷取 | `ingest/wiki.py`(新)、`loader.py` |
| A2 | 4.4 + 4.5 相依圖 + trace 升級 | `graph/deps.py`(新)、`code_splitter.py`、`pipeline.py`、`graph/store.py`、`graph/models.py`、`views/__init__.py` |
| A3 | 5.1 + 5.2 Advisor + MCP | `advisor/`(新)、`server.py` |
| A4 | 5.5 + 5.6 指標邏輯 | `metrics/__init__.py` |
| A5 | 3.3 + 6.5 backfill + CLI 文件 | `cli.py`、`store/chroma_store.py` |

（記錄持續更新於下方。）
