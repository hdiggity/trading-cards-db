# Cloudflare Workers Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate the trading cards app from a GCP VM (Node + Python + SQLite) to Cloudflare Workers + D1 + R2 + Pages + Queues, with no functionality lost and no data lost.

**Architecture:** React on Cloudflare Pages → Hono API Worker (all 45 routes) → D1 (database) + R2 (images) + Cloudflare Queue → Pipeline Worker (HEIC decode, Anthropic Vision, image crop, D1/R2 writes). Cloudflare Access handles auth — no auth code in the app.

**Tech Stack:** Hono (Worker framework), Cloudflare D1 (SQLite-compatible), Cloudflare R2 (object storage), Cloudflare Queues (async jobs), Cloudflare Pages (React hosting), libheif-wasm (HEIC decode), jimp (image crop), wrangler CLI, Anthropic SDK

**Reference:** Design doc at `docs/plans/2026-03-25-cloudflare-workers-migration-design.md`

---

### Task 1: Scaffold workers/ directory and wrangler projects

**Files:**
- Create: `workers/api/package.json`
- Create: `workers/api/wrangler.toml`
- Create: `workers/api/src/index.ts`
- Create: `workers/pipeline/package.json`
- Create: `workers/pipeline/wrangler.toml`
- Create: `workers/pipeline/src/index.ts`

**Step 1: Create workers/api package**

```bash
mkdir -p workers/api/src workers/pipeline/src
```

**Step 2: Write workers/api/package.json**

```json
{
  "name": "trading-cards-api",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy",
    "cf-typegen": "wrangler types"
  },
  "dependencies": {
    "hono": "^4.6.0"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20241205.0",
    "typescript": "^5.0.0",
    "wrangler": "^4.0.0"
  }
}
```

**Step 3: Write workers/api/wrangler.toml**

```toml
name = "trading-cards-api"
main = "src/index.ts"
compatibility_date = "2024-12-01"
compatibility_flags = ["nodejs_compat"]

[[d1_databases]]
binding = "DB"
database_name = "trading-cards"
database_id = "PLACEHOLDER"

[[r2_buckets]]
binding = "STORAGE"
bucket_name = "trading-cards"

[[queues.producers]]
binding = "PIPELINE_QUEUE"
queue = "pipeline-jobs"

[vars]
ENVIRONMENT = "production"
```

**Step 4: Write workers/api/src/index.ts (skeleton)**

```typescript
import { Hono } from 'hono'
import { cors } from 'hono/cors'

export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  PIPELINE_QUEUE: Queue
  ANTHROPIC_API_KEY: string
}

const app = new Hono<{ Bindings: Env }>()

app.use('*', cors({
  origin: ['https://trading-cards.harlanswitzer.com', 'http://localhost:3000'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization'],
}))

app.get('/health', (c) => c.json({ status: 'ok', service: 'trading-cards-api' }))

export default app
```

**Step 5: Write workers/pipeline/package.json**

```json
{
  "name": "trading-cards-pipeline",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "wrangler dev",
    "deploy": "wrangler deploy"
  },
  "dependencies": {
    "jimp": "^1.6.0"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20241205.0",
    "typescript": "^5.0.0",
    "wrangler": "^4.0.0"
  }
}
```

**Step 6: Write workers/pipeline/wrangler.toml**

```toml
name = "trading-cards-pipeline"
main = "src/index.ts"
compatibility_date = "2024-12-01"
compatibility_flags = ["nodejs_compat"]

[[d1_databases]]
binding = "DB"
database_name = "trading-cards"
database_id = "PLACEHOLDER"

[[r2_buckets]]
binding = "STORAGE"
bucket_name = "trading-cards"

[[queues.consumers]]
queue = "pipeline-jobs"
max_batch_size = 5
max_batch_timeout = 30
max_retries = 2
```

**Step 7: Write workers/pipeline/src/index.ts (skeleton)**

```typescript
export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  ANTHROPIC_API_KEY: string
}

export default {
  async queue(batch: MessageBatch, env: Env): Promise<void> {
    for (const message of batch.messages) {
      console.log('Processing job:', message.body)
      message.ack()
    }
  }
}
```

**Step 8: Install deps in both workers**

```bash
cd workers/api && npm install
cd ../pipeline && npm install
```

**Step 9: Commit**

```bash
git add workers/
git commit -m "scaffold workers/api and workers/pipeline wrangler projects"
```

---

### Task 2: Create Cloudflare resources (D1, R2, Queue)

**Step 1: Create D1 database**

```bash
cd workers/api
npx wrangler d1 create trading-cards
```

Copy the `database_id` from output. Update both `workers/api/wrangler.toml` and `workers/pipeline/wrangler.toml`, replacing `PLACEHOLDER` with the real ID.

**Step 2: Create R2 bucket**

```bash
npx wrangler r2 bucket create trading-cards
```

Note: the `trading-cards-backup` bucket already exists — this creates a new `trading-cards` bucket for active data.

**Step 3: Create Queue**

```bash
npx wrangler queues create pipeline-jobs
```

**Step 4: Set Anthropic API key as Worker secret**

```bash
cd workers/api
npx wrangler secret put ANTHROPIC_API_KEY
# paste key when prompted

cd ../pipeline
npx wrangler secret put ANTHROPIC_API_KEY
```

**Step 5: Commit updated wrangler.toml files**

```bash
git add workers/api/wrangler.toml workers/pipeline/wrangler.toml
git commit -m "add cloudflare resource IDs to wrangler configs"
```

---

### Task 3: D1 schema

**Files:**
- Create: `workers/schema.sql`

**Step 1: Write schema**

