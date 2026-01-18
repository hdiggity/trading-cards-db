-- Migration: Add canonical_name column for player name normalization
-- Date: 2026-01-01
-- Description: Adds canonical_name field to both cards and cards_complete tables
--              to support matching name variations (nicknames, middle names, suffixes)

-- Add canonical_name column to cards table
ALTER TABLE cards ADD COLUMN canonical_name VARCHAR;

-- Add canonical_name column to cards_complete table
ALTER TABLE cards_complete ADD COLUMN canonical_name VARCHAR;

-- Create index for efficient canonical name lookups
CREATE INDEX idx_cards_canonical_name ON cards(canonical_name);
CREATE INDEX idx_cards_complete_canonical_name ON cards_complete(canonical_name);

-- Create composite index for duplicate detection query
-- (canonical_name, brand, number, copyright_year)
CREATE INDEX idx_cards_duplicate_detection ON cards(
    canonical_name, brand, number, copyright_year
);
