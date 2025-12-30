"""Backfill award features for all existing cards in the database.

Checks each card for:
- Hall of Fame status
- Rookie card (rookie year + 1)
- Season MVP (award year + 1)
- Cy Young season (award year + 1)
- Triple Crown season (award year + 1)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import func

from app.database import get_session
from app.grid_processor import (has_award_in_year, is_hall_of_famer,
                                is_rookie_card)
from app.models import Card, CardComplete


def add_feature(current_features, new_feature):
    """Add a feature to the features string if not already present."""
    if not current_features or current_features == 'none':
        return new_feature
    
    features_list = [f.strip() for f in current_features.split(',')]
    if new_feature not in features_list:
        features_list.append(new_feature)
    
    return ','.join(features_list)

def remove_feature(current_features, feature_to_remove):
    """Remove a feature from the features string."""
    if not current_features or current_features == 'none':
        return 'none'
    
    features_list = [f.strip() for f in current_features.split(',') if f.strip() != feature_to_remove]
    return ','.join(features_list) if features_list else 'none'

def backfill_awards():
    """Backfill award features for all cards."""
    
    stats = {
        'total_cards': 0,
        'baseball_cards': 0,
        'hall_of_fame_added': 0,
        'hall_of_fame_removed': 0,
        'rookie_added': 0,
        'rookie_removed': 0,
        'mvp_added': 0,
        'mvp_removed': 0,
        'cy_young_added': 0,
        'cy_young_removed': 0,
        'triple_crown_added': 0,
        'triple_crown_removed': 0,
        'cards_updated': 0
    }
    
    with get_session() as session:
        # Get all cards
        cards = session.query(Card).all()
        stats['total_cards'] = len(cards)
        
        print(f"Processing {stats['total_cards']} cards...")
        
        for card in cards:
            # Only process baseball player cards
            if card.sport != 'baseball' or not card.is_player:
                continue
            
            stats['baseball_cards'] += 1
            original_features = card.features or 'none'
            updated_features = original_features
            card_modified = False
            
            # Check Hall of Fame
            if is_hall_of_famer(card.name):
                if 'hall of fame' not in updated_features:
                    updated_features = add_feature(updated_features, 'hall of fame')
                    stats['hall_of_fame_added'] += 1
                    card_modified = True
            else:
                if 'hall of fame' in updated_features:
                    updated_features = remove_feature(updated_features, 'hall of fame')
                    stats['hall_of_fame_removed'] += 1
                    card_modified = True
            
            # Check Rookie
            if is_rookie_card(card.name, card.copyright_year):
                if 'rookie' not in updated_features:
                    updated_features = add_feature(updated_features, 'rookie')
                    stats['rookie_added'] += 1
                    card_modified = True
            else:
                if 'rookie' in updated_features:
                    updated_features = remove_feature(updated_features, 'rookie')
                    stats['rookie_removed'] += 1
                    card_modified = True
            
            # Check Season MVP
            if has_award_in_year(card.name, card.copyright_year, 'mvp'):
                if 'season mvp' not in updated_features:
                    updated_features = add_feature(updated_features, 'season mvp')
                    stats['mvp_added'] += 1
                    card_modified = True
            else:
                if 'season mvp' in updated_features:
                    updated_features = remove_feature(updated_features, 'season mvp')
                    stats['mvp_removed'] += 1
                    card_modified = True
            
            # Check Cy Young season
            if has_award_in_year(card.name, card.copyright_year, 'cy_young'):
                if 'cy young season' not in updated_features:
                    updated_features = add_feature(updated_features, 'cy young season')
                    stats['cy_young_added'] += 1
                    card_modified = True
            else:
                if 'cy young season' in updated_features:
                    updated_features = remove_feature(updated_features, 'cy young season')
                    stats['cy_young_removed'] += 1
                    card_modified = True
            
            # Check Triple Crown season
            if has_award_in_year(card.name, card.copyright_year, 'triple_crown'):
                if 'triple crown season' not in updated_features:
                    updated_features = add_feature(updated_features, 'triple crown season')
                    stats['triple_crown_added'] += 1
                    card_modified = True
            else:
                if 'triple crown season' in updated_features:
                    updated_features = remove_feature(updated_features, 'triple crown season')
                    stats['triple_crown_removed'] += 1
                    card_modified = True
            
            # Update card if modified
            if card_modified:
                card.features = updated_features
                
                # Update all CardComplete records for this card
                session.query(CardComplete).filter(
                    CardComplete.card_id == card.id
                ).update({
                    'features': updated_features,
                    'last_updated': func.now()
                }, synchronize_session=False)
                
                stats['cards_updated'] += 1
                
                # Print updates for visibility
                if stats['cards_updated'] <= 20 or stats['cards_updated'] % 10 == 0:
                    print(f"  Updated: {card.name} ({card.copyright_year}) - {updated_features}")
        
        # Commit all changes
        session.commit()
    
    # Print summary
    print("\n" + "=" * 60)
    print("BACKFILL SUMMARY")
    print("=" * 60)
    print(f"Total cards processed: {stats['total_cards']}")
    print(f"Baseball player cards: {stats['baseball_cards']}")
    print(f"Cards updated: {stats['cards_updated']}")
    print()
    print("Features added:")
    print(f"  Hall of Fame: {stats['hall_of_fame_added']}")
    print(f"  Rookie: {stats['rookie_added']}")
    print(f"  Season MVP: {stats['mvp_added']}")
    print(f"  Cy Young season: {stats['cy_young_added']}")
    print(f"  Triple Crown season: {stats['triple_crown_added']}")
    print()
    print("Features removed (no longer match criteria):")
    print(f"  Hall of Fame: {stats['hall_of_fame_removed']}")
    print(f"  Rookie: {stats['rookie_removed']}")
    print(f"  Season MVP: {stats['mvp_removed']}")
    print(f"  Cy Young season: {stats['cy_young_removed']}")
    print(f"  Triple Crown season: {stats['triple_crown_removed']}")
    print("=" * 60)

if __name__ == '__main__':
    print("Starting award features backfill...\n")
    backfill_awards()
    print("\nBackfill complete!")