```sql
-- workers/schema.sql

CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  sport TEXT DEFAULT 'baseball',
  brand TEXT,
  number TEXT,
  copyright_year TEXT,
  team TEXT,
  card_set TEXT,
  condition TEXT,
  is_player INTEGER DEFAULT 1,
  features TEXT,
  value_estimate TEXT,
  notes TEXT,
  quantity INTEGER DEFAULT 1,
  date_added TEXT DEFAULT (datetime('now')),
  last_updated TEXT,
  canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS cards_complete (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  sport TEXT,
  brand TEXT,
  number TEXT,
  copyright_year TEXT,
  team TEXT,
  card_set TEXT,
  condition TEXT,
  is_player INTEGER,
  features TEXT,
  value_estimate TEXT,
  notes TEXT,
  quantity INTEGER,
  last_updated TEXT,
  source_file TEXT,
  grid_position TEXT,
  original_filename TEXT,
  verification_date TEXT DEFAULT (datetime('now')),
  verified_by TEXT,
  cropped_back_file TEXT,
  canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS undo_transactions (
  id INTEGER PRIMARY KEY,
  session_id TEXT,
  card_id INTEGER,
  action TEXT,
  before_state TEXT,
  after_state TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_logs (
  id INTEGER PRIMARY KEY,
  event_type TEXT,
  filename TEXT,
  details TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_jobs (
  id TEXT PRIMARY KEY,
  status TEXT DEFAULT 'queued',
  total INTEGER DEFAULT 0,
  processed INTEGER DEFAULT 0,
  error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_complete_card_id ON cards_complete(card_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status);
```

**Step 2: Apply schema to D1**

```bash
cd workers/api
npx wrangler d1 execute trading-cards --file=../schema.sql
```

Expected output: `Successfully applied 1 migration`

**Step 3: Verify schema**

```bash
npx wrangler d1 execute trading-cards --command="SELECT name FROM sqlite_master WHERE type='table'"
```

Expected: 5 table names listed.

**Step 4: Commit**

```bash
git add workers/schema.sql
git commit -m "add d1 schema for trading cards migration"
```

---

### Task 4: Data migration — SQLite to D1

**Files:**
- Create: `workers/migrate/export-sqlite.sh`
- Create: `workers/migrate/import-to-d1.sh`

**Step 1: Write export script**

```bash
# workers/migrate/export-sqlite.sh
#!/usr/bin/env bash
# Run from repo root. Exports VM SQLite data to local JSON files.
set -euo pipefail

mkdir -p workers/migrate/data

gcloud compute ssh "harlan@trading-cards" --zone=us-central1-a -- \
  "python3 -c \"
import sqlite3, json
conn = sqlite3.connect('/opt/trading_cards_db/cards/verified/trading_cards.db')
conn.row_factory = sqlite3.Row

for table in ['cards', 'cards_complete']:
    rows = [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]
    print(f'{table}: {len(rows)} rows')
    open(f'/tmp/{table}.json', 'w').write(json.dumps(rows))
\"" 2>&1 | grep -v 'Ignoring unknown'

gcloud compute scp "harlan@trading-cards:/tmp/cards.json" workers/migrate/data/ --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'
gcloud compute scp "harlan@trading-cards:/tmp/cards_complete.json" workers/migrate/data/ --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'

echo "Exported to workers/migrate/data/"
```

**Step 2: Run export**

```bash
chmod +x workers/migrate/export-sqlite.sh
./workers/migrate/export-sqlite.sh
```

Expected: `cards: 901 rows` and `cards_complete: 1053 rows` printed, two JSON files in `workers/migrate/data/`.

**Step 3: Write import script**

```bash
# workers/migrate/import-to-d1.sh
#!/usr/bin/env bash
# Run from workers/api/. Imports JSON data into D1 in batches.
set -euo pipefail

node -e "
const fs = require('fs')
const cards = JSON.parse(fs.readFileSync('../migrate/data/cards.json'))
const cc = JSON.parse(fs.readFileSync('../migrate/data/cards_complete.json'))

function escStr(v) {
  if (v === null || v === undefined) return 'NULL'
  return \"'\" + String(v).replace(/'/g, \"''\") + \"'\"
}

function rowToInsert(table, row) {
  const keys = Object.keys(row).join(', ')
  const vals = Object.values(row).map(escStr).join(', ')
  return \`INSERT OR IGNORE INTO \${table} (\${keys}) VALUES (\${vals});\`
}

let sql = ''
for (const r of cards) sql += rowToInsert('cards', r) + '\n'
fs.writeFileSync('../migrate/data/cards.sql', sql)

sql = ''
for (const r of cc) sql += rowToInsert('cards_complete', r) + '\n'
fs.writeFileSync('../migrate/data/cards_complete.sql', sql)

console.log('SQL files written')
"

npx wrangler d1 execute trading-cards --file=../migrate/data/cards.sql
npx wrangler d1 execute trading-cards --file=../migrate/data/cards_complete.sql
echo "Import complete"
```

**Step 4: Run import**

```bash
chmod +x workers/migrate/import-to-d1.sh
cd workers/api && bash ../migrate/import-to-d1.sh
```

**Step 5: Verify counts**

```bash
npx wrangler d1 execute trading-cards --command="SELECT COUNT(*) as n FROM cards"
npx wrangler d1 execute trading-cards --command="SELECT COUNT(*) as n FROM cards_complete"
```

Expected: 901 and 1053.

**Step 6: Commit migration scripts (not data files)**

```bash
git add workers/migrate/
echo "workers/migrate/data/" >> .gitignore
git add .gitignore
git commit -m "add d1 data migration scripts"
```

---

### Task 5: Data migration — images to R2

**Files:**
- Create: `workers/migrate/sync-images-to-r2.sh`

**Step 1: Write sync script**

