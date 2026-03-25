import { Hono } from 'hono'
import { Env } from '../index'

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
  const [cards, copies] = await Promise.all([
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards").first<{ n: number }>(),
    c.env.DB.prepare("SELECT COUNT(*) as n FROM cards_complete").first<{ n: number }>(),
  ])
  return c.json({ total_cards: cards?.n ?? 0, total_copies: copies?.n ?? 0 })
})

misc.get('/system-logs', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 100"
  ).all()
  return c.json(rows.results)
})

misc.get('/recent-activity', async (c) => {
  const rows = await c.env.DB.prepare(
    "SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 20"
  ).all()
  return c.json(rows.results)
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
  const { filename } = await c.req.json<{ filename: string }>()
  if (!filename) return c.json({ error: 'No filename provided' }, 400)

  const obj = await c.env.STORAGE.get(`unprocessed/${filename}`)
  if (!obj) return c.json({ error: 'File not found in storage' }, 404)

  const bytes = await obj.arrayBuffer()
  const uint8 = new Uint8Array(bytes)
  let b64 = ''
  const chunkSize = 32768
  for (let i = 0; i < uint8.length; i += chunkSize) {
    b64 += String.fromCharCode(...uint8.subarray(i, i + chunkSize))
  }
  b64 = btoa(b64)

  const prompt = `I upload photos of baseball cards, usually arranged in grids. You identify each card individually and treat them one by one, not as a group. For each card, you determine what type of card it is (player card, prospect, checklist, stat card, Bowman paper vs Chrome, etc.). You consider the player, career outcome, era, brand, year, condition visible in the photo, and typical market value. You assume my default storage is cards stored in boxes in rows, out of light, protected, for long term value preservation.

For each card, you give a per-card storage recommendation, choosing only from:
    •    no protection
    •    penny sleeve
    •    top loader
    •    special storage (only for genuinely high-value cases)

FORMAT YOUR RESPONSE AS ONE LINE PER CARD:
Card [number]: [player name, year, brand, card type] | Storage: [recommendation] | Reason: [brief explanation] | Price: [estimated market value]

Separate each card with a blank line.

DO NOT include summary guidance, general recommendations, or offers for future analysis.`

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
