# Cloudflare Workers Migration Design

Date: 2026-03-25

## Goal

Eliminate the GCP VM entirely. Move all compute to Cloudflare (Workers, D1, R2, Pages, Queues).
Same functionality, no data loss, same async processing behavior.

## Architecture

```
Browser
  └─ Cloudflare Pages (React, auto-deploys on git push to main)
       └─ API calls → Cloudflare Workers API (Hono, all 45 routes)
                           ├─ D1 (SQLite-compatible database)
                           ├─ R2 (image storage)
                           └─ Cloudflare Queue
                                └─ Pipeline Worker (consumer)
                                     ├─ R2 (reads grid image)
                                     ├─ WASM HEIC decoder (libheif-wasm)
                                     ├─ Canvas/WASM image cropping
                                     ├─ Anthropic Vision API (claude-opus-4-6)
                                     └─ D1 + R2 (writes results)
```

Auth: Cloudflare Access protects both Pages and the API Worker. No auth code in the app.

## Data Layer

### D1 Database (single database, 5 tables)

- `cards` — deduplicated card registry
- `cards_complete` — one row per physical card copy
- `undo_transactions` — reversible operations with before/after JSON
- `system_logs` — upload/processing/verification events
- `processing_jobs` — queue job status tracking (new table)

### R2 Bucket (`trading-cards`)

```
unprocessed/          uploaded grid images waiting to process
pending/
  json/               extracted card data JSON per grid
  images/             cropped individual card backs (9 per grid)
  bulk-back/          original grid image after processing
verified/
  images/             original grid images after cards are passed
  cropped/            individual card backs after cards are passed
```

## API Worker

- Framework: Hono
- All 45 existing routes ported 1:1 (same URL paths, same request/response shapes)
- React frontend unchanged except REACT_APP_API_BASE points to Worker URL
- File uploads: multipart form data parsed natively (replaces multer)
- Image serving: streamed from R2 (replaces local sendFile)
- DB ops: D1 prepared statements (replaces SQLAlchemy/Python subprocess calls)
- Processing trigger: enqueues to Queue, returns job_id immediately
- Status polling: reads processing_jobs table in D1
- CORS: locked to Pages domain + localhost

## Pipeline Worker (Queue Consumer)

Triggered by queue message `{ job_id, filenames[] }`.

Per grid:
1. Read image bytes from R2 `unprocessed/`
2. HEIC → JPEG via libheif-wasm if needed
3. Base64 encode for Anthropic API
4. Call claude-opus-4-6 with same prompt as current Python pipeline
5. Crop 3x3 grid → 9 individual images via WASM canvas library
6. Write JSON to R2 `pending/json/`, cropped images to R2 `pending/images/`
7. Move original to R2 `pending/bulk-back/`
8. Update processing_jobs in D1 (progress tracking for polling)
9. On error: mark job failed, leave files in `unprocessed/` for retry

Queue consumer processes grids sequentially per batch. Max 15 min runtime per batch.

## Migration Sequence (VM stays live, no downtime)

1. Create D1 + schema, export SQLite from VM, import to D1
2. Create R2 bucket, upload all images from VM via wrangler
3. Deploy API Worker + Pipeline Worker, verify all routes
4. Connect Pages to git repo, set REACT_APP_API_BASE to Worker URL
5. End-to-end verification: upload → process → verify → database
6. Switch trading-cards.harlanswitzer.com DNS to Pages
7. Decommission VM

## Repository Structure

New `workers/` folder at repo root:

```
workers/
  api/          Hono API Worker (all 45 routes)
  pipeline/     Queue consumer Worker (image processing pipeline)
  schema.sql    D1 schema (DDL for all 5 tables)
```

React code stays at `app/ui/client/` unchanged.

## Cloudflare Resources

- 1 Worker: API (Hono)
- 1 Worker: Pipeline (Queue consumer)
- 1 D1 database
- 1 R2 bucket: trading-cards
- 1 Queue: pipeline-jobs
- 1 Pages project: connected to git repo main branch
- Cloudflare Access: protects Pages + API Worker
