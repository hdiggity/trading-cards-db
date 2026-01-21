-- Migration: Update database triggers to include canonical_name
-- Date: 2026-01-01
-- Description: Updates sync_to_cards_on_insert and sync_to_cards_on_update triggers
--              to include canonical_name field in sync operations

-- Drop existing triggers
DROP TRIGGER IF EXISTS sync_to_cards_on_insert;
DROP TRIGGER IF EXISTS sync_to_cards_on_update;

-- Recreate INSERT trigger with canonical_name
CREATE TRIGGER sync_to_cards_on_insert
AFTER INSERT ON cards_complete
BEGIN
    INSERT INTO cards (
        id, name, canonical_name, sport, brand, number, copyright_year, team,
        card_set, condition, is_player, features, value_estimate,
        notes, quantity, date_added, last_updated
    )
    SELECT
        NEW.card_id,
        NEW.name,
        NEW.canonical_name,
        NEW.sport,
        NEW.brand,
        NEW.number,
        NEW.copyright_year,
        NEW.team,
        NEW.card_set,
        NEW.condition,
        NEW.is_player,
        NEW.features,
        NEW.value_estimate,
        NEW.notes,
        1,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    WHERE NOT EXISTS (SELECT 1 FROM cards WHERE id = NEW.card_id);

    UPDATE cards SET
        name = NEW.name,
        canonical_name = NEW.canonical_name,
        sport = NEW.sport,
        brand = NEW.brand,
        number = NEW.number,
        copyright_year = NEW.copyright_year,
        team = NEW.team,
        card_set = NEW.card_set,
        condition = NEW.condition,
        is_player = NEW.is_player,
        features = NEW.features,
        value_estimate = NEW.value_estimate,
        notes = NEW.notes,
        quantity = (SELECT COUNT(*) FROM cards_complete WHERE card_id = NEW.card_id),
        last_updated = CURRENT_TIMESTAMP
    WHERE id = NEW.card_id;
END;

-- Recreate UPDATE trigger with canonical_name
CREATE TRIGGER sync_to_cards_on_update
AFTER UPDATE ON cards_complete
BEGIN
    UPDATE cards SET
        name = NEW.name,
        canonical_name = NEW.canonical_name,
        sport = NEW.sport,
        brand = NEW.brand,
        number = NEW.number,
        copyright_year = NEW.copyright_year,
        team = NEW.team,
        card_set = NEW.card_set,
        condition = NEW.condition,
        is_player = NEW.is_player,
        features = NEW.features,
        value_estimate = NEW.value_estimate,
        notes = NEW.notes,
        last_updated = CURRENT_TIMESTAMP
    WHERE id = NEW.card_id;
END;