```bash
# workers/migrate/sync-images-to-r2.sh
#!/usr/bin/env bash
# Rsyncs all card images from VM to R2 via wrangler.
set -euo pipefail

TMP=$(mktemp -d)
echo "==> downloading images from VM to $TMP..."

gcloud compute ssh "harlan@trading-cards" --zone=us-central1-a -- \
  "tar -czf /tmp/card-images.tar.gz -C /opt/trading_cards_db/cards verified pending_verification" \
  2>&1 | grep -v 'Ignoring unknown'

gcloud compute scp "harlan@trading-cards:/tmp/card-images.tar.gz" "$TMP/" \
  --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'

echo "==> extracting..."
tar -xzf "$TMP/card-images.tar.gz" -C "$TMP"

echo "==> uploading verified images to R2..."
find "$TMP/verified" -type f \( -name "*.jpg" -o -name "*.png" -o -name "*.jpeg" \) | while read f; do
  key="verified/$(basename "$f")"
  npx wrangler r2 object put "trading-cards/$key" --file="$f" --content-type="image/jpeg" 2>/dev/null
  echo "  uploaded: $key"
done

echo "==> uploading pending images to R2..."
find "$TMP/pending_verification" -type f \( -name "*.jpg" -o -name "*.png" -o -name "*.jpeg" \) | while read f; do
  key="pending/images/$(basename "$f")"
  npx wrangler r2 object put "trading-cards/$key" --file="$f" --content-type="image/jpeg" 2>/dev/null
  echo "  uploaded: $key"
done

echo "==> done. cleaning up $TMP"
rm -rf "$TMP"
```

**Step 2: Run sync (run from repo root)**

```bash
chmod +x workers/migrate/sync-images-to-r2.sh
cd workers/api && bash ../migrate/sync-images-to-r2.sh
```

This will take several minutes for ~1169 images. Expected: lines of `uploaded: ...` for each file.

**Step 3: Verify spot-check**

```bash
npx wrangler r2 object get trading-cards/verified/$(npx wrangler r2 object list trading-cards --prefix=verified/ 2>/dev/null | grep -m1 '"key"' | awk -F'"' '{print $4}') --file=/tmp/spot-check.jpg 2>/dev/null && echo "R2 read OK" || echo "FAILED"
```

**Step 4: Commit script**

```bash
git add workers/migrate/sync-images-to-r2.sh
git commit -m "add image sync script for r2 migration"
```

---

### Task 6: API Worker — health, cards list, search

**Files:**
- Create: `workers/api/src/routes/health.ts`
- Create: `workers/api/src/routes/cards.ts`
- Modify: `workers/api/src/index.ts`

**Step 1: Write health route**

```typescript
// workers/api/src/routes/health.ts
import { Hono } from 'hono'
import { Env } from '../index'

const health = new Hono<{ Bindings: Env }>()

health.get('/', async (c) => {
  try {
    await c.env.DB.prepare('SELECT 1').run()
    return c.json({ status: 'ok', db: 'ok', service: 'trading-cards-api' })
  } catch (e) {
    return c.json({ status: 'error', db: String(e) }, 500)
  }
})

export default health
```

**Step 2: Write cards route (GET /api/cards)**

```typescript
// workers/api/src/routes/cards.ts
import { Hono } from 'hono'
import { Env } from '../index'

const cards = new Hono<{ Bindings: Env }>()

cards.get('/', async (c) => {
  const { search, brand, team, sport, number, sort = 'date_added', order = 'desc', page = '1', limit = '50' } = c.req.query()

  let query = 'SELECT * FROM cards WHERE 1=1'
  const params: string[] = []

  if (search) {
    query += ' AND (name LIKE ? OR brand LIKE ? OR team LIKE ?)'
    const s = `%${search}%`
    params.push(s, s, s)
  }
  if (brand) { query += ' AND brand = ?'; params.push(brand) }
  if (team) { query += ' AND team = ?'; params.push(team) }
  if (sport) { query += ' AND sport = ?'; params.push(sport) }
  if (number) { query += ' AND number = ?'; params.push(number) }

  const validSorts = ['name', 'brand', 'team', 'date_added', 'last_updated', 'quantity', 'value_estimate']
  const sortCol = validSorts.includes(sort) ? sort : 'date_added'
  const sortDir = order === 'asc' ? 'ASC' : 'DESC'
  query += ` ORDER BY ${sortCol} ${sortDir}`

  const pageNum = Math.max(1, parseInt(page))
  const limitNum = Math.min(200, Math.max(1, parseInt(limit)))
  const offset = (pageNum - 1) * limitNum
  query += ` LIMIT ? OFFSET ?`
  params.push(String(limitNum), String(offset))

  const rows = await c.env.DB.prepare(query).bind(...params).all()
  return c.json({ cards: rows.results, page: pageNum, limit: limitNum })
})

cards.get('/stats', async (c) => {
  const total = await c.env.DB.prepare('SELECT COUNT(*) as n FROM cards').first<{ n: number }>()
  const totalComplete = await c.env.DB.prepare('SELECT COUNT(*) as n FROM cards_complete').first<{ n: number }>()
  return c.json({ total_cards: total?.n ?? 0, total_copies: totalComplete?.n ?? 0 })
})

export default cards
```

**Step 3: Mount routes in index.ts**

```typescript
// workers/api/src/index.ts
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import health from './routes/health'
import cards from './routes/cards'

export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  PIPELINE_QUEUE: Queue
  ANTHROPIC_API_KEY: string
}

const app = new Hono<{ Bindings: Env }>()

app.use('*', cors({
  origin: ['https://trading-cards.harlanswitzer.com', 'http://localhost:3000'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization'],
}))

app.route('/health', health)
app.route('/api/cards', cards)

export default app
```

**Step 4: Test locally**

```bash
cd workers/api && npm run dev
```

In another terminal:

```bash
curl http://localhost:8787/health
# Expected: {"status":"ok","db":"ok","service":"trading-cards-api"}

curl "http://localhost:8787/api/cards?limit=2"
# Expected: {"cards":[...2 cards...],"page":1,"limit":2}
```

**Step 5: Commit**

```bash
git add workers/api/src/
git commit -m "add health and cards list routes to api worker"
```

