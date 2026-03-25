#!/usr/bin/env bash
# Export SQLite from VM and import to D1.
# Run from repo root: ./workers/migrate/export-and-import.sh
set -euo pipefail

mkdir -p workers/migrate/data

echo "==> exporting from VM..."
gcloud compute ssh "harlan@trading-cards" --zone=us-central1-a -- \
  "python3 -c \"
import sqlite3, json
conn = sqlite3.connect('/opt/trading_cards_db/cards/verified/trading_cards.db')
conn.row_factory = sqlite3.Row

for table in ['cards', 'cards_complete']:
    rows = [dict(r) for r in conn.execute(f'SELECT * FROM {table}')]
    print(f'{table}: {len(rows)} rows', flush=True)
    open(f'/tmp/{table}.json', 'w').write(json.dumps(rows))
\"" 2>&1 | grep -v 'Ignoring unknown'

gcloud compute scp "harlan@trading-cards:/tmp/cards.json" workers/migrate/data/ --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'
gcloud compute scp "harlan@trading-cards:/tmp/cards_complete.json" workers/migrate/data/ --zone=us-central1-a 2>&1 | grep -v 'Ignoring unknown'

echo "==> generating SQL..."
node -e "
const fs = require('fs')
function escStr(v) {
  if (v === null || v === undefined) return 'NULL'
  return \"'\" + String(v).replace(/'/g, \"''\") + \"'\"
}
function rowToInsert(table, row) {
  const keys = Object.keys(row).join(', ')
  const vals = Object.values(row).map(escStr).join(', ')
  return \`INSERT OR IGNORE INTO \${table} (\${keys}) VALUES (\${vals});\`
}
const cards = JSON.parse(fs.readFileSync('workers/migrate/data/cards.json'))
const cc = JSON.parse(fs.readFileSync('workers/migrate/data/cards_complete.json'))
fs.writeFileSync('workers/migrate/data/cards.sql', cards.map(r => rowToInsert('cards', r)).join('\n'))
fs.writeFileSync('workers/migrate/data/cards_complete.sql', cc.map(r => rowToInsert('cards_complete', r)).join('\n'))
console.log('SQL written: ' + cards.length + ' cards, ' + cc.length + ' cards_complete')
"

echo "==> applying schema..."
cd workers/api
npx wrangler d1 execute trading-cards --remote --file=../schema.sql

echo "==> importing cards..."
npx wrangler d1 execute trading-cards --remote --file=../migrate/data/cards.sql

echo "==> importing cards_complete..."
npx wrangler d1 execute trading-cards --remote --file=../migrate/data/cards_complete.sql

echo "==> verifying..."
npx wrangler d1 execute trading-cards --remote --command="SELECT COUNT(*) as cards FROM cards"
npx wrangler d1 execute trading-cards --remote --command="SELECT COUNT(*) as copies FROM cards_complete"

echo "==> done"
