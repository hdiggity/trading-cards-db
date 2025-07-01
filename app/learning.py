"""
Learning system for improving AI accuracy based on user corrections
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from collections import defaultdict, Counter

from sqlalchemy.orm import Session
from app.database import get_session
from app.models import LearningData


def store_user_corrections(
    image_filename: str,
    original_data: List[Dict[str, Any]],
    corrected_data: List[Dict[str, Any]],
    session: Optional[Session] = None
):
    """
    Store user corrections for learning purposes
    
    Args:
        image_filename: Name of the image file being corrected
        original_data: Original AI-extracted data
        corrected_data: User-corrected data
        session: Database session (optional)
    """
    if session is None:
        session = get_session()
        should_close = True
    else:
        should_close = False
    
    try:
        # Compare original vs corrected data
        for i, (original_card, corrected_card) in enumerate(zip(original_data, corrected_data)):
            for field_name in original_card.keys():
                original_value = original_card.get(field_name)
                corrected_value = corrected_card.get(field_name)
                
                # Only store if there was a change
                if original_value != corrected_value:
                    correction_type = determine_correction_type(field_name, original_value, corrected_value)
                    
                    # Create context data
                    context = {
                        'card_index': i,
                        'total_cards': len(original_data),
                        'other_fields': {k: v for k, v in original_card.items() if k != field_name},
                        'brand': original_card.get('brand'),
                        'copyright_year': original_card.get('copyright_year'),
                        'sport': original_card.get('sport')
                    }
                    
                    learning_entry = LearningData(
                        image_filename=image_filename,
                        field_name=field_name,
                        ai_original_value=str(original_value) if original_value is not None else None,
                        user_corrected_value=str(corrected_value) if corrected_value is not None else None,
                        correction_type=correction_type,
                        context_data=json.dumps(context),
                        timestamp=datetime.now()
                    )
                    
                    session.add(learning_entry)
        
        session.commit()
        
    except Exception as e:
        session.rollback()
        print(f"Error storing learning data: {e}")
    finally:
        if should_close:
            session.close()


def determine_correction_type(field_name: str, original_value: Any, corrected_value: Any) -> str:
    """Determine the type of correction made"""
    if original_value is None and corrected_value is not None:
        return 'value_added'
    elif original_value is not None and corrected_value is None:
        return 'value_removed'
    elif field_name == 'copyright_year':
        return 'year_correction'
    elif field_name in ['name', 'brand', 'team']:
        return 'text_correction'
    elif field_name == 'condition':
        return 'condition_correction'
    elif field_name == 'features':
        return 'features_correction'
    elif field_name in ['is_player_card']:
        return 'boolean_correction'
    else:
        return 'value_change'


def get_learning_insights(limit: int = 100) -> Dict[str, Any]:
    """
    Analyze learning data to extract insights for prompt improvement
    
    Returns:
        Dictionary containing learning insights and patterns
    """
    with get_session() as session:
        # Get recent learning data
        recent_corrections = session.query(LearningData).order_by(
            LearningData.timestamp.desc()
        ).limit(limit).all()
        
        insights = {
            'total_corrections': len(recent_corrections),
            'field_error_patterns': defaultdict(list),
            'common_mistakes': defaultdict(int),
            'year_corrections': [],
            'name_corrections': [],
            'condition_corrections': [],
            'features_patterns': [],
            'brand_specific_issues': defaultdict(list)
        }
        
        for correction in recent_corrections:
            field = correction.field_name
            original = correction.ai_original_value
            corrected = correction.user_corrected_value
            correction_type = correction.correction_type
            
            # Parse context
            try:
                context = json.loads(correction.context_data) if correction.context_data else {}
            except json.JSONDecodeError:
                context = {}
            
            # Track field-specific patterns
            insights['field_error_patterns'][field].append({
                'original': original,
                'corrected': corrected,
                'type': correction_type,
                'context': context
            })
            
            # Track common mistake patterns
            mistake_key = f"{field}:{correction_type}"
            insights['common_mistakes'][mistake_key] += 1
            
            # Specific field analysis
            if field == 'copyright_year':
                insights['year_corrections'].append({
                    'original': original,
                    'corrected': corrected,
                    'brand': context.get('brand'),
                    'context': context
                })
            
            elif field == 'name':
                insights['name_corrections'].append({
                    'original': original,
                    'corrected': corrected,
                    'context': context
                })
            
            elif field == 'condition':
                insights['condition_corrections'].append({
                    'original': original,
                    'corrected': corrected,
                    'context': context
                })
            
            elif field == 'features':
                insights['features_patterns'].append({
                    'original': original,
                    'corrected': corrected,
                    'context': context
                })
            
            # Brand-specific issues
            brand = context.get('brand')
            if brand:
                insights['brand_specific_issues'][brand].append({
                    'field': field,
                    'original': original,
                    'corrected': corrected,
                    'type': correction_type
                })
        
        return dict(insights)


def generate_learning_prompt_enhancements() -> str:
    """
    Generate prompt enhancements based on learning data
    
    Returns:
        String containing additional prompt instructions based on learned patterns
    """
    insights = get_learning_insights()
    
    if insights['total_corrections'] == 0:
        return ""
    
    enhancements = ["\\n\\nLEARNED CORRECTIONS AND IMPROVEMENTS:"]
    
    # Year correction patterns
    if insights['year_corrections']:
        year_issues = analyze_year_corrections(insights['year_corrections'])
        if year_issues:
            enhancements.append("\\nCOPYRIGHT YEAR CORRECTIONS LEARNED:")
            enhancements.extend([f"- {issue}" for issue in year_issues])
    
    # Name correction patterns
    if insights['name_corrections']:
        name_issues = analyze_name_corrections(insights['name_corrections'])
        if name_issues:
            enhancements.append("\\nPLAYER NAME CORRECTIONS LEARNED:")
            enhancements.extend([f"- {issue}" for issue in name_issues])
    
    # Condition correction patterns
    if insights['condition_corrections']:
        condition_issues = analyze_condition_corrections(insights['condition_corrections'])
        if condition_issues:
            enhancements.append("\\nCONDITION ASSESSMENT CORRECTIONS LEARNED:")
            enhancements.extend([f"- {issue}" for issue in condition_issues])
    
    # Features patterns
    if insights['features_patterns']:
        features_issues = analyze_features_patterns(insights['features_patterns'])
        if features_issues:
            enhancements.append("\\nFEATURES IDENTIFICATION CORRECTIONS LEARNED:")
            enhancements.extend([f"- {issue}" for issue in features_issues])
    
    # Brand-specific issues
    brand_issues = analyze_brand_specific_issues(insights['brand_specific_issues'])
    if brand_issues:
        enhancements.append("\\nBRAND-SPECIFIC CORRECTIONS LEARNED:")
        enhancements.extend([f"- {issue}" for issue in brand_issues])
    
    # Common mistake patterns
    common_mistakes = get_top_mistakes(insights['common_mistakes'])
    if common_mistakes:
        enhancements.append("\\nMOST COMMON MISTAKES TO AVOID:")
        enhancements.extend([f"- {mistake}" for mistake in common_mistakes])
    
    return "\\n".join(enhancements)


def analyze_year_corrections(year_corrections: List[Dict]) -> List[str]:
    """Analyze copyright year correction patterns"""
    issues = []
    
    # Check for patterns in year mistakes
    year_mistakes = defaultdict(list)
    for correction in year_corrections:
        if correction['original'] and correction['corrected']:
            original_year = correction['original']
            corrected_year = correction['corrected']
            brand = correction.get('context', {}).get('brand', 'unknown')
            year_mistakes[brand].append((original_year, corrected_year))
    
    # Analyze patterns
    for brand, mistakes in year_mistakes.items():
        if len(mistakes) >= 2:  # Only if we have multiple examples
            common_patterns = Counter(mistakes)
            for (orig, corr), count in common_patterns.most_common(3):
                if count >= 2:
                    issues.append(f"For {brand} cards, AI often mistakes {orig} for {corr} - check copyright more carefully")
    
    return issues


def analyze_name_corrections(name_corrections: List[Dict]) -> List[str]:
    """Analyze player name correction patterns"""
    issues = []
    
    na_corrections = [c for c in name_corrections if c['original'] == 'n/a']
    if len(na_corrections) >= 3:
        issues.append("AI frequently uses 'n/a' for player names - make stronger effort to identify players from jersey numbers, team context, or visual features")
    
    return issues


def analyze_condition_corrections(condition_corrections: List[Dict]) -> List[str]:
    """Analyze condition assessment correction patterns"""
    issues = []
    
    condition_changes = defaultdict(int)
    for correction in condition_corrections:
        if correction['original'] and correction['corrected']:
            change = f"{correction['original']} → {correction['corrected']}"
            condition_changes[change] += 1
    
    # Find common condition adjustments
    for change, count in condition_changes.most_common(3):
        if count >= 2:
            issues.append(f"AI often grades too high: '{change}' - be more conservative in condition assessment")
    
    return issues


def analyze_features_patterns(features_patterns: List[Dict]) -> List[str]:
    """Analyze features identification patterns"""
    issues = []
    
    empty_to_filled = [p for p in features_patterns if not p['original'] and p['corrected']]
    if len(empty_to_filled) >= 3:
        issues.append("AI often misses features - look more carefully for rookie cards, autographs, jersey cards, etc.")
    
    return issues


def analyze_brand_specific_issues(brand_issues: Dict[str, List]) -> List[str]:
    """Analyze brand-specific correction patterns"""
    issues = []
    
    for brand, corrections in brand_issues.items():
        if len(corrections) >= 3:
            field_counts = Counter([c['field'] for c in corrections])
            for field, count in field_counts.most_common(2):
                if count >= 2:
                    issues.append(f"For {brand} cards, AI often makes mistakes with {field} - pay extra attention")
    
    return issues


def get_top_mistakes(common_mistakes: Dict[str, int]) -> List[str]:
    """Get the most common mistake patterns"""
    issues = []
    
    for mistake_pattern, count in Counter(common_mistakes).most_common(5):
        if count >= 3:
            field, mistake_type = mistake_pattern.split(':', 1)
            issues.append(f"Field '{field}' frequently has {mistake_type} errors - double-check this field")
    
    return issues