---

### Task 7: API Worker — pending cards, pass, fail

**Files:**
- Create: `workers/api/src/routes/verification.ts`
- Modify: `workers/api/src/index.ts`

**Step 1: Write verification routes**

```typescript
// workers/api/src/routes/verification.ts
import { Hono } from 'hono'
import { Env } from '../index'

const verification = new Hono<{ Bindings: Env }>()

// GET /api/pending-cards — list pending JSON files from R2
verification.get('/pending-cards', async (c) => {
  const list = await c.env.STORAGE.list({ prefix: 'pending/json/' })
  const results = []
  for (const obj of list.objects) {
    const raw = await c.env.STORAGE.get(obj.key)
    if (!raw) continue
    const data = await raw.json<any>()
    results.push({ id: obj.key.replace('pending/json/', '').replace('.json', ''), ...data })
  }
  return c.json(results)
})

// POST /api/pass-card/:id/:cardIndex
verification.post('/pass-card/:id/:cardIndex', async (c) => {
  const { id, cardIndex } = c.req.param()
  const { modifiedData } = await c.req.json<{ modifiedData: any }>()
  const idx = parseInt(cardIndex)

  // Read pending JSON
  const jsonKey = `pending/json/${id}.json`
  const raw = await c.env.STORAGE.get(jsonKey)
  if (!raw) return c.json({ error: 'Pending card not found' }, 404)
  const pendingData = await raw.json<any>()
  const cards = Array.isArray(pendingData.cards) ? pendingData.cards : [pendingData]
  const card = { ...cards[idx], ...modifiedData }

  // Upsert into cards table (deduplicate by name+brand+number)
  const existing = await c.env.DB.prepare(
    'SELECT id FROM cards WHERE name = ? AND brand = ? AND number = ?'
  ).bind(card.name, card.brand ?? null, card.number ?? null).first<{ id: number }>()

  let cardId: number
  if (existing) {
    await c.env.DB.prepare('UPDATE cards SET quantity = quantity + 1, last_updated = datetime("now") WHERE id = ?')
      .bind(existing.id).run()
    cardId = existing.id
  } else {
    const result = await c.env.DB.prepare(
      `INSERT INTO cards (name, sport, brand, number, copyright_year, team, card_set, condition, is_player, features, value_estimate, notes, canonical_name)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      card.name, card.sport ?? 'baseball', card.brand ?? null, card.number ?? null,
      card.copyright_year ?? null, card.team ?? null, card.card_set ?? null,
      card.condition ?? null, card.is_player ?? 1, card.features ?? null,
      card.value_estimate ?? null, card.notes ?? null, card.canonical_name ?? null
    ).run()
    cardId = result.meta.last_row_id as number
  }

  // Insert into cards_complete
  await c.env.DB.prepare(
    `INSERT INTO cards_complete (card_id, name, sport, brand, number, copyright_year, team, card_set, condition, is_player, features, value_estimate, notes, source_file, grid_position, original_filename, cropped_back_file, canonical_name)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).bind(
    cardId, card.name, card.sport ?? 'baseball', card.brand ?? null, card.number ?? null,
    card.copyright_year ?? null, card.team ?? null, card.card_set ?? null,
    card.condition ?? null, card.is_player ?? 1, card.features ?? null,
    card.value_estimate ?? null, card.notes ?? null,
    card.source_file ?? null, String(idx), card.original_filename ?? null,
    card.cropped_back_file ?? null, card.canonical_name ?? null
  ).run()

  // If all cards in this grid are resolved, clean up pending JSON
  const allResolved = cards.every((_: any, i: number) => i === idx || cards[i]?.resolved)
  if (allResolved) {
    await c.env.STORAGE.delete(jsonKey)
  } else {
    cards[idx] = { ...card, resolved: true }
    await c.env.STORAGE.put(jsonKey, JSON.stringify({ ...pendingData, cards }))
  }

  return c.json({ success: true, cardId })
})

// POST /api/fail-card/:id/:cardIndex
verification.post('/fail-card/:id/:cardIndex', async (c) => {
  const { id, cardIndex } = c.req.param()
  const idx = parseInt(cardIndex)
  const jsonKey = `pending/json/${id}.json`
  const raw = await c.env.STORAGE.get(jsonKey)
  if (!raw) return c.json({ error: 'Pending card not found' }, 404)
  const pendingData = await raw.json<any>()
  const cards = Array.isArray(pendingData.cards) ? pendingData.cards : [pendingData]
  cards[idx] = { ...cards[idx], resolved: true, failed: true }
  await c.env.STORAGE.put(jsonKey, JSON.stringify({ ...pendingData, cards }))
  return c.json({ success: true })
})

export default verification
```

**Step 2: Mount in index.ts**

Add to `workers/api/src/index.ts`:
```typescript
import verification from './routes/verification'
// ...
app.route('/api', verification)
```

**Step 3: Test locally**

```bash
curl http://localhost:8787/api/pending-cards
# Expected: [] (empty if no pending cards) or array of pending grids
```

**Step 4: Commit**

```bash
git add workers/api/src/
git commit -m "add verification routes: pending-cards, pass-card, fail-card"
```

---

### Task 8: API Worker — image upload and serving

**Files:**
- Create: `workers/api/src/routes/images.ts`
- Modify: `workers/api/src/index.ts`

**Step 1: Write image routes**

```typescript
// workers/api/src/routes/images.ts
import { Hono } from 'hono'
import { Env } from '../index'

const images = new Hono<{ Bindings: Env }>()

// POST /api/upload — save to R2 unprocessed/
images.post('/upload', async (c) => {
  const formData = await c.req.formData()
  const file = formData.get('image') as File | null
  if (!file) return c.json({ error: 'No file uploaded' }, 400)

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  const filename = `${timestamp}_${file.name.replace(/['"\\]/g, '_')}`
  const key = `unprocessed/${filename}`

  const bytes = await file.arrayBuffer()
  await c.env.STORAGE.put(key, bytes, {
    httpMetadata: { contentType: file.type || 'image/jpeg' },
    customMetadata: { originalName: file.name }
  })

  await c.env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES ('upload', ?, ?)"
  ).bind(filename, JSON.stringify({ size: file.size, type: file.type })).run()

  return c.json({ success: true, filename })
})

// GET /api/bulk-back-image/:filename — serve from R2
images.get('/bulk-back-image/:filename', async (c) => {
  const { filename } = c.req.param()
  const obj = await c.env.STORAGE.get(`pending/bulk-back/${filename}`)
    ?? await c.env.STORAGE.get(`unprocessed/${filename}`)
  if (!obj) return c.json({ error: 'Not found' }, 404)
  return new Response(obj.body, {
    headers: { 'Content-Type': 'image/jpeg', 'Cache-Control': 'public, max-age=86400' }
  })
})

// GET /api/cropped-back-image/:filename — serve from R2
images.get('/cropped-back-image/:filename', async (c) => {
  const { filename } = c.req.param()
  const obj = await c.env.STORAGE.get(`pending/images/${filename}`)
    ?? await c.env.STORAGE.get(`verified/cropped/${filename}`)
  if (!obj) return c.json({ error: 'Not found' }, 404)
  return new Response(obj.body, {
    headers: { 'Content-Type': 'image/jpeg', 'Cache-Control': 'public, max-age=86400' }
  })
})

// GET /api/raw-scan-count
images.get('/raw-scan-count', async (c) => {
  const list = await c.env.STORAGE.list({ prefix: 'unprocessed/' })
  return c.json({ count: list.objects.length })
})

export default images
```

**Step 2: Mount in index.ts**

```typescript
import images from './routes/images'
// ...
app.route('/api', images)
```

**Step 3: Test upload**

```bash
curl -X POST http://localhost:8787/api/upload \
  -F "image=@/path/to/test.jpg"
# Expected: {"success":true,"filename":"2026-...test.jpg"}
```

**Step 4: Commit**

```bash
git add workers/api/src/
git commit -m "add image upload and serving routes"
```

---

### Task 9: API Worker — pipeline trigger and status

**Files:**
- Create: `workers/api/src/routes/pipeline.ts`
- Modify: `workers/api/src/index.ts`

**Step 1: Write pipeline routes**

```typescript
// workers/api/src/routes/pipeline.ts
import { Hono } from 'hono'
import { Env } from '../index'

const pipeline = new Hono<{ Bindings: Env }>()

// POST /api/process-raw-scans
pipeline.post('/process-raw-scans', async (c) => {
  const body = await c.req.json<{ count?: number }>().catch(() => ({}))
  const list = await c.env.STORAGE.list({ prefix: 'unprocessed/' })
  const files = list.objects.map(o => o.key.replace('unprocessed/', ''))

  if (files.length === 0) {
    return c.json({ error: 'No images to process', count: 0 }, 400)
  }

  const toProcess = body.count ? files.slice(0, body.count) : files
  const jobId = crypto.randomUUID()

  await c.env.DB.prepare(
    "INSERT INTO processing_jobs (id, status, total, processed) VALUES (?, 'queued', ?, 0)"
  ).bind(jobId, toProcess.length).run()

  await c.env.PIPELINE_QUEUE.send({ jobId, filenames: toProcess })

  return c.json({ success: true, jobId, total: toProcess.length })
})

// GET /api/processing-status
pipeline.get('/processing-status', async (c) => {
  const job = await c.env.DB.prepare(
    "SELECT * FROM processing_jobs ORDER BY created_at DESC LIMIT 1"
  ).first<any>()

  if (!job) return c.json({ active: false })

  const isActive = job.status === 'queued' || job.status === 'processing'
  const progress = job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0

  return c.json({
    active: isActive,
    status: job.status,
    progress,
    total: job.total,
    processed: job.processed,
    error: job.error ?? null,
    jobId: job.id
  })
})

// POST /api/cancel-processing
pipeline.post('/cancel-processing', async (c) => {
  await c.env.DB.prepare(
    "UPDATE processing_jobs SET status = 'cancelled', updated_at = datetime('now') WHERE status IN ('queued', 'processing')"
  ).run()
  return c.json({ success: true })
})

export default pipeline
```

**Step 2: Mount in index.ts**

```typescript
import pipeline from './routes/pipeline'
// ...
app.route('/api', pipeline)
```

**Step 3: Test**

```bash
curl -X POST http://localhost:8787/api/process-raw-scans \
  -H 'Content-Type: application/json' \
  -d '{"count":1}'
# Expected: {"success":true,"jobId":"...","total":1}

curl http://localhost:8787/api/processing-status
# Expected: {"active":true,"status":"queued","progress":0,...}
```

**Step 4: Commit**

```bash
git add workers/api/src/
git commit -m "add pipeline trigger and processing status routes"
```

---

### Task 10: API Worker — remaining routes (field options, storage analysis, undo, logs)

**Files:**
- Create: `workers/api/src/routes/misc.ts`
- Modify: `workers/api/src/index.ts`

**Step 1: Write misc routes**

```typescript
// workers/api/src/routes/misc.ts
import { Hono } from 'hono'
import { Env } from '../index'

const misc = new Hono<{ Bindings: Env }>()

// GET /api/field-options — distinct values for filter dropdowns
misc.get('/field-options', async (c) => {
  const [brands, teams, sports, conditions] = await Promise.all([
    c.env.DB.prepare("SELECT DISTINCT brand FROM cards WHERE brand IS NOT NULL ORDER BY brand").all(),
    c.env.DB.prepare("SELECT DISTINCT team FROM cards WHERE team IS NOT NULL ORDER BY team").all(),
    c.env.DB.prepare("SELECT DISTINCT sport FROM cards WHERE sport IS NOT NULL ORDER BY sport").all(),
    c.env.DB.prepare("SELECT DISTINCT condition FROM cards WHERE condition IS NOT NULL ORDER BY condition").all(),
  ])
  return c.json({
    brands: brands.results.map((r: any) => r.brand),
    teams: teams.results.map((r: any) => r.team),
    sports: sports.results.map((r: any) => r.sport),
    conditions: conditions.results.map((r: any) => r.condition),
  })
})

// GET /api/database-stats
misc.get('/database-stats', async (c) => {
  const [cards, copies] = await Promise.all([
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards").first<{ n: number }>(),
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards_complete").first<{ n: number }>(),
  ])
  return c.json({ total_cards: cards?.n ?? 0, total_copies: copies?.n ?? 0 })
})

// GET /api/system-logs
misc.get('/system-logs', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 100"
  ).all()
  return c.json(rows.results)
})

