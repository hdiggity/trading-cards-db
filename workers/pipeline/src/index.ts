import { Jimp } from 'jimp'

export interface Env {
  DB: D1Database
  STORAGE: R2Bucket
  ANTHROPIC_API_KEY: string
}

interface PipelineJob {
  jobId: string
  filenames: string[]
}

async function decodeToJpeg(bytes: ArrayBuffer, filename: string): Promise<ArrayBuffer> {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.heic') || lower.endsWith('.heif')) {
    const libheif = await import('libheif-js')
    const decoder = new libheif.HeifDecoder()
    const decoded = decoder.decode(new Uint8Array(bytes))
    if (!decoded.length) throw new Error('HEIC decode failed: no images found')
    const image = decoded[0]
    const w = image.get_width()
    const h = image.get_height()
    const pixels = await new Promise<Uint8Array>((resolve, reject) => {
      image.display({ data: new Uint8Array(w * h * 4), width: w, height: h }, (result: any) => {
        if (!result) reject(new Error('HEIC display failed'))
        else resolve(result.data)
      })
    })
    const img = new Jimp({ data: Buffer.from(pixels), width: w, height: h })
    const buf = await img.getBuffer('image/jpeg')
    return buf.buffer as ArrayBuffer
  }
  return bytes
}

// Anthropic limit is 5MB on the base64 string (~3.75MB raw). Resize proportionally if needed.
async function ensureUnderLimit(jpegBytes: ArrayBuffer): Promise<ArrayBuffer> {
  const MAX_RAW = 3.75 * 1024 * 1024
  if (jpegBytes.byteLength <= MAX_RAW) return jpegBytes
  const img = await Jimp.fromBuffer(Buffer.from(jpegBytes))
  const scale = Math.sqrt(MAX_RAW / jpegBytes.byteLength)
  img.resize({ w: Math.floor(img.width * scale), h: Math.floor(img.height * scale) })
  const buf = await img.getBuffer('image/jpeg', { quality: 90 })
  return buf.buffer as ArrayBuffer
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
      crops.push(buf.buffer as ArrayBuffer)
    }
  }
  return crops
}

async function callVision(b64: string, apiKey: string): Promise<any[]> {
  const prompt = `You are examining a 3x3 grid of baseball trading cards (9 cards total, arranged in 3 rows of 3). Extract data for each card in reading order (left to right, top to bottom).

For each card return a JSON object with these exact fields:
- name: player name or card title
- sport: "baseball"
- brand: card manufacturer (Topps, Bowman, Upper Deck, Fleer, Donruss, etc.)
- number: card number if visible
- copyright_year: year on card
- team: team name
- card_set: specific set name if visible
- condition: one of Near Mint, Good, Fair, Poor
- is_player: true if this is a player card, false for checklists or team cards
- features: any special features (rookie, autograph, refractor, chrome, etc.)
- value_estimate: estimated market value range in dollars
- notes: anything else notable

Return a JSON array of exactly 9 objects. Use null for any field you cannot determine.`

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
      ]}]
    })
  })

  if (!resp.ok) throw new Error(`Anthropic error ${resp.status}: ${await resp.text()}`)
  const result = await resp.json<any>()
  const text = result.content[0].text
  const match = text.match(/\[[\s\S]*\]/)
  if (!match) throw new Error(`No JSON array in Vision response: ${text.slice(0, 200)}`)
  return JSON.parse(match[0])
}

function toBase64(bytes: ArrayBuffer): string {
  const uint8 = new Uint8Array(bytes)
  let b64 = ''
  const chunkSize = 32768
  for (let i = 0; i < uint8.length; i += chunkSize) {
    b64 += String.fromCharCode(...uint8.subarray(i, i + chunkSize))
  }
  return btoa(b64)
}

async function processFile(filename: string, env: Env): Promise<void> {
  const key = `unprocessed/${filename}`
  const obj = await env.STORAGE.get(key)
  if (!obj) throw new Error(`File not found in R2: ${key}`)

  const rawBytes = await obj.arrayBuffer()
  const jpegBytes = await decodeToJpeg(rawBytes, filename)
  const sizedBytes = await ensureUnderLimit(jpegBytes)
  const b64 = toBase64(sizedBytes)

  const cards = await callVision(b64, env.ANTHROPIC_API_KEY)
  const crops = await cropGrid(jpegBytes)

  const gridId = filename.replace(/\.[^.]+$/, '')

  for (let i = 0; i < Math.min(crops.length, cards.length); i++) {
    const cropKey = `pending/images/${gridId}_card_${i}.jpg`
    await env.STORAGE.put(cropKey, crops[i], { httpMetadata: { contentType: 'image/jpeg' } })
    if (cards[i]) cards[i].cropped_back_file = `${gridId}_card_${i}.jpg`
    if (cards[i]) cards[i].source_file = filename
  }

  await env.STORAGE.put(`pending/bulk-back/${filename}`, rawBytes, {
    httpMetadata: { contentType: obj.httpMetadata?.contentType ?? 'image/jpeg' }
  })
  await env.STORAGE.delete(key)

  const jsonPayload = { source_file: filename, grid_id: gridId, cards, processed_at: new Date().toISOString() }
  await env.STORAGE.put(`pending/json/${gridId}.json`, JSON.stringify(jsonPayload), {
    httpMetadata: { contentType: 'application/json' }
  })

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
          await processFile(filename, env)
          processed++
          await env.DB.prepare(
            "UPDATE processing_jobs SET processed = ?, updated_at = datetime('now') WHERE id = ?"
          ).bind(processed, jobId).run()
        } catch (err) {
          console.error(`Failed ${filename}:`, err)
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
