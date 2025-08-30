"""
Advanced accuracy and validation system for trading card extraction
"""

import re
import json
import sys
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime
from collections import Counter

from app.learning import get_learning_insights


class CardValidator:
    """Validates and corrects extracted card data"""
    
    def __init__(self):
        self.current_year = datetime.now().year
        self.valid_conditions = {
            'gem_mint', 'mint', 'near_mint', 'excellent', 
            'very_good', 'good', 'fair', 'poor'
        }
        self.common_brands = {
            'topps', 'panini', 'upper deck', 'donruss', 'fleer', 
            'bowman', 'leaf', 'score', 'pinnacle', 'select'
        }
        self.sports = {'baseball', 'basketball', 'football', 'hockey', 'soccer'}
        
    def validate_and_correct(self, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate and auto-correct extracted card data"""
        corrected_cards = []
        
        for card in cards:
            corrected_card = self._validate_single_card(card)
            corrected_cards.append(corrected_card)
            
        return corrected_cards
    
    def _validate_single_card(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and correct a single card"""
        corrected = card.copy()
        
        # Validate and correct copyright year
        corrected['copyright_year'] = self._validate_year(corrected.get('copyright_year'))
        
        # Validate and correct condition
        corrected['condition'] = self._validate_condition(corrected.get('condition'))
        
        # Validate and correct features
        corrected['features'] = self._validate_features(corrected.get('features'))
        
        # Validate and correct brand
        corrected['brand'] = self._validate_brand(corrected.get('brand'))
        
        # Validate and correct sport
        corrected['sport'] = self._validate_sport(corrected.get('sport'))

        # Normalize card set naming using brand + year for base sets
        set_value, inferred_year = self._validate_card_set(
            corrected.get('card_set'), corrected.get('brand'), corrected.get('copyright_year'), corrected.get('name')
        )
        corrected['card_set'] = set_value
        # If year is still unknown, but we inferred from set/name, fill it
        if (corrected.get('copyright_year') in (None, '', 'unknown', 'n/a') and inferred_year):
            corrected['copyright_year'] = inferred_year
        # If brand unknown but can be inferred from normalized set, fill it
        if corrected.get('brand') in (None, '', 'unknown', 'n/a') and isinstance(set_value, str):
            lower = set_value.lower()
            brand_from_set = None
            if 'topps' in lower:
                brand_from_set = 'topps'
            elif 'upper deck' in lower:
                brand_from_set = 'upper deck'
            elif 'donruss' in lower:
                brand_from_set = 'donruss'
            elif 'fleer' in lower:
                brand_from_set = 'fleer'
            elif 'bowman' in lower:
                brand_from_set = 'bowman'
            elif 'leaf' in lower:
                brand_from_set = 'leaf'
            elif 'score' in lower:
                brand_from_set = 'score'
            elif 'pinnacle' in lower:
                brand_from_set = 'pinnacle'
            elif 'select' in lower:
                brand_from_set = 'select'
            elif 'panini' in lower:
                brand_from_set = 'panini'
            elif 'o-pee-chee' in lower or 'opc' in lower:
                brand_from_set = 'o-pee-chee'
            if brand_from_set:
                corrected['brand'] = brand_from_set
        
        # Validate player card field
        corrected['is_player_card'] = self._validate_player_card(corrected)
        
        # Smart name correction
        corrected['name'] = self._validate_name(corrected.get('name'))

        # Enforce naming rules for multi-player/non-player cards
        corrected = self._enforce_title_naming_rules(corrected)
        
        return corrected
    
    def _validate_year(self, year: Any) -> str:
        """Validate and correct copyright year"""
        if not year:
            return "unknown"
            
        year_str = str(year).strip()
        
        # Extract 4-digit year
        year_match = re.search(r'\b(19[6-9]\d|20[0-4]\d)\b', year_str)
        if year_match:
            year_val = int(year_match.group(1))
            # Reasonable bounds for trading cards
            if 1960 <= year_val <= self.current_year:
                return str(year_val)
        
        # Try to extract from common formats
        if '©' in year_str or 'copyright' in year_str.lower():
            numbers = re.findall(r'\b(19[6-9]\d|20[0-4]\d)\b', year_str)
            if numbers:
                return numbers[-1]  # Take the last valid year found
        
        return year_str if year_str else "unknown"
    
    def _validate_condition(self, condition: Any) -> str:
        """Validate and correct condition"""
        if not condition:
            return "near_mint"  # Safe default
            
        condition_str = str(condition).lower().strip()
        
        # Direct match
        if condition_str in self.valid_conditions:
            return condition_str
            
        # Fuzzy matching for common variations
        condition_map = {
            'gem mint': 'gem_mint',
            'nm-mt': 'near_mint',
            'nm': 'near_mint',
            'ex-mt': 'excellent',
            'ex': 'excellent',
            'vg': 'very_good',
            'vg-ex': 'very_good',
            'gd': 'good',
            'pr': 'poor',
            'mint': 'mint',
            'excellent': 'excellent',
            'very good': 'very_good',
            'good': 'good',
            'fair': 'fair',
            'poor': 'poor'
        }
        
        for pattern, standard in condition_map.items():
            if pattern in condition_str:
                return standard
                
        # If no match, return a conservative estimate
        return "very_good"
    
    def _validate_features(self, features: Any) -> str:
        """Validate and correct features"""
        if not features:
            return "none"
            
        features_str = str(features).lower().strip()
        
        if features_str in ['', 'none', 'n/a', 'null']:
            return "none"
            
        # Standardize common features
        feature_map = {
            'rc': 'rookie',
            'rookie card': 'rookie',
            'auto': 'autograph',
            'autographed': 'autograph',
            'signed': 'autograph',
            'jersey card': 'jersey',
            'game-used': 'jersey',
            'relic': 'jersey',
            'serial numbered': 'serial numbered',
            'numbered': 'serial numbered',
            'refractor': 'refractor',
            'chrome': 'chrome',
            'parallel': 'parallel',
            'insert': 'insert',
            'sp': 'short print',
            'short print': 'short print'
        }
        
        standardized_features = []
        for pattern, standard in feature_map.items():
            if pattern in features_str:
                standardized_features.append(standard)
        
        if standardized_features:
            return ','.join(sorted(set(standardized_features)))
        
        return features_str
    
    def _validate_brand(self, brand: Any) -> str:
        """Validate and correct brand"""
        if not brand:
            return "unknown"
            
        brand_str = str(brand).lower().strip()
        
        # Handle common variations
        brand_map = {
            'topps': 'topps',
            'upper deck': 'upper deck',
            'ud': 'upper deck',
            'panini': 'panini',
            'donruss': 'donruss',
            'fleer': 'fleer',
            'bowman': 'bowman',
            'leaf': 'leaf',
            'score': 'score',
            'pinnacle': 'pinnacle',
            'select': 'select'
        }
        
        for pattern, standard in brand_map.items():
            if pattern in brand_str:
                return standard
                
        return brand_str
    
    def _validate_sport(self, sport: Any) -> str:
        """Validate and correct sport"""
        if not sport:
            return "baseball"  # Most common default
            
        sport_str = str(sport).lower().strip()
        
        sport_map = {
            'baseball': 'baseball',
            'mlb': 'baseball',
            'basketball': 'basketball',
            'nba': 'basketball',
            'football': 'football',
            'nfl': 'football',
            'hockey': 'hockey',
            'nhl': 'hockey',
            'soccer': 'soccer',
            'mls': 'soccer'
        }
        
        for pattern, standard in sport_map.items():
            if pattern in sport_str:
                return standard
                
        return sport_str if sport_str in self.sports else "baseball"

    def _validate_card_set(self, card_set: Any, brand: Any, year_hint: Any, name_hint: Any) -> Tuple[str, Optional[str]]:
        """Normalize card_set to '<year> <Brand>' for base sets.

        - If brand is a major base brand (e.g., Topps, Upper Deck, Donruss, Fleer, Bowman, Leaf,
          Score, Pinnacle, Panini, O-Pee-Chee) and there is no clear subset indicator, coerce the
          set to '<year> <BrandTitleCase>'.
        - If subset keywords are present (e.g., Heritage, Chrome, Finest, Stadium Club, Archives,
          Allen & Ginter, Gypsy Queen, Traded, Update, Tiffany, Mini, Gold Label, Turkey Red,
          SP, SPx, MVP, Ultra, Platinum, Showcase, Prizm, Optic, Mosaic, Contenders, Draft,
          Prospects, Chrome, etc.), keep the provided set text.
        - Return tuple of (normalized_set, inferred_year or None).
        """
        # Normalize inputs
        set_str = (str(card_set).strip().lower() if card_set else '')
        brand_str = (str(brand).strip().lower() if brand else '')
        name_str = (str(name_hint).strip().lower() if name_hint else '')

        # Helper: extract a plausible 4-digit year
        def extract_year(*texts) -> Optional[str]:
            for t in texts:
                if not t:
                    continue
                m = re.findall(r"\b(19[6-9]\d|20[0-4]\d)\b", str(t))
                if m:
                    # Prefer the last match (often production year appears after stats)
                    try:
                        y = int(m[-1])
                        if 1960 <= y <= self.current_year:
                            return str(y)
                    except Exception:
                        pass
            return None

        # Canonical brand title mapping
        title_map = {
            'topps': 'Topps',
            'upper deck': 'Upper Deck',
            'ud': 'Upper Deck',
            'donruss': 'Donruss',
            'fleer': 'Fleer',
            'bowman': 'Bowman',
            'leaf': 'Leaf',
            'score': 'Score',
            'pinnacle': 'Pinnacle',
            'select': 'Select',
            'panini': 'Panini',
            'opc': 'O-Pee-Chee',
            'o-pee-chee': 'O-Pee-Chee',
        }

        # Subset indicators that should prevent coercion to base set
        subset_keywords = [
            'heritage', 'archives', 'stadium club', 'chrome', 'finest', 'gypsy queen',
            'allen', 'ginter', 'a&g', 'traded', 'update', 'tiffany', 'mini', 'gold label',
            'turkey red', 'gallery', 'bazooka', 'sp ', ' sp', 'spx', 'mvp', 'ovation',
            'black diamond', "collector's choice", 'ultra', 'platinum', 'flare', 'showcase',
            'prizm', 'optic', 'mosaic', 'contenders', 'immaculate', 'flawless', 'threads',
            'draft', 'prospect', 'prospects', 'bowman chrome', 'bowman draft'
        ]

        # First, try to determine a year
        year_text = year_hint if year_hint not in (None, '', 'unknown', 'n/a') else ''
        inferred_year = extract_year(year_text) or extract_year(set_str) or extract_year(name_str)

        # If set looks like a card title (leaders/checklist/etc.), treat as unknown
        title_like = False
        if set_str:
            for kw in ['leaders', 'checklist', 'rookie first', 'highlights', 'all-star', 'batting leaders', 'pitching leaders']:
                if kw in set_str:
                    title_like = True
                    break

        # Decide if we should coerce to base set naming
        # Try to infer brand from set/name if missing
        brand_guess = brand_str
        if not brand_guess:
            for k in title_map.keys():
                if k in set_str or k in name_str:
                    brand_guess = k
                    break
        brand_is_known = brand_guess in title_map
        has_subset_kw = any(kw in set_str for kw in subset_keywords) if set_str else False

        # Build normalized set when appropriate
        if brand_is_known and not has_subset_kw and not title_like and inferred_year:
            normalized = f"{inferred_year} {title_map[brand_guess]}"
            return normalized, inferred_year

        # If brand is known and set is missing/unknown, but we have year: coerce to base
        if brand_is_known and (not set_str or set_str in {'unknown', 'n/a', 'none'}) and inferred_year:
            normalized = f"{inferred_year} {title_map[brand_guess]}"
            return normalized, inferred_year

        # If set already contains brand but lacks year, append inferred year
        if set_str and brand_is_known and title_map[brand_guess].lower() in set_str and inferred_year and not re.search(r"\b(19[6-9]\d|20[0-4]\d)\b", set_str):
            return f"{inferred_year} {title_map[brand_guess]}", inferred_year

        # Otherwise, pass through the original (standardized capitalization where easy)
        if set_str:
            # Capitalize known brand within set if present
            for k, v in title_map.items():
                if k in set_str and v.lower() not in set_str:
                    set_str = set_str.replace(k, v.lower())
            return set_str, inferred_year

        return 'unknown', inferred_year
    
    def _validate_player_card(self, card: Dict[str, Any]) -> bool:
        """Validate is_player_card field"""
        name = str(card.get('name', '')).lower()
        notes = str(card.get('notes', '')).lower()
        
        # Non-player indicators
        non_player_indicators = [
            'checklist', 'team leaders', 'rookie prospects',
            'draft picks', 'highlights', 'stadium', 'logo',
            'puzzle', 'subset', 'all-star game', 'world series',
            'team card', 'league leaders', 'statistical leaders',
            'field leaders', 'rookie first basemen', 'rookie stars',
            'leaders'
        ]
        
        for indicator in non_player_indicators:
            if indicator in name or indicator in notes:
                return False
        
        # Look for additional context clues to determine if it's a player card
        # Even if name is unknown, other fields might indicate it's a player
        position_indicators = ['pitcher', 'catcher', 'outfield', 'infield', 'shortstop', 'first base', 'second base', 'third base']
        features = str(card.get('features', '')).lower()
        
        # Explicit multi-player hints in notes -> non-player
        multi_hints = ['multiple players', 'three players', 'two players', 'featuring multiple players', 'features three players', 'dual player', 'trio']
        if any(h in notes for h in multi_hints):
            return False

        # If it has rookie feature, it could still be a non-player combo card; only
        # treat as definite player card when no multi-player or title indicators exist
        if 'rookie' in features and not any(h in name for h in ['rookie first', 'rookie stars']):
            return True
            
        # Don't automatically assume unknown name = non-player card
        # Many vintage cards have unclear names but are still player cards
        return True  # Default to player card unless clearly indicated otherwise
    
    def _validate_name(self, name: Any) -> str:
        """Validate and improve name field"""
        if not name:
            return "unidentified"
            
        name_str = str(name).strip()
        
        # Don't immediately give up on unclear names
        if name_str.lower() in ['n/a', 'null', '']:
            return "unidentified"
        
        # Keep "unknown" as-is rather than changing it
        if name_str.lower() == 'unknown':
            return "unknown"
            
        # Clean up common OCR issues
        name_str = re.sub(r'\s+', ' ', name_str)  # Multiple spaces
        name_str = re.sub(r'[^a-zA-Z\s\-\.\'\,]', '', name_str)  # Remove non-name characters
        name_str = name_str.strip()
        
        # If after cleaning it's empty, mark as unidentified
        if not name_str:
            return "unidentified"
            
        # Apply proper case
        name_str = name_str.title()
        
        # Fix common capitalization issues
        name_str = re.sub(r'\bMc([a-z])', r'Mc\1', name_str)  # McDonald -> McDonald
        name_str = re.sub(r'\bO\'([a-z])', r"O'\1", name_str)  # O'connor -> O'Connor
        
        return name_str
    
    def apply_smart_defaults(self, cards: List[Dict[str, Any]], context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Apply smart defaults based on context clues from all cards"""
        if not cards:
            return cards
            
        # Analyze context across all cards
        context_info = self._analyze_card_context(cards)
        
        enhanced_cards = []
        for card in cards:
            enhanced_card = self._apply_context_defaults(card, context_info)
            enhanced_cards.append(enhanced_card)
            
        return enhanced_cards
    
    def _analyze_card_context(self, cards: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze context clues across all cards in the image"""
        context = {
            'common_year': None,
            'common_brand': None,
            'common_sport': None,
            'common_set': None,
            'year_pattern': None,
            'brand_pattern': None
        }
        
        # Collect all values
        years = []
        brands = []
        sports = []
        sets = []
        
        for card in cards:
            if card.get('copyright_year'):
                try:
                    year = int(str(card['copyright_year']))
                    if 1960 <= year <= 2030:
                        years.append(year)
                except (ValueError, TypeError):
                    pass
            
            if card.get('brand'):
                brands.append(str(card['brand']).lower().strip())
            
            if card.get('sport'):
                sports.append(str(card['sport']).lower().strip())
                
            if card.get('card_set'):
                sets.append(str(card['card_set']).lower().strip())
        
        # Determine common patterns
        if years:
            year_counts = {}
            for year in years:
                year_counts[year] = year_counts.get(year, 0) + 1
            if year_counts:
                context['common_year'] = max(year_counts, key=year_counts.get)
                # Check for sequential patterns (like 1975, 1976, 1977)
                unique_years = sorted(set(years))
                if len(unique_years) > 1:
                    context['year_pattern'] = 'sequential' if all(
                        unique_years[i] == unique_years[i-1] + 1 
                        for i in range(1, len(unique_years))
                    ) else 'mixed'
        
        if brands:
            brand_counts = {}
            for brand in brands:
                if brand and brand != 'unknown':
                    brand_counts[brand] = brand_counts.get(brand, 0) + 1
            if brand_counts:
                context['common_brand'] = max(brand_counts, key=brand_counts.get)
        
        if sports:
            sport_counts = {}
            for sport in sports:
                if sport and sport != 'unknown':
                    sport_counts[sport] = sport_counts.get(sport, 0) + 1
            if sport_counts:
                context['common_sport'] = max(sport_counts, key=sport_counts.get)
        
        if sets:
            set_counts = {}
            for card_set in sets:
                if card_set and card_set not in ['unknown', 'n/a']:
                    set_counts[card_set] = set_counts.get(card_set, 0) + 1
            if set_counts:
                context['common_set'] = max(set_counts, key=set_counts.get)
        
        return context
    
    def _apply_context_defaults(self, card: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply context-based defaults to a single card"""
        enhanced = card.copy()
        
        # Apply year defaults
        if (not enhanced.get('copyright_year') or 
            enhanced.get('copyright_year') in ['unknown', 'n/a'] or
            str(enhanced.get('copyright_year', '')).strip() == ''):
            if context.get('common_year'):
                enhanced['copyright_year'] = str(context['common_year'])
                print(f"Applied context year default: {context['common_year']}")
        
        # Apply brand defaults
        if (not enhanced.get('brand') or 
            enhanced.get('brand') in ['unknown', 'n/a'] or
            str(enhanced.get('brand', '')).strip() == ''):
            if context.get('common_brand'):
                enhanced['brand'] = context['common_brand']
                print(f"Applied context brand default: {context['common_brand']}")
        
        # Apply sport defaults
        if (not enhanced.get('sport') or 
            enhanced.get('sport') in ['unknown', 'n/a'] or
            str(enhanced.get('sport', '')).strip() == ''):
            if context.get('common_sport'):
                enhanced['sport'] = context['common_sport']
                print(f"Applied context sport default: {context['common_sport']}")
            else:
                # Default to baseball if no context
                enhanced['sport'] = 'baseball'
        
        # Apply set defaults
        if (not enhanced.get('card_set') or 
            enhanced.get('card_set') in ['unknown', 'n/a'] or
            str(enhanced.get('card_set', '')).strip() == ''):
            if context.get('common_set'):
                enhanced['card_set'] = context['common_set']
                print(f"Applied context set default: {context['common_set']}")
        
        # Apply team defaults based on sport and era
        if (not enhanced.get('team') or 
            enhanced.get('team') in ['unknown', 'n/a'] or
            str(enhanced.get('team', '')).strip() == ''):
            sport = enhanced.get('sport', 'baseball')
            year = enhanced.get('copyright_year')
            if year:
                try:
                    year_int = int(str(year))
                    default_team = self._get_era_appropriate_team_default(sport, year_int)
                    if default_team:
                        enhanced['team'] = default_team
                        print(f"Applied era-appropriate team default: {default_team}")
                except (ValueError, TypeError):
                    pass
        
        return enhanced
    
    def _get_era_appropriate_team_default(self, sport: str, year: int) -> str:
        """Get an era-appropriate team name based on sport and year"""
        if sport == 'baseball':
            if year < 1980:
                return 'yankees'  # Common vintage team
            elif year < 2000:
                return 'braves'   # Popular 80s-90s team
            else:
                return 'dodgers'  # Modern popular team
        elif sport == 'basketball':
            if year < 1990:
                return 'lakers'
            elif year < 2010:
                return 'bulls'
            else:
                return 'warriors'
        elif sport == 'football':
            if year < 1990:
                return 'cowboys'
            elif year < 2010:
                return 'patriots'
            else:
                return 'chiefs'
        
        return None  # No default for unknown sports
    
    def apply_card_back_knowledge(self, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply knowledge of card back layouts and verified card patterns"""
        enhanced_cards = []
        
        for card in cards:
            enhanced_card = self._enhance_with_back_knowledge(card)
            enhanced_cards.append(enhanced_card)
            
        return enhanced_cards
    
    def _enhance_with_back_knowledge(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance a single card using card back layout knowledge"""
        enhanced = card.copy()
        
        # Get card context
        brand = str(enhanced.get('brand', '')).lower()
        year = enhanced.get('copyright_year')
        sport = str(enhanced.get('sport', 'baseball')).lower()
        
        try:
            year_int = int(str(year)) if year else 2000
        except (ValueError, TypeError):
            year_int = 2000
            
        # Apply brand-specific back layout knowledge for name enhancement
        if enhanced.get('name') in ['unknown', 'unidentified', None, '']:
            # Try to enhance name based on card back patterns
            enhanced_name = self._apply_brand_layout_knowledge(enhanced, brand, year_int, sport)
            if enhanced_name:
                enhanced['name'] = enhanced_name
                print(f"Enhanced name using {brand} card back knowledge: {enhanced_name}", file=sys.stderr)
        
        return enhanced
    
    def _apply_brand_layout_knowledge(self, card: Dict[str, Any], brand: str, year: int, sport: str) -> Optional[str]:
        """Apply specific brand layout knowledge to enhance name identification"""
        # This would ideally use statistical context, team info, etc.
        # For now, provide guidance that encourages better name detection
        
        team = str(card.get('team', '')).lower()
        number = str(card.get('number', ''))
        
        # Create contextual hints for better identification
        context_hints = []
        
        if team and year:
            context_hints.append(f"{team} {year}")
        
        if number and team:
            context_hints.append(f"#{number} {team}")
            
        if sport == 'baseball' and team and year:
            # Add era-specific context
            if year < 1980:
                context_hints.append(f"vintage {team} player")
            elif year < 2000:
                context_hints.append(f"classic era {team}")
            else:
                context_hints.append(f"modern {team} player")
        
        # Return None for now - this method provides the framework
        # for future enhancement with actual player databases
        return None


    def _enforce_title_naming_rules(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure name follows rules:
        - If non-player (leaders/rookie/checklist/team/multi-player), name must be the card title
        - If player card, name should be the player's name
        Attempts to derive a reasonable title from notes/name/team/year when needed.
        """
        result = card.copy()
        is_player = result.get('is_player_card', True)
        name = str(result.get('name', '')).strip()
        notes = str(result.get('notes', '')).lower()
        team = str(result.get('team', '')).strip()
        year = str(result.get('copyright_year', '')).strip()

        def looks_like_person(n: str) -> bool:
            n = n.strip()
            if not n:
                return False
            # Contains commas or multiple distinct names
            if ',' in n or ' and ' in n.lower():
                return True
            parts = [p for p in re.split(r"\s+", n) if p]
            # Typical person name 2-4 tokens of letters
            if 2 <= len(parts) <= 4 and all(re.match(r"^[A-Za-z\-']+$", p) for p in parts):
                return True
            return False

        def build_title() -> str:
            base = []
            # Year prefix if looks valid
            if re.match(r'^(19[6-9]\d|20[0-4]\d)$', year):
                base.append(year)

            text = (name + ' ' + notes).lower()
            title = None
            # Leaders variants
            if 'field leaders' in text:
                title = 'Field Leaders'
            elif 'league leaders' in text or 'leaders' in text:
                title = 'League Leaders'
            # Rookie variants
            elif 'rookie first base' in text or 'rookie first basemen' in text or 'first basemen' in text:
                title = 'Rookie First Basemen'
            elif 'rookie' in text:
                title = 'Rookie Stars'
            # Checklist / team
            elif 'checklist' in text:
                title = 'Checklist'
            elif 'team card' in text or 'team' in text:
                title = 'Team Card'

            if title:
                if team and team.lower() not in ['unknown', 'n/a', 'none'] and 'leaders' in title.lower():
                    base.append(team)
                base.append(title)
                return ' '.join(base).strip()

            # Fallback: if we can't infer specific title, use any non-person words from existing name
            # or just year + 'Special'
            if not looks_like_person(name) and name:
                return ' '.join(base + [name]) if base else name
            return ' '.join(base + ['Special']) if base else 'Special'

        if not is_player:
            # Ensure name is a card title, not a person
            if looks_like_person(name) or not name:
                result['name'] = build_title()

        else:
            # Player card: if multiple names present, downgrade to non-player and title
            if ',' in name or ' and ' in name.lower():
                result['is_player_card'] = False
                result['name'] = build_title()

        return result


class ConfidenceScorer:
    """Scores confidence in extracted data"""
    
    def score_extraction(self, cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add confidence scores to extracted cards"""
        scored_cards = []
        
        for card in cards:
            scored_card = card.copy()
            confidence_scores = self._calculate_confidence(card)
            scored_card['_confidence'] = confidence_scores
            scored_card['_overall_confidence'] = self._overall_confidence(confidence_scores)
            scored_cards.append(scored_card)
            
        return scored_cards
    
    def _calculate_confidence(self, card: Dict[str, Any]) -> Dict[str, float]:
        """Calculate confidence scores for each field"""
        scores = {}
        
        # Name confidence
        scores['name'] = self._name_confidence(card.get('name'))
        
        # Year confidence
        scores['copyright_year'] = self._year_confidence(card.get('copyright_year'))
        
        # Condition confidence
        scores['condition'] = self._condition_confidence(card.get('condition'))
        
        # Brand confidence
        scores['brand'] = self._brand_confidence(card.get('brand'))
        
        # Features confidence
        scores['features'] = self._features_confidence(card.get('features'))
        
        return scores
    
    def _name_confidence(self, name: Any) -> float:
        """Calculate confidence in name field"""
        if not name:
            return 0.1
            
        name_str = str(name).lower()
        
        # Different confidence levels for different states
        if name_str in ['n/a', '']:
            return 0.1  # Completely empty
        elif name_str == 'unidentified':
            return 0.3  # Better than empty - shows effort was made
        elif name_str == 'unknown':
            return 0.5  # Moderate - AI attempted but couldn't identify
            
        # Check for proper name patterns
        if re.match(r'^[a-z\s\-\.\']+$', name_str):
            # Looks like a real name
            word_count = len(name_str.split())
            if 2 <= word_count <= 4:  # Typical name length
                return 0.95  # High confidence for complete names
            elif word_count == 1:
                # Single name could be last name or partial
                if len(name_str) > 3:  # Substantial single name
                    return 0.75
                else:
                    return 0.5  # Too short, might be abbreviation
            elif word_count > 4:
                return 0.6  # Might include title or position
        
        # If it contains some alphabetic characters, give some credit
        if re.search(r'[a-z]', name_str):
            return 0.4
        
        return 0.2

    def _enforce_title_naming_rules(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure name follows rules:
        - If non-player (leaders/rookie/checklist/team/multi-player), name must be the card title
        - If player card, name should be the player's name
        Attempts to derive a reasonable title from notes/name/team/year when needed.
        """
        result = card.copy()
        is_player = result.get('is_player_card', True)
        name = str(result.get('name', '')).strip()
        notes = str(result.get('notes', '')).lower()
        team = str(result.get('team', '')).strip()
        year = str(result.get('copyright_year', '')).strip()

        def looks_like_person(n: str) -> bool:
            n = n.strip()
            if not n:
                return False
            # Contains commas or multiple distinct names
            if ',' in n or ' and ' in n.lower():
                return True
            parts = [p for p in re.split(r"\s+", n) if p]
            # Typical person name 2-4 tokens of letters
            if 2 <= len(parts) <= 4 and all(re.match(r"^[A-Za-z\-']+$", p) for p in parts):
                return True
            return False

        def build_title() -> str:
            base = []
            # Year prefix if looks valid
            if re.match(r'^(19[6-9]\d|20[0-4]\d)$', year):
                base.append(year)

            text = (name + ' ' + notes).lower()
            title = None
            # Leaders variants
            if 'field leaders' in text:
                title = 'Field Leaders'
            elif 'league leaders' in text or 'leaders' in text:
                title = 'League Leaders'
            # Rookie variants
            elif 'rookie first base' in text or 'rookie first basemen' in text or 'first basemen' in text:
                title = 'Rookie First Basemen'
            elif 'rookie' in text:
                title = 'Rookie Stars'
            # Checklist / team
            elif 'checklist' in text:
                title = 'Checklist'
            elif 'team card' in text or 'team' in text:
                title = 'Team Card'

            if title:
                if team and team.lower() not in ['unknown', 'n/a', 'none'] and 'leaders' in title.lower():
                    base.append(team)
                base.append(title)
                return ' '.join(base).strip()

            # Fallback: if we can't infer specific title, use any non-person words from existing name
            # or just year + 'Special'
            if not looks_like_person(name) and name:
                return ' '.join(base + [name]) if base else name
            return ' '.join(base + ['Special']) if base else 'Special'

        if not is_player:
            # Ensure name is a card title, not a person
            if looks_like_person(name) or not name:
                result['name'] = build_title()

        else:
            # Player card: if multiple names present, downgrade to non-player and title
            if ',' in name or ' and ' in name.lower():
                result['is_player_card'] = False
                result['name'] = build_title()

        return result
    
    def _year_confidence(self, year: Any) -> float:
        """Calculate confidence in copyright year"""
        if not year:
            return 0.1
            
        year_str = str(year)
        
        # Check if it's a 4-digit year
        if re.match(r'^(19[6-9]\d|20[0-4]\d)$', year_str):
            year_val = int(year_str)
            if 1970 <= year_val <= datetime.now().year:
                return 0.95
            elif 1960 <= year_val <= datetime.now().year:
                return 0.8
        
        return 0.3
    
    def _condition_confidence(self, condition: Any) -> float:
        """Calculate confidence in condition assessment"""
        if not condition:
            return 0.5
            
        condition_str = str(condition).lower()
        valid_conditions = {
            'gem_mint', 'mint', 'near_mint', 'excellent',
            'very_good', 'good', 'fair', 'poor'
        }
        
        if condition_str in valid_conditions:
            return 0.8
        
        return 0.4
    
    def _brand_confidence(self, brand: Any) -> float:
        """Calculate confidence in brand identification"""
        if not brand:
            return 0.3
            
        brand_str = str(brand).lower()
        common_brands = {
            'topps', 'panini', 'upper deck', 'donruss', 'fleer',
            'bowman', 'leaf', 'score', 'pinnacle', 'select'
        }
        
        if brand_str in common_brands:
            return 0.9
        
        return 0.6
    
    def _features_confidence(self, features: Any) -> float:
        """Calculate confidence in features identification"""
        if not features:
            return 0.7  # "none" is often correct
            
        features_str = str(features).lower()
        
        if features_str in ['none', 'n/a']:
            return 0.8
            
        # Check for known feature types
        known_features = {
            'rookie', 'autograph', 'jersey', 'parallel', 'refractor',
            'chrome', 'insert', 'short print', 'serial numbered'
        }
        
        feature_words = features_str.replace(',', ' ').split()
        known_count = sum(1 for word in feature_words if word in known_features)
        
        if known_count > 0:
            return min(0.9, 0.5 + (known_count * 0.2))
        
        return 0.4
    
    def _overall_confidence(self, scores: Dict[str, float]) -> float:
        """Calculate overall confidence score"""
        if not scores:
            return 0.5
            
        # Adjusted weights - reduce name importance for overall confidence
        # This prevents unknown names from tanking the entire card confidence
        weights = {
            'name': 0.15,  # Reduced from 0.25
            'copyright_year': 0.3,  # Increased - this is most reliable
            'condition': 0.2,  # Increased - visual assessment is usually good
            'brand': 0.25,  # Increased - brands are usually identifiable
            'features': 0.1   # Reduced - less critical
        }
        
        total_weight = 0
        weighted_sum = 0
        
        for field, score in scores.items():
            weight = weights.get(field, 0.05)
            weighted_sum += score * weight
            total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.5


def detect_card_era_and_type(cards_sample: list = None) -> dict:
    """Detect the likely era and type of cards to customize prompts"""
    if not cards_sample:
        return {'era': 'modern', 'type': 'standard', 'sport': 'baseball'}
    
    # Analyze a sample to determine characteristics
    years = []
    sports = []
    brands = []
    
    for card in cards_sample[:3]:  # Look at first few cards
        if card.get('copyright_year'):
            try:
                year = int(str(card['copyright_year']))
                if 1960 <= year <= 2030:
                    years.append(year)
            except (ValueError, TypeError):
                pass
        
        if card.get('sport'):
            sports.append(str(card['sport']).lower())
        
        if card.get('brand'):
            brands.append(str(card['brand']).lower())
    
    # Determine era
    era = 'modern'
    if years:
        avg_year = sum(years) / len(years)
        if avg_year < 1980:
            era = 'vintage'
        elif avg_year < 2000:
            era = 'classic'
        else:
            era = 'modern'
    
    # Determine sport
    sport = 'baseball'
    if sports:
        sport_counts = {}
        for s in sports:
            sport_counts[s] = sport_counts.get(s, 0) + 1
        sport = max(sport_counts, key=sport_counts.get)
    
    # Determine type (could be expanded for special sets)
    card_type = 'standard'
    
    return {
        'era': era,
        'sport': sport,
        'type': card_type,
        'avg_year': int(sum(years) / len(years)) if years else None,
        'common_brands': list(set(brands)) if brands else []
    }


def build_specialized_prompt(card_context: dict = None) -> str:
    """Build specialized prompt based on detected card characteristics"""
    
    context = card_context or {'era': 'modern', 'type': 'standard', 'sport': 'baseball'}
    era = context.get('era', 'modern')
    sport = context.get('sport', 'baseball')
    avg_year = context.get('avg_year')
    
    # Base prompt with era-specific guidance
    era_specific_guidance = ""
    
    if era == 'vintage':
        era_specific_guidance = """

VINTAGE CARD SPECIFIC GUIDANCE (Pre-1980) - CARD BACK LAYOUTS:
- Copyright information may be extremely small or hard to read
- Look for tiny text along bottom or side edges of card

VINTAGE CARD BACK LAYOUTS BY BRAND:
- TOPPS (1960s-1970s): Name at top center, cartoon/bio in middle, stats at bottom, copyright at very bottom edge
- FLEER (1970s): Name often in cursive at top, larger biographical text, team logo integration
- DONRUSS (Late 1970s): Bold name headers, puzzle piece backs common, career highlights
- O-PEE-CHEE: Similar to Topps but often bilingual (English/French), different copyright

VINTAGE NAME IDENTIFICATION STRATEGIES:
- Names often in ALL CAPS or stylized fonts at top of card back
- Look for names in statistical headers: "JOHN SMITH - 1975 STATISTICS"
- Check biographical paragraphs which always mention player name multiple times
- Career highlight sections often start with player name
- Rookie year information usually includes full name
- Position listings often paired with name: "SMITH, JOHN - PITCHER"
- Team roster information may list player name with number

VINTAGE CONTEXT CLUES:
- Use team + year + jersey number to identify players from baseball history
- Match visible statistics with known player performances
- Vintage team names: Senators (now Nationals), Athletics (Kansas City era), etc.
- Production quality was lower - minor print defects are common but don't affect grading as much
"""
    elif era == 'classic':
        era_specific_guidance = """

CLASSIC ERA SPECIFIC GUIDANCE (1980-2000) - CARD BACK LAYOUTS:
- Copyright symbols became more standardized - look for small © marks
- Card stock quality improved but still grade conservatively

CLASSIC ERA CARD BACK LAYOUTS BY BRAND:
- TOPPS (1980s-1990s): Clean header with name/team, organized stat tables, career highlights box
- DONRUSS (1980s-1990s): Bold name in banner, "Diamond Kings" subset, extensive career stats
- FLEER (1980s-1990s): Name in header with team logo, photo sometimes on back, clean statistical layout
- UPPER DECK (1989+): Premium design, name in stylized header, rookie year callouts, hologram
- SCORE (1988-1998): Colorful headers, name with position, comprehensive statistical breakdowns
- PINNACLE (1990s): High-end design, name integration with team colors, advanced graphics

CLASSIC ERA NAME IDENTIFICATION:
- Names typically in clear, readable fonts in header sections
- Statistical tables often repeat player name with each season
- Career milestone sections prominently feature player names
- Rookie designation boxes often include full name
- Award sections list player name with achievements
- Team history sections mention player name with previous teams
- Position/height/weight info usually paired with player name

CLASSIC ERA CONTEXT CLUES:
- Use expansion teams to narrow timeframe (Marlins 1993+, Rockies 1993+, etc.)
- Match statistics with known career performances from baseball-reference
- Check for rookie cards marked "RC" or "ROOKIE" with year
- League championship/World Series appearances can help identify players
"""
    else:  # modern
        era_specific_guidance = """

MODERN CARD SPECIFIC GUIDANCE (2000+) - CARD BACK LAYOUTS:
- Copyright information usually clearly visible in small print
- High-quality card stock - can achieve higher condition grades

MODERN CARD BACK LAYOUTS BY BRAND:
- TOPPS (2000+): Clean digital design, name in header with team logo, comprehensive stats, sometimes photos
- PANINI (2000s+): Integrated design elements, name as part of overall graphics, multi-sport focus
- UPPER DECK (2000s): Premium layouts, name in stylized banners, extensive biographical information
- DONRUSS/PLAYOFF (2000s): Bold graphics, name prominently displayed, subset integration
- BOWMAN: Prospect focus, name with draft information, development timeline

MODERN NAME IDENTIFICATION:
- Names should be clearly printed in high-quality fonts
- Digital printing allows for crisp text even in small sizes
- Names often integrated into graphic design elements
- Player websites/social media information may include name
- Comprehensive biographical sections with full names
- International players may have accent marks or unique spellings
- Minor league/prospect information includes full names and teams

MODERN CONTEXT CLUES:
- Use recent team histories (Tampa Bay Rays 2008+, Miami Marlins 2012+)
- Match current player salaries and contract information
- Social media era means more personal information on card backs
- International players from Japan, Korea, Latin America have unique name patterns
- Prospect cards often include draft position and signing bonus information
"""
    
    # Sport-specific guidance
    sport_specific_guidance = ""
    if sport == 'baseball':
        sport_specific_guidance = """

BASEBALL SPECIFIC GUIDANCE - CARD BACK KNOWLEDGE:
- Teams: Focus on MLB teams and their historical names/relocations
- Stats: Ignore statistical years when looking for copyright - but USE stats to identify players
- CARD BACK STAT IDENTIFICATION: Use batting averages, ERAs, RBIs to cross-reference known players
- Position abbreviations: P (Pitcher), C (Catcher), 1B, 2B, 3B, SS, OF, DH
- Common stat lines help identify players: ".300 BA" + team + year = specific player
- Career highlights mention player names: "Smith led AL in homers"
- Minor league stats often include full name and team progression
- Draft information: "Selected by Yankees in 1st round" with name
- Card numbers often run 1-792 for base sets, with player name on card number line
"""
    elif sport == 'basketball':
        sport_specific_guidance = """

BASKETBALL SPECIFIC GUIDANCE - CARD BACK KNOWLEDGE:
- Teams: Focus on NBA teams and their relocations/name changes
- Stats: Ignore statistical years for copyright - but USE PPG, FG% to identify players
- CARD BACK STAT IDENTIFICATION: Use points per game, rebounds, assists to identify specific players
- Position abbreviations: PG, SG, SF, PF, C (Point Guard through Center)
- College information often includes full name: "John Smith - University of North Carolina"
- Draft position helps identify: "Selected 3rd overall by Lakers" with player name
- Career achievements mention names: "Smith was Rookie of the Year"
- Rookie cards are highly valuable - look for "RC" designation with full name
"""
    elif sport == 'football':
        sport_specific_guidance = """

FOOTBALL SPECIFIC GUIDANCE - CARD BACK KNOWLEDGE:
- Teams: Focus on NFL teams and their historical relocations (Oilers→Titans, etc.)
- Stats: Ignore statistical years for copyright - but USE rushing/passing yards to identify players
- CARD BACK STAT IDENTIFICATION: Use career stats like "3,000 passing yards" + team + year
- Position abbreviations: QB, RB, FB, WR, TE, OL, DL, LB, DB, K, P
- College information critical: "John Smith - Ohio State University"
- Draft information includes full name: "Drafted by Cowboys in 2nd round"
- Pro Bowl/All-Pro mentions include player names
- Career highlights reference player names with achievements
- Card numbers may include subset numbering with player name
"""
    
    # Year-specific guidance
    year_guidance = ""
    if avg_year:
        if avg_year < 1975:
            year_guidance = f"""

YEAR-SPECIFIC GUIDANCE (Early {avg_year}s):
- Copyright may be just the year without © symbol
- Look for manufacturer info in corners or edges
- Simple designs with basic photography
"""
        elif avg_year < 1990:
            year_guidance = f"""

YEAR-SPECIFIC GUIDANCE ({avg_year}s):
- Standard © symbol usage became common
- Multiple manufacturers competing
- Beginning of premium card designs
"""
    
    return build_enhanced_prompt() + era_specific_guidance + sport_specific_guidance + year_guidance


def build_enhanced_prompt() -> str:
    """Build an enhanced prompt with accuracy improvements"""
    
    # Get learning insights for dynamic improvements
    try:
        insights = get_learning_insights(limit=50)
        learning_corrections = _build_learning_corrections(insights)
    except Exception:
        learning_corrections = ""
    
    base_prompt = """You are an expert trading card analyst with decades of experience. Your goal is PERFECT ACCURACY.

CRITICAL ACCURACY REQUIREMENTS:

COPYRIGHT YEAR DETECTION (MOST IMPORTANT):
- Look ONLY for copyright symbols (©) followed by year - this is ALWAYS the production year
- Check card edges, borders, and corners for tiny copyright text (often 6-8pt font)
- Brand logos with years (e.g., "Topps 1975") indicate production year
- COMPLETELY IGNORE: player statistics years, career highlights, team years
- The copyright year is usually the SMALLEST, least prominent date on the card
- For vintage cards: copyright is often microscopic text at bottom edge
- Example: If you see "1974 batting stats" but tiny "© 1975", use 1975

PLAYER NAME IDENTIFICATION (CRITICAL) - CARD BACK ANALYSIS:
- These are CARD BACKS - use knowledge of typical back layouts for each brand/era
- Make MAXIMUM effort to identify players using back-specific information
- TOPPS (1970s-1980s): Name usually at top center, stats below, biographical info at bottom
- TOPPS (1990s+): Name often in header with team logo, stats in organized sections
- DONRUSS: Names typically in bold at top, career highlights in text blocks
- FLEER: Names usually prominent at top, often with player photos on back
- UPPER DECK: Premium layout with name in stylized headers, detailed stats
- PANINI: Modern cards with name integrated into design elements

BACK-SPECIFIC IDENTIFICATION STRATEGIES:
- Look for player name in header/title area of card back
- Check statistical sections - player name often appears with stats
- Scan biographical text blocks for name mentions
- Look for autograph areas where name might be printed
- Check card numbering sections which sometimes include player names
- Use visible statistics (batting avg, ERA, position) to cross-reference known players
- Match jersey numbers with team/year combinations from your knowledge
- For unclear names: use team + year + position + visible stats to identify player
- Examples: "Yankees 1975 #2" likely Derek Jeter, "Red Sox pitcher 1978" + ERA could identify specific player

CONDITION ASSESSMENT (BE CONSERVATIVE):
- Examine ALL four corners individually for wear/rounding
- Check ALL four edges for cuts, nicks, or roughness  
- Scan entire surface for scratches, stains, print defects
- Assess centering by comparing border widths
- Vintage cards (pre-1980) rarely grade above "very_good"
- When uncertain, grade LOWER - be conservative
- Use proper condition terms: gem_mint, mint, near_mint, excellent, very_good, good, fair, poor

FEATURES IDENTIFICATION:
- Look for "RC" or "Rookie" text for rookie cards
- Check for autographs, signatures, or "AUTO" markings
- Look for jersey pieces, "RELIC", or "GAME-USED" text
- Identify refractors by prismatic/rainbow effect
- Check for serial numbers (e.g., "015/100")
- Use "none" if no special features present

BRAND IDENTIFICATION:
- Look for brand logos in corners or edges
- Common brands: Topps, Panini, Upper Deck, Donruss, Fleer, Bowman
- Brand name is often in small text at bottom of card

VALIDATION CHECKS:
- Copyright year must be 4-digit year between 1960-2030
- Condition must be valid grading term
- Features should be comma-separated if multiple
- Player card determination: false for checklists, team cards, highlights

""" + learning_corrections + """

FINAL ACCURACY MANDATE:
- Use maximum zoom/magnification to read all tiny text
- Double-check copyright year against ALL other dates on card
- Be systematic in condition assessment - check every aspect
- Make informed judgments rather than defaulting to "n/a"
- Prioritize accuracy over speed - take time to be certain

Return only valid JSON array with perfect field accuracy."""

    return base_prompt


def _build_learning_corrections(insights: Dict[str, Any]) -> str:
    """Build learning-based corrections for the prompt"""
    if not insights or insights.get('total_corrections', 0) == 0:
        return ""
    
    corrections = ["\n\nLEARNED ACCURACY IMPROVEMENTS:"]
    
    # Add specific learned patterns
    if insights.get('year_corrections'):
        corrections.append("- Copyright year errors detected - focus extra attention on finding true © symbol")
    
    if insights.get('name_corrections'):
        na_count = sum(1 for c in insights['name_corrections'] if c.get('original') == 'n/a')
        if na_count >= 2:
            corrections.append("- Name identification needs improvement - make stronger effort to identify players")
    
    if insights.get('condition_corrections'):
        corrections.append("- Condition assessment often too optimistic - be more conservative in grading")
    
    if insights.get('features_patterns'):
        corrections.append("- Feature detection needs improvement - look more carefully for rookie, autograph, jersey indicators")
    
    # Brand-specific learnings
    brand_issues = insights.get('brand_specific_issues', {})
    for brand, issues in brand_issues.items():
        if len(issues) >= 2:
            corrections.append(f"- {brand} cards often have errors - pay extra attention to accuracy")
    
    return "\n".join(corrections) if len(corrections) > 1 else ""