// POST /api/storage-analysis — call Anthropic Vision on uploaded image
misc.post('/storage-analysis', async (c) => {
  const { filename } = await c.req.json<{ filename: string }>()
  if (!filename) return c.json({ error: 'No filename provided' }, 400)

  const obj = await c.env.STORAGE.get(`unprocessed/${filename}`)
  if (!obj) return c.json({ error: 'File not found' }, 404)

  const bytes = await obj.arrayBuffer()
  const b64 = btoa(String.fromCharCode(...new Uint8Array(bytes)))

  const prompt = `I upload photos of baseball cards, usually arranged in grids. You identify each card individually and treat them one by one, not as a group. For each card, you determine what type of card it is (player card, prospect, checklist, stat card, Bowman paper vs Chrome, etc.). You consider the player, career outcome, era, brand, year, condition visible in the photo, and typical market value. You assume my default storage is cards stored in boxes in rows, out of light, protected, for long term value preservation.

For each card, you give a per-card storage recommendation, choosing only from:
    •    no protection
    •    penny sleeve
    •    top loader
    •    special storage (only for genuinely high-value cases)

You do not overprotect low-value commons, even if the player had a good career. High-value may get top loaders.

FORMAT YOUR RESPONSE AS ONE LINE PER CARD:
Card [number]: [player name, year, brand, card type] | Storage: [recommendation] | Reason: [brief explanation] | Price: [estimated market value]

Separate each card with a blank line.

DO NOT include summary guidance, general recommendations, or offers for future analysis. Only provide the per-card recommendations in the format specified above.`

  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': c.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: 'claude-opus-4-6',
      max_tokens: 4000,
      messages: [{ role: 'user', content: [
        { type: 'text', text: prompt },
        { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: b64 } }
      ]}]
    })
  })

  if (!resp.ok) {
    const err = await resp.text()
    return c.json({ error: 'Anthropic API error', details: err }, 500)
  }

  const result = await resp.json<any>()
  return c.json({ recommendations: result.content[0].text })
})

