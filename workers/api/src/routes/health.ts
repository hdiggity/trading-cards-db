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
