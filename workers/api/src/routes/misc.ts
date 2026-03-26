import { Hono } from 'hono'
import { Env } from '../index'
import { runBackup } from '../backup'

const misc = new Hono<{ Bindings: Env }>()

misc.get('/field-options', async (c) => {
  const [brands, teams, sports, conditions] = await Promise.all([
    c.env.DB.prepare("SELECT DISTINCT brand FROM cards WHERE brand IS NOT NULL ORDER BY brand").all(),
    c.env.DB.prepare("SELECT DISTINCT team FROM cards WHERE team IS NOT NULL ORDER BY team").all(),
    c.env.DB.prepare("SELECT DISTINCT sport FROM cards WHERE sport IS NOT NULL ORDER BY sport").all(),
    c.env.DB.prepare("SELECT DISTINCT condition FROM cards WHERE condition IS NOT NULL ORDER BY condition").all(),
  ])
  return c.json({
    brands: (brands.results as any[]).map(r => r.brand),
    teams: (teams.results as any[]).map(r => r.team),
    sports: (sports.results as any[]).map(r => r.sport),
    conditions: (conditions.results as any[]).map(r => r.condition),
  })
})

misc.get('/database-stats', async (c) => {
  const [totalQty, totalCards, copies, years, brands, sports, totalValue] = await Promise.all([
    c.env.DB.prepare("SELECT COALESCE(SUM(quantity), 0) as n FROM cards").first<{ n: number }>(),
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards").first<{ n: number }>(),
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards_complete").first<{ n: number }>(),
    c.env.DB.prepare("SELECT copyright_year as year, SUM(quantity) as count FROM cards WHERE copyright_year IS NOT NULL GROUP BY copyright_year ORDER BY count DESC LIMIT 5").all(),
    c.env.DB.prepare("SELECT brand, SUM(quantity) as count FROM cards WHERE brand IS NOT NULL GROUP BY brand ORDER BY count DESC LIMIT 5").all(),
    c.env.DB.prepare("SELECT sport, SUM(quantity) as count FROM cards WHERE sport IS NOT NULL GROUP BY sport ORDER BY count DESC LIMIT 5").all(),
    c.env.DB.prepare("SELECT ROUND(SUM(CAST(REPLACE(value_estimate, '$', '') AS REAL) * quantity), 2) as total FROM cards WHERE value_estimate IS NOT NULL AND value_estimate != ''").first<{ total: number }>(),
  ])
  return c.json({
    total_cards: totalCards?.n ?? 0,
    total_copies: copies?.n ?? 0,
    total_quantity: totalQty?.n ?? 0,
    unique_years: (years.results as any[]).length,
    years_summary: years.results,
    unique_brands: (brands.results as any[]).length,
    brands_summary: brands.results,
    unique_sports: (sports.results as any[]).length,
    sports_summary: sports.results,
    total_value: totalValue?.total ?? 0,
  })
})

misc.get('/system-logs', async (c) => {
  const { limit = '200' } = c.req.query()
  const rows = await c.env.DB.prepare(
    `SELECT id, event_type as level, details as message, filename, created_at as timestamp FROM system_logs ORDER BY created_at DESC LIMIT ${parseInt(limit)}`
  ).all()
  return c.json({ logs: rows.results, totals: null })
})

misc.get('/recent-activity', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT id, event_type as action, filename, details, created_at as timestamp FROM system_logs ORDER BY created_at DESC LIMIT 20"
  ).all()
  return c.json({ activity: rows.results })
})

misc.get('/verification-sessions', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT DISTINCT session_id, MIN(created_at) as started_at, COUNT(*) as actions FROM undo_transactions GROUP BY session_id ORDER BY started_at DESC LIMIT 50"
  ).all()
  return c.json(rows.results)
})

misc.get('/verification-history/:id', async (c) => {
  const { id } = c.req.param()
  const rows = await c.env.DB.prepare(
    "SELECT * FROM undo_transactions WHERE card_id = ? ORDER BY created_at DESC"
  ).bind(id).all()
  return c.json(rows.results)
})

misc.post('/undo/:id', async (c) => {
  const { id } = c.req.param()
  const tx = await c.env.DB.prepare(
    "SELECT * FROM undo_transactions WHERE id = ?"
  ).bind(id).first<any>()
  if (!tx) return c.json({ error: 'Transaction not found' }, 404)

  await c.env.DB.prepare("DELETE FROM cards_complete WHERE card_id = ?").bind(tx.card_id).run()
  await c.env.DB.prepare("UPDATE cards SET quantity = MAX(0, quantity - 1), last_updated = datetime('now') WHERE id = ?")
    .bind(tx.card_id).run()
  await c.env.DB.prepare("DELETE FROM cards WHERE id = ? AND quantity = 0").bind(tx.card_id).run()
  await c.env.DB.prepare("DELETE FROM undo_transactions WHERE id = ?").bind(id).run()

  await c.env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES ('undo', ?, ?)"
  ).bind(String(tx.card_id), `Undone card #${tx.card_id}`).run()

  return c.json({ success: true })
})

misc.get('/search-cards', async (c) => {
  const { q } = c.req.query()
  if (!q) return c.json([])
  const rows = await c.env.DB.prepare(
    "SELECT * FROM cards WHERE name LIKE ? OR brand LIKE ? OR team LIKE ? ORDER BY name LIMIT 20"
  ).bind(`%${q}%`, `%${q}%`, `%${q}%`).all()
  return c.json(rows.results)
})