// POST /api/undo/:id
misc.post('/undo/:id', async (c) => {
  const { id } = c.req.param()
  const tx = await c.env.DB.prepare(
    "SELECT * FROM undo_transactions WHERE id = ?"
  ).bind(id).first<any>()
  if (!tx) return c.json({ error: 'Transaction not found' }, 404)

  const before = JSON.parse(tx.before_state)
  await c.env.DB.prepare("DELETE FROM cards_complete WHERE id = ?").bind(tx.card_id).run()

  if (before.deleted) {
    await c.env.DB.prepare(
      "INSERT INTO cards (id, name, sport, brand, number, copyright_year, team, card_set, condition, is_player, features, value_estimate, notes, quantity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ).bind(before.id, before.name, before.sport, before.brand, before.number, before.copyright_year, before.team, before.card_set, before.condition, before.is_player, before.features, before.value_estimate, before.notes, before.quantity).run()
  } else {
    await c.env.DB.prepare("UPDATE cards SET quantity = quantity - 1, last_updated = datetime('now') WHERE id = ?")
      .bind(before.card_id).run()
  }

  await c.env.DB.prepare("DELETE FROM undo_transactions WHERE id = ?").bind(id).run()
  return c.json({ success: true })
})

export default misc
```

**Step 2: Mount in index.ts**

```typescript
import misc from './routes/misc'
// ...
app.route('/api', misc)
```

**Step 3: Verify all routes load**

```bash
cd workers/api && npm run dev
curl http://localhost:8787/api/field-options
# Expected: {"brands":[...],"teams":[...],...}
```

**Step 4: Commit**

```bash
git add workers/api/src/
git commit -m "add field options, storage analysis, undo, logs routes"
```

---

### Task 11: Pipeline Worker — HEIC decode, Vision API, crop, write results

**Files:**
- Modify: `workers/pipeline/src/index.ts`

**Step 1: Install HEIC and image deps**

```bash
cd workers/pipeline
npm install jimp
```

Note: For HEIC decoding in Workers, use `libheif-js` (pure WASM build). Install it:

```bash
npm install libheif-js
```

**Step 2: Write full pipeline worker**

```typescript
// workers/pipeline/src/index.ts
import Jimp from 'jimp'

export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  ANTHROPIC_API_KEY: string
}

interface PipelineJob {
  jobId: string
  filenames: string[]
}

async function decodeImage(bytes: ArrayBuffer, filename: string): Promise<ArrayBuffer> {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.heic') || lower.endsWith('.heif')) {
    // Decode HEIC via libheif-js
    const libheif = await import('libheif-js')
    const decoder = new libheif.HeifDecoder()
    const data = decoder.decode(new Uint8Array(bytes))
    if (!data.length) throw new Error('HEIC decode failed')
    const image = data[0]
    const w = image.get_width()
    const h = image.get_height()
    const pixels = await new Promise<Uint8Array>((resolve, reject) => {
      image.display({ data: new Uint8Array(w * h * 4), width: w, height: h }, (result: any) => {
        if (!result) reject(new Error('HEIC display failed'))
        else resolve(result.data)
      })
    })
    // Convert RGBA to JPEG via Jimp
    const img = new Jimp({ data: Buffer.from(pixels), width: w, height: h })
    return (await img.getBuffer('image/jpeg')).buffer
  }
  return bytes
}

