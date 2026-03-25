import { Hono } from 'hono'
import { Env } from '../index'

const pipeline = new Hono<{ Bindings: Env }>()

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

  await c.env.DB.prepare(
    "INSERT INTO system_logs (event_type, filename, details) VALUES ('process_start', 'batch', ?)"
  ).bind(JSON.stringify({ job_id: jobId, total: toProcess.length })).run()

  return c.json({ success: true, jobId, total: toProcess.length })
})

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
    remaining: job.total - job.processed,
    error: job.error ?? null,
    jobId: job.id,
    startedAt: job.created_at
  })
})

pipeline.post('/cancel-processing', async (c) => {
  await c.env.DB.prepare(
    "UPDATE processing_jobs SET status = 'cancelled', updated_at = datetime('now') WHERE status IN ('queued', 'processing')"
  ).run()
  return c.json({ success: true })
})

export default pipeline
