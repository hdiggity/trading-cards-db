CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  sport TEXT DEFAULT 'baseball',
  brand TEXT,
  number TEXT,
  copyright_year TEXT,
  team TEXT,
  card_set TEXT,
  condition TEXT,
  is_player INTEGER DEFAULT 1,
  features TEXT,
  value_estimate TEXT,
  notes TEXT,
  quantity INTEGER DEFAULT 1,
  date_added TEXT DEFAULT (datetime('now')),
  last_updated TEXT,
  canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS cards_complete (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  sport TEXT,
  brand TEXT,
  number TEXT,
  copyright_year TEXT,
  team TEXT,
  card_set TEXT,
  condition TEXT,
  is_player INTEGER,
  features TEXT,
  value_estimate TEXT,
  notes TEXT,
  quantity INTEGER,
  last_updated TEXT,
  source_file TEXT,
  grid_position TEXT,
  original_filename TEXT,
  verification_date TEXT DEFAULT (datetime('now')),
  verified_by TEXT,
  cropped_back_file TEXT,
  canonical_name TEXT
);

CREATE TABLE IF NOT EXISTS undo_transactions (
  id INTEGER PRIMARY KEY,
  session_id TEXT,
  card_id INTEGER,
  action TEXT,
  before_state TEXT,
  after_state TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_logs (
  id INTEGER PRIMARY KEY,
  event_type TEXT,
  filename TEXT,
  details TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_jobs (
  id TEXT PRIMARY KEY,
  status TEXT DEFAULT 'queued',
  total INTEGER DEFAULT 0,
  processed INTEGER DEFAULT 0,
  error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_brand ON cards(brand);
CREATE INDEX IF NOT EXISTS idx_cards_team ON cards(team);
CREATE INDEX IF NOT EXISTS idx_cards_complete_card_id ON cards_complete(card_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status);