async function cropGrid(jpegBytes: ArrayBuffer): Promise<ArrayBuffer[]> {
  const img = await Jimp.fromBuffer(Buffer.from(jpegBytes))
  const w = img.width
  const h = img.height
  const cellW = Math.floor(w / 3)
  const cellH = Math.floor(h / 3)
  const crops: ArrayBuffer[] = []

  for (let row = 0; row < 3; row++) {
    for (let col = 0; col < 3; col++) {
      const cropped = img.clone().crop({ x: col * cellW, y: row * cellH, w: cellW, h: cellH })
      const buf = await cropped.getBuffer('image/jpeg')
      crops.push(buf.buffer)
    }
  }
  return crops
}

async function callAnthropicVision(b64: string, apiKey: string): Promise<any[]> {
  const prompt = `You are examining a 3x3 grid of baseball trading cards (9 cards total, arranged in 3 rows of 3). Extract data for each card in reading order (left to right, top to bottom).

For each card return a JSON object with these fields:
- name: player name or card title
- sport: "baseball"
- brand: card manufacturer (Topps, Bowman, Upper Deck, etc.)
- number: card number if visible
- copyright_year: year on card
- team: team name
- card_set: specific set name if visible
- condition: Near Mint, Good, Fair, Poor
- is_player: true if this is a player card, false for checklists/team cards
- features: any special features (rookie, autograph, refractor, etc.)
- value_estimate: estimated market value range
- notes: anything else notable

Return a JSON array of exactly 9 objects, one per card position. Use null for any field you cannot determine.`

  const resp = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model: 'claude-opus-4-6',
      max_tokens: 8096,
      messages: [{ role: 'user', content: [
        { type: 'text', text: prompt },
        { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: b64 } }
      ]}],
    })
  })

  if (!resp.ok) throw new Error(`Anthropic error: ${await resp.text()}`)
  const result = await resp.json<any>()
  const text = result.content[0].text
  const match = text.match(/\[[\s\S]*\]/)
  if (!match) throw new Error('No JSON array in response')
  return JSON.parse(match[0])
}

async function processFile(filename: string, env: Env, jobId: string): Promise<void> {
  const key = `unprocessed/${filename}`
  const obj = await env.STORAGE.get(key)
  if (!obj) throw new Error(`File not found in R2: ${key}`)

  const rawBytes = await obj.arrayBuffer()
  const jpegBytes = await decodeImage(rawBytes, filename)

  // Base64 encode for Anthropic
  const uint8 = new Uint8Array(jpegBytes)
  let b64 = ''
  const chunkSize = 32768
  for (let i = 0; i < uint8.length; i += chunkSize) {
    b64 += String.fromCharCode(...uint8.subarray(i, i + chunkSize))
  }
  b64 = btoa(b64)

  // Call Vision API
  const cards = await callAnthropicVision(b64, env.ANTHROPIC_API_KEY)

  // Crop grid into 9 individual images
  const crops = await cropGrid(jpegBytes)

  // Store cropped images
  const gridId = filename.replace(/\.[^.]+$/, '')
  const croppedFiles: string[] = []
  for (let i = 0; i < crops.length; i++) {
    const cropKey = `pending/images/${gridId}_card_${i}.jpg`
    await env.STORAGE.put(cropKey, crops[i], { httpMetadata: { contentType: 'image/jpeg' } })
    croppedFiles.push(`${gridId}_card_${i}.jpg`)
    if (cards[i]) cards[i].cropped_back_file = `${gridId}_card_${i}.jpg`
  }

  // Move original to pending/bulk-back/
  await env.STORAGE.put(`pending/bulk-back/${filename}`, rawBytes, {
    httpMetadata: { contentType: obj.httpMetadata?.contentType ?? 'image/jpeg' }
  })
  await env.STORAGE.delete(key)

  // Write JSON to pending/json/
  const jsonPayload = {
    source_file: filename,
    grid_id: gridId,
    cards,
    processed_at: new Date().toISOString()
  }
  await env.STORAGE.put(`pending/json/${gridId}.json`, JSON.stringify(jsonPayload), {
    httpMetadata: { contentType: 'application/json' }
  })

  // Log to system_logs
  await env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES ('processed', ?, ?)"
  ).bind(filename, JSON.stringify({ cards_found: cards.length })).run()
}

export default {
  async queue(batch: MessageBatch<PipelineJob>, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const { jobId, filenames } = message.body

      await env.DB.prepare(
        "UPDATE processing_jobs SET status = 'processing', updated_at = datetime('now') WHERE id = ?"
      ).bind(jobId).run()

      let processed = 0
      for (const filename of filenames) {
        try {
          await processFile(filename, env, jobId)
          processed++
          await env.DB.prepare(
            "UPDATE processing_jobs SET processed = ?, updated_at = datetime('now') WHERE id = ?"
          ).bind(processed, jobId).run()
        } catch (err) {
          console.error(`Failed to process ${filename}:`, err)
          await env.DB.prepare(
            "UPDATE processing_jobs SET error = ?, updated_at = datetime('now') WHERE id = ?"
          ).bind(String(err), jobId).run()
        }
      }

      await env.DB.prepare(
        "UPDATE processing_jobs SET status = 'done', updated_at = datetime('now') WHERE id = ?"
      ).bind(jobId).run()

      message.ack()
    }
  }
}
```

**Step 3: Deploy pipeline worker**

```bash
cd workers/pipeline && npm run deploy
```

Expected: `Published trading-cards-pipeline`

**Step 4: Commit**

```bash
git add workers/pipeline/
git commit -m "implement pipeline worker: heic decode, vision api, crop, d1/r2 writes"
```

---

### Task 12: Deploy API Worker and verify all routes

**Step 1: Deploy API Worker**

```bash
cd workers/api && npm run deploy
```

Expected: `Published trading-cards-api` with a URL like `https://trading-cards-api.<your-subdomain>.workers.dev`

