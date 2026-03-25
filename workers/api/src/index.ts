import { Hono } from 'hono'
import { cors } from 'hono/cors'
import health from './routes/health'
import cards from './routes/cards'
import verification from './routes/verification'
import images from './routes/images'
import pipeline from './routes/pipeline'
import misc from './routes/misc'

export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  PIPELINE_QUEUE: Queue
  ANTHROPIC_API_KEY: string
}

const app = new Hono<{ Bindings: Env }>()

app.use('*', cors({
  origin: ['https://trading-cards.harlanswitzer.com', 'https://trading-cards-frontend.pages.dev', 'http://localhost:3000'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization'],
}))

app.route('/health', health)
app.route('/api/cards', cards)
app.route('/api', verification)
app.route('/api', images)
app.route('/api', pipeline)
app.route('/api', misc)

export default app
