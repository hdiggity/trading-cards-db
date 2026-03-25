import { Hono } from 'hono'
import { Env } from '../index'

const verification = new Hono<{ Bindings: Env }>()

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

verification.post('/pass-card/:id/:cardIndex', async (c) => {
  const { id, cardIndex } = c.req.param()
  const { modifiedData } = await c.req.json<{ modifiedData: any }>()
  const idx = parseInt(cardIndex)

  const jsonKey = `pending/json/${id}.json`
  const raw = await c.env.STORAGE.get(jsonKey)
  if (!raw) return c.json({ error: 'Pending card not found' }, 404)
  const pendingData = await raw.json<any>()
  const cardList = Array.isArray(pendingData.cards) ? pendingData.cards : [pendingData]
  const card = { ...cardList[idx], ...modifiedData }

  // Auto-set is_player based on team/features
  const teamMultiple = (card.team ?? '').toLowerCase().includes('multiple')
  const isChecklist = (card.features ?? '').toLowerCase().includes('checklist') || (card.name ?? '').toLowerCase().includes('checklist')
  if (teamMultiple || isChecklist) card.is_player = 0

  const existing = await c.env.DB.prepare(
    'SELECT id, quantity FROM cards WHERE name = ? AND (brand = ? OR (brand IS NULL AND ? IS NULL)) AND (number = ? OR (number IS NULL AND ? IS NULL))'
  ).bind(card.name, card.brand ?? null, card.brand ?? null, card.number ?? null, card.number ?? null).first<{ id: number; quantity: number }>()

  let cardId: number
  if (existing) {
    await c.env.DB.prepare("UPDATE cards SET quantity = quantity + 1, last_updated = datetime('now') WHERE id = ?")
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

  await c.env.DB.prepare(
    `INSERT INTO cards_complete (card_id, name, sport, brand, number, copyright_year, team, card_set, condition, is_player, features, value_estimate, notes, source_file, grid_position, original_filename, cropped_back_file, canonical_name)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  ).bind(
    cardId, card.name, card.sport ?? 'baseball', card.brand ?? null, card.number ?? null,
    card.copyright_year ?? null, card.team ?? null, card.card_set ?? null,
    card.condition ?? null, card.is_player ?? 1, card.features ?? null,
    card.value_estimate ?? null, card.notes ?? null,
    card.source_file ?? id, String(idx), card.original_filename ?? null,
    card.cropped_back_file ?? null, card.canonical_name ?? null
  ).run()

  // Record undo transaction
  await c.env.DB.prepare(
    "INSERT INTO undo_transactions (session_id, card_id, action, before_state, after_state) VALUES (?, ?, 'pass', ?, ?)"
  ).bind(id, cardId, JSON.stringify({ card_id: cardId }), JSON.stringify(card)).run()

  // Mark card as resolved in pending JSON
  cardList[idx] = { ...card, resolved: true }
  const allResolved = cardList.every((c: any) => c?.resolved)
  if (allResolved) {
    await c.env.STORAGE.delete(jsonKey)
  } else {
    await c.env.STORAGE.put(jsonKey, JSON.stringify({ ...pendingData, cards: cardList }))
  }

  await c.env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES ('pass', ?, ?)"
  ).bind(id, JSON.stringify({ card_index: idx, card_id: cardId })).run()

  return c.json({ success: true, cardId })
})

verification.post('/fail-card/:id/:cardIndex', async (c) => {
  const { id, cardIndex } = c.req.param()
  const idx = parseInt(cardIndex)
  const jsonKey = `pending/json/${id}.json`
  const raw = await c.env.STORAGE.get(jsonKey)
  if (!raw) return c.json({ error: 'Pending card not found' }, 404)
  const pendingData = await raw.json<any>()
  const cardList = Array.isArray(pendingData.cards) ? pendingData.cards : [pendingData]
  cardList[idx] = { ...cardList[idx], resolved: true, failed: true }
  const allResolved = cardList.every((c: any) => c?.resolved)
  if (allResolved) {
    await c.env.STORAGE.delete(jsonKey)
  } else {
    await c.env.STORAGE.put(jsonKey, JSON.stringify({ ...pendingData, cards: cardList }))
  }
  return c.json({ success: true })
})

verification.post('/save-progress/:id', async (c) => {
  const { id } = c.req.param()
  const { cardIndex, data } = await c.req.json<any>()
  const jsonKey = `pending/json/${id}.json`
  const raw = await c.env.STORAGE.get(jsonKey)
  if (!raw) return c.json({ error: 'Not found' }, 404)
  const pendingData = await raw.json<any>()
  const cardList = Array.isArray(pendingData.cards) ? pendingData.cards : [pendingData]
  cardList[cardIndex] = { ...cardList[cardIndex], ...data }
  await c.env.STORAGE.put(jsonKey, JSON.stringify({ ...pendingData, cards: cardList }))
  return c.json({ success: true })
})

export default verification
