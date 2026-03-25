import { Hono } from 'hono'
import { Env } from '../index'

const images = new Hono<{ Bindings: Env }>()

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

images.get('/bulk-back-image/:filename', async (c) => {
  const { filename } = c.req.param()
  const obj = await c.env.STORAGE.get(`pending/bulk-back/${filename}`)
    ?? await c.env.STORAGE.get(`unprocessed/${filename}`)
  if (!obj) return c.json({ error: 'Not found' }, 404)
  return new Response(obj.body, {
    headers: { 'Content-Type': obj.httpMetadata?.contentType ?? 'image/jpeg', 'Cache-Control': 'public, max-age=86400' }
  })
})

images.get('/cropped-back-image/:filename', async (c) => {
  const { filename } = c.req.param()
  const obj = await c.env.STORAGE.get(`pending/images/${filename}`)
    ?? await c.env.STORAGE.get(`verified/cropped/${filename}`)
  if (!obj) return c.json({ error: 'Not found' }, 404)
  return new Response(obj.body, {
    headers: { 'Content-Type': obj.httpMetadata?.contentType ?? 'image/jpeg', 'Cache-Control': 'public, max-age=86400' }
  })
})

images.get('/card-cropped-back/:id', async (c) => {
  const { id } = c.req.param()
  const row = await c.env.DB.prepare('SELECT cropped_back_file FROM cards_complete WHERE id = ?').bind(id).first<{ cropped_back_file: string }>()
  if (!row?.cropped_back_file) return c.json({ error: 'Not found' }, 404)
  const obj = await c.env.STORAGE.get(`verified/cropped/${row.cropped_back_file}`)
    ?? await c.env.STORAGE.get(`pending/images/${row.cropped_back_file}`)
  if (!obj) return c.json({ error: 'Image not found in storage' }, 404)
  return new Response(obj.body, {
    headers: { 'Content-Type': 'image/jpeg', 'Cache-Control': 'public, max-age=86400' }
  })
})

images.get('/raw-scan-count', async (c) => {
  const list = await c.env.STORAGE.list({ prefix: 'unprocessed/' })
  return c.json({ count: list.objects.length })
})

images.get('/raw-scans', async (c) => {
  const list = await c.env.STORAGE.list({ prefix: 'unprocessed/' })
  return c.json(list.objects.map(o => ({ filename: o.key.replace('unprocessed/', ''), size: o.size, uploaded: o.uploaded })))
})

export default images