misc.post('/storage-analysis', async (c) => {
  const body = await c.req.json<{ base64?: string; mediaType?: string; filename?: string }>()

  let b64: string
  let mediaType: string

  if (body.base64) {
    b64 = body.base64
    mediaType = body.mediaType ?? 'image/jpeg'
  } else if (body.filename) {
    const obj = await c.env.STORAGE.get(`unprocessed/${body.filename}`)
    if (!obj) return c.json({ error: 'File not found in storage' }, 404)
    const bytes = await obj.arrayBuffer()
    if (bytes.byteLength > 4.9 * 1024 * 1024) {
      return c.json({ error: 'Image too large (>5MB). Please resize before analyzing.' }, 400)
    }
    const uint8 = new Uint8Array(bytes)
    let s = ''
    for (let i = 0; i < uint8.length; i += 32768) s += String.fromCharCode(...uint8.subarray(i, i + 32768))
    b64 = btoa(s)
    const lower = body.filename.toLowerCase()
    mediaType = lower.endsWith('.png') ? 'image/png' : 'image/jpeg'
  } else {
    return c.json({ error: 'Provide base64 or filename' }, 400)
  }

  const prompt = `You are analyzing trading card photos. Cards may be arranged in grids or shown individually. Examine each card carefully and treat them one at a time.

For each card, read the text directly on the card to extract:
- Player name (REQUIRED — printed on the card front or back. On backs, the name is at the top above the stats. On fronts, it is on the nameplate. Read it carefully character by character.)
- Year (copyright year or set year, found on the card back near the copyright symbol or card number)
- Brand (Topps, Donruss, Fleer, Bowman, Upper Deck, Leaf, Score, O-Pee-Chee, etc.)
- Card number (the # printed on the card, e.g. #137)
- Card type (base, rookie, prospect, highlight, checklist, error, chrome, refractor, etc.)

CRITICAL: Every card has a player name or subject printed on it. You MUST identify it. Look at:
1. The top of the card back for the player name in large/bold text
2. The stats table header
3. The biographical info section
4. The front nameplate
If text is hard to read, zoom in mentally and decode letter by letter. Never output "unnamed" or "unknown player".

Assess storage based on: player significance, career outcome, card rarity, condition, era, and typical market value.

Storage options (pick one per card):
- no protection (common junk wax era commons, bulk filler)
- penny sleeve (minor names, some collectible value)
- top loader (notable players, rookies, better condition cards worth $1+)
- special storage (genuinely high-value cards only, $20+)

FORMAT — one line per card, pipe-separated:
Card [number]: [player name], [year] [brand] #[card number], [card type] | Storage: [recommendation] | Reason: [1 sentence] | Price: [estimated market value]

DO NOT include summaries, group recommendations, or offers for further analysis.`

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
        { type: 'image', source: { type: 'base64', media_type: mediaType, data: b64 } }
      ]}]
    })
  })

  if (!resp.ok) {
    const err = await resp.text()
    return c.json({ error: 'Anthropic API error', details: err }, 500)
  }

  const result = await resp.json<any>()
  const recommendations = result.content[0].text
  const filename = body.filename ?? null
  const cardCount = (recommendations.match(/^Card \d+:/gm) || []).length
  await c.env.DB.prepare(
    "INSERT INTO storage_recommendations (filename, recommendations) VALUES (?, ?)"
  ).bind(filename, recommendations).run()
  // Log the analysis
  await c.env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES (?, ?, ?)"
  ).bind('storage_analysis', filename, `Generated storage recommendations for ${cardCount} card(s)`).run()
  return c.json({ recommendations })
})

misc.post('/backup-now', async (c) => {
  const result = await runBackup(c.env)
  return c.json({ success: true, ...result })
})

misc.get('/backups', async (c) => {
  const list = await c.env.STORAGE.list({ prefix: 'backups/' })
  // Collect unique date prefixes from manifest files
  const dates: Record<string, any> = {}
  for (const obj of list.objects) {
    if (!obj.key.endsWith('manifest.json')) continue
    const parts = obj.key.split('/')
    const date = parts[1]
    dates[date] = { date, size: obj.size, uploaded: obj.uploaded }
  }
  return c.json(Object.values(dates).sort((a: any, b: any) => b.date.localeCompare(a.date)))
})

misc.get('/storage-recommendations', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT id, filename, recommendations, created_at FROM storage_recommendations ORDER BY created_at DESC LIMIT 50"
  ).all()
  return c.json(rows.results)
})

misc.post('/card-suggestions', async (c) => {
  const { name } = await c.req.json<{ name: string }>()
  if (!name) return c.json([])
  const rows = await c.env.DB.prepare(
    "SELECT DISTINCT name, brand, team FROM cards WHERE name LIKE ? LIMIT 10"
  ).bind(`%${name}%`).all()
  return c.json(rows.results)
})

misc.post('/field-autocomplete', async (c) => {
  const { field, query } = await c.req.json<{ field: string; query: string }>()
  const allowed = ['name', 'brand', 'team', 'card_set', 'canonical_name']
  if (!allowed.includes(field)) return c.json([])
  const rows = await c.env.DB.prepare(
    `SELECT DISTINCT ${field} as value FROM cards WHERE ${field} LIKE ? AND ${field} IS NOT NULL ORDER BY ${field} LIMIT 10`
  ).bind(`%${query}%`).all()
  return c.json((rows.results as any[]).map(r => r.value))
})

export default misc