**Step 2: Test all critical routes against deployed worker**

```bash
WORKER_URL=https://trading-cards-api.<your-subdomain>.workers.dev

curl $WORKER_URL/health
# Expected: {"status":"ok","db":"ok"}

curl "$WORKER_URL/api/cards?limit=3"
# Expected: {"cards":[...3 cards],"page":1,"limit":3}

curl "$WORKER_URL/api/database-stats"
# Expected: {"total_cards":901,"total_copies":1053}

curl "$WORKER_URL/api/field-options" | python3 -m json.tool | head -10
# Expected: valid JSON with brands, teams, sports, conditions arrays

curl "$WORKER_URL/api/processing-status"
# Expected: {"active":false}

curl "$WORKER_URL/api/raw-scan-count"
# Expected: {"count":0} or current count
```

**Step 3: Add a custom domain for the Worker**

In Cloudflare dashboard: Workers & Pages → trading-cards-api → Settings → Domains & Routes → Add Route:
- Route: `trading-cards-api.harlanswitzer.com/*`
- Zone: `harlanswitzer.com`

Or use wrangler:
```bash
cd workers/api
npx wrangler deploy --route "trading-cards-api.harlanswitzer.com/*"
```

**Step 4: Update API Worker CORS to include Pages URL once known**

In `workers/api/src/index.ts`, add the Worker subdomain URL to cors origins and redeploy.

---

### Task 13: Update React frontend — point to Worker API

**Files:**
- Modify: `app/ui/client/.env.production`

**Step 1: Create/update production env file**

```bash
# app/ui/client/.env.production
REACT_APP_API_BASE=https://trading-cards-api.harlanswitzer.com
```

**Step 2: Verify apiBase.js uses it**

`app/ui/client/src/utils/apiBase.js` already reads `process.env.REACT_APP_API_BASE || ''` — no change needed.

**Step 3: Test build locally**

```bash
cd app/ui/client
REACT_APP_API_BASE=https://trading-cards-api.harlanswitzer.com npm run build
```

Expected: build succeeds, no errors.

**Step 4: Commit**

```bash
git add app/ui/client/.env.production
git commit -m "point react frontend to cloudflare worker api url"
```

---

### Task 14: Deploy React to Cloudflare Pages

**Step 1: Create Pages project via wrangler**

```bash
cd app/ui/client
npx wrangler pages project create trading-cards-frontend \
  --production-branch=main
```

**Step 2: Deploy the current build**

```bash
npx wrangler pages deploy build/ --project-name=trading-cards-frontend
```

Expected: `Deployment complete! URL: https://trading-cards-frontend.pages.dev`

**Step 3: Add custom domain in Cloudflare dashboard**

Pages → trading-cards-frontend → Custom Domains → Add `trading-cards.harlanswitzer.com`

Cloudflare will automatically update the DNS record.

**Step 4: Configure Pages to auto-deploy from git**

In Cloudflare dashboard: Pages → trading-cards-frontend → Settings → Build:
- Build command: `npm run build`
- Build output directory: `build`
- Root directory: `app/ui/client`
- Branch: `main`

Connect to the GitHub repo. From now on every push to `main` auto-deploys.

**Step 5: Verify Pages is serving correctly**

```bash
curl https://trading-cards.harlanswitzer.com
# Expected: HTML with <title>Trading Cards</title>
```

**Step 6: Verify end-to-end in browser**

1. Open https://trading-cards.harlanswitzer.com
2. Should redirect to /dashboard (no ENTER button)
3. Should show card totals loaded from D1 via Worker
4. Upload an image — should appear in R2 `unprocessed/`
5. Click Process — should queue a job, progress bar should appear
6. Wait for processing — cards appear in pending verification
7. Pass a card — should write to D1

---

### Task 15: DNS cutover and VM decommission

**Step 1: Verify everything works on the new stack for at least 24 hours**

Run through the full workflow: upload → process → verify → browse database. Confirm card counts match what was migrated.

**Step 2: Remove cards-origin DNS record**

In Cloudflare dashboard: DNS → delete the `cards-origin` A record (no longer needed).

**Step 3: Stop trading-cards service on VM**

```bash
gcloud compute ssh "harlan@trading-cards" --zone=us-central1-a -- \
  "sudo systemctl stop trading-cards && sudo systemctl disable trading-cards"
```

**Step 4: Final R2 backup of VM data (safety net)**

```bash
cd workers/api
bash ../migrate/sync-images-to-r2.sh
npx wrangler d1 execute trading-cards --command="SELECT COUNT(*) as n FROM cards"
```

Confirm counts still match: 901 cards, 1053 cards_complete.

**Step 5: Delete VM (after 1 week of confirmed stability)**

```bash
gcloud compute instances delete trading-cards --zone=us-central1-a
```

**Step 6: Final commit**

```bash
git add .
git commit -m "complete cloudflare workers migration, decommission vm"
```

---

## Summary of Cloudflare Resources

| Resource | Name | Purpose |
|---|---|---|
| Worker | trading-cards-api | All 45 API routes (Hono) |
| Worker | trading-cards-pipeline | Queue consumer, Vision pipeline |
| D1 Database | trading-cards | Cards + verification + logs |
| R2 Bucket | trading-cards | All images (unprocessed/pending/verified) |
| Queue | pipeline-jobs | Async pipeline jobs |
| Pages | trading-cards-frontend | React UI, auto-deploys from git |

## Route Reference

All existing routes are preserved at the same paths. The React app only needs `REACT_APP_API_BASE` changed to point at the Worker URL.
