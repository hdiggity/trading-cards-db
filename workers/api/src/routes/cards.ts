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

  const [rows, countRow] = await Promise.all([
    c.env.DB.prepare(query).bind(...params).all(),
    c.env.DB.prepare('SELECT COUNT(*) as n FROM cards WHERE 1=1').all(),
  ])

  return c.json({ cards: rows.results, page: pageNum, limit: limitNum, total: (rows.results as any[]).length })
})

cards.get('/stats', async (c) => {
  const [total, totalComplete] = await Promise.all([
    c.env.DB.prepare('SELECT COUNT(*) as n FROM cards').first<{ n: number }>(),
    c.env.DB.prepare('SELECT COUNT(*) as n FROM cards_complete').first<{ n: number }>(),
  ])
  return c.json({ total_cards: total?.n ?? 0, total_copies: totalComplete?.n ?? 0 })
})

cards.get('/:id', async (c) => {
  const { id } = c.req.param()
  const card = await c.env.DB.prepare('SELECT * FROM cards WHERE id = ?').bind(id).first()
  if (!card) return c.json({ error: 'Not found' }, 404)
  return c.json(card)
})

cards.put('/:id', async (c) => {
  const { id } = c.req.param()
  const data = await c.req.json<any>()
  const fields = ['name', 'sport', 'brand', 'number', 'copyright_year', 'team', 'card_set', 'condition', 'is_player', 'features', 'value_estimate', 'notes', 'quantity', 'canonical_name']
  const updates = fields.filter(f => f in data).map(f => `${f} = ?`).join(', ')
  const values = fields.filter(f => f in data).map(f => data[f])
  if (!updates) return c.json({ error: 'No fields to update' }, 400)
  await c.env.DB.prepare(`UPDATE cards SET ${updates}, last_updated = datetime('now') WHERE id = ?`)
    .bind(...values, id).run()
  return c.json({ success: true })
})

cards.delete('/:id', async (c) => {
  const { id } = c.req.param()
  await c.env.DB.prepare('DELETE FROM cards WHERE id = ?').bind(id).run()
  return c.json({ success: true })
})

export default cards
