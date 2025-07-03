"""
Enhanced online verification system for trading cards using multiple sources
"""

import re
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from .tcdb_scraper import search_tcdb_cards


@dataclass
class VerificationResult:
    """Result from online verification"""
    source: str
    confidence: float
    matched_data: Dict[str, Any]
    query_used: str
    raw_results: List[Dict]


class OnlineVerifier:
    """Enhanced online verification using multiple sources"""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )
    
    def verify_card_comprehensive(self, card_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive verification using multiple online sources
        """
        verification_results = []
        
        # Build search queries with different strategies
        queries = self._build_verification_queries(card_data)
        
        for query_info in queries:
            query = query_info['query']
            strategy = query_info['strategy']
            
            # Try TCDB first (most reliable for trading cards)
            tcdb_result = self._verify_with_tcdb(query, card_data)
            if tcdb_result:
                tcdb_result.query_used = f"{strategy}: {query}"
                verification_results.append(tcdb_result)
            
            # Try Baseball Reference for baseball cards
            if card_data.get('sport', '').lower() == 'baseball':
                bbref_result = self._verify_with_baseball_reference(query, card_data)
                if bbref_result:
                    bbref_result.query_used = f"{strategy}: {query}"
                    verification_results.append(bbref_result)
            
            # Try Sports Reference (covers multiple sports)
            sports_ref_result = self._verify_with_sports_reference(query, card_data)
            if sports_ref_result:
                sports_ref_result.query_used = f"{strategy}: {query}"
                verification_results.append(sports_ref_result)
            
            # Add small delay between queries
            time.sleep(0.5)
        
        # Combine and analyze results
        enhanced_card = self._combine_verification_results(card_data, verification_results)
        
        return enhanced_card
    
    def _build_verification_queries(self, card_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Build multiple search queries for verification"""
        queries = []
        
        name = card_data.get('name', '').strip()
        team = card_data.get('team', '').strip()
        year = card_data.get('copyright_year', '').strip()
        sport = card_data.get('sport', '').strip()
        brand = card_data.get('brand', '').strip()
        number = card_data.get('number', '').strip()
        
        # Skip verification for unidentified cards
        if not name or name.lower() in ['unidentified', 'unknown', 'n/a']:
            return []
        
        # Strategy 1: Full card identification
        if name and team and year:
            queries.append({
                'query': f"{name} {team} {year}",
                'strategy': 'full_identification'
            })
        
        # Strategy 2: Player + year (for career verification)
        if name and year:
            queries.append({
                'query': f"{name} {year}",
                'strategy': 'player_year'
            })
        
        # Strategy 3: Player + team (for team verification)
        if name and team:
            queries.append({
                'query': f"{name} {team}",
                'strategy': 'player_team'
            })
        
        # Strategy 4: Set-specific search
        if name and brand and year:
            queries.append({
                'query': f"{name} {brand} {year}",
                'strategy': 'set_specific'
            })
        
        # Strategy 5: Card number + set
        if number and brand and year:
            queries.append({
                'query': f"#{number} {brand} {year}",
                'strategy': 'card_number'
            })
        
        # Strategy 6: Just player name (broad search)
        if name and len(name.split()) >= 2:
            queries.append({
                'query': name,
                'strategy': 'player_only'
            })
        
        return queries[:3]  # Limit to 3 queries to avoid rate limiting
    
    def _verify_with_tcdb(self, query: str, card_data: Dict) -> Optional[VerificationResult]:
        """Verify card using TCDB"""
        try:
            results = search_tcdb_cards(query, max_results=3)
            
            if not results:
                return None
            
            # Find best match
            best_match = self._find_best_tcdb_match(results, card_data)
            if not best_match:
                return None
            
            confidence = self._calculate_tcdb_confidence(best_match, card_data)
            
            return VerificationResult(
                source="tcdb",
                confidence=confidence,
                matched_data=best_match,
                query_used=query,
                raw_results=results
            )
            
        except Exception as e:
            print(f"TCDB verification error: {e}")
            return None
    
    def _verify_with_baseball_reference(self, query: str, card_data: Dict) -> Optional[VerificationResult]:
        """Verify baseball player using Baseball Reference"""
        try:
            # Baseball Reference search
            search_url = "https://www.baseball-reference.com/search/search.fcgi"
            params = {
                'search': query,
                'results': 'all'
            }
            
            response = self.session.get(search_url, params=params)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Parse search results
            player_links = soup.find_all('a', href=re.compile(r'/players/[a-z]/.*\.shtml'))
            
            if not player_links:
                return None
            
            # Get detailed info for first few matches
            matches = []
            for link in player_links[:2]:  # Limit to avoid rate limiting
                player_url = f"https://www.baseball-reference.com{link.get('href')}"
                player_info = self._get_baseball_reference_player_info(player_url)
                if player_info:
                    matches.append(player_info)
                time.sleep(0.5)  # Be respectful
            
            if not matches:
                return None
            
            best_match = self._find_best_bbref_match(matches, card_data)
            if not best_match:
                return None
            
            confidence = self._calculate_bbref_confidence(best_match, card_data)
            
            return VerificationResult(
                source="baseball_reference",
                confidence=confidence,
                matched_data=best_match,
                query_used=query,
                raw_results=matches
            )
            
        except Exception as e:
            print(f"Baseball Reference verification error: {e}")
            return None
    
    def _verify_with_sports_reference(self, query: str, card_data: Dict) -> Optional[VerificationResult]:
        """Verify using Sports Reference (covers multiple sports)"""
        try:
            sport = card_data.get('sport', 'baseball').lower()
            
            # Map sports to Sports Reference sites
            sport_sites = {
                'baseball': 'baseball-reference.com',
                'basketball': 'basketball-reference.com',
                'football': 'pro-football-reference.com',
                'hockey': 'hockey-reference.com'
            }
            
            site = sport_sites.get(sport, 'baseball-reference.com')
            
            # For non-baseball, try a basic search
            if sport != 'baseball':
                search_url = f"https://www.{site}/search/search.fcgi"
                params = {'search': query}
                
                response = self.session.get(search_url, params=params)
                response.raise_for_status()
                
                # Basic parsing for player verification
                soup = BeautifulSoup(response.text, 'html.parser')
                player_links = soup.find_all('a', href=re.compile(r'/players/'))
                
                if player_links:
                    return VerificationResult(
                        source=f"sports_reference_{sport}",
                        confidence=0.6,  # Lower confidence for basic match
                        matched_data={'found': True, 'player_links': len(player_links)},
                        query_used=query,
                        raw_results=[]
                    )
            
            return None
            
        except Exception as e:
            print(f"Sports Reference verification error: {e}")
            return None
    
    def _get_baseball_reference_player_info(self, player_url: str) -> Optional[Dict]:
        """Get detailed player info from Baseball Reference"""
        try:
            response = self.session.get(player_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract player info
            info = {'url': player_url}
            
            # Player name
            name_elem = soup.find('h1', {'itemprop': 'name'})
            if name_elem:
                info['name'] = name_elem.get_text(strip=True)
            
            # Career span
            career_span = soup.find('p', string=re.compile(r'.*\d{4}-\d{4}.*'))
            if career_span:
                years = re.findall(r'\d{4}', career_span.get_text())
                if len(years) >= 2:
                    info['career_start'] = years[0]
                    info['career_end'] = years[1]
            
            # Teams played for
            teams_section = soup.find('div', {'id': 'meta'})
            if teams_section:
                team_links = teams_section.find_all('a', href=re.compile(r'/teams/'))
                teams = [link.get_text(strip=True) for link in team_links]
                info['teams'] = teams
            
            # Position
            position_elem = soup.find('p', string=re.compile(r'Position:'))
            if position_elem:
                position_text = position_elem.get_text()
                position_match = re.search(r'Position:\s*([^,\n]+)', position_text)
                if position_match:
                    info['position'] = position_match.group(1).strip()
            
            return info
            
        except Exception as e:
            print(f"Error getting player info from {player_url}: {e}")
            return None
    
    def _find_best_tcdb_match(self, results: List[Dict], card_data: Dict) -> Optional[Dict]:
        """Find best TCDB match for card data"""
        if not results:
            return None
        
        best_match = None
        best_score = 0
        
        for result in results:
            score = self._score_tcdb_match(result, card_data)
            if score > best_score:
                best_score = score
                best_match = result
        
        return best_match if best_score > 0.3 else None
    
    def _find_best_bbref_match(self, results: List[Dict], card_data: Dict) -> Optional[Dict]:
        """Find best Baseball Reference match for card data"""
        if not results:
            return None
        
        best_match = None
        best_score = 0
        
        for result in results:
            score = self._score_bbref_match(result, card_data)
            if score > best_score:
                best_score = score
                best_match = result
        
        return best_match if best_score > 0.3 else None
    
    def _score_tcdb_match(self, tcdb_result: Dict, card_data: Dict) -> float:
        """Score how well TCDB result matches card data"""
        score = 0.0
        checks = 0
        
        # Name matching
        card_name = str(card_data.get('name', '')).lower().strip()
        tcdb_title = str(tcdb_result.get('title', '')).lower().strip()
        
        if card_name and tcdb_title:
            checks += 1
            if card_name in tcdb_title or any(word in tcdb_title for word in card_name.split() if len(word) > 2):
                score += 0.4
        
        # Year matching
        card_year = str(card_data.get('copyright_year', '')).strip()
        tcdb_year = str(tcdb_result.get('year', '')).strip()
        
        if card_year and tcdb_year:
            checks += 1
            try:
                if abs(int(card_year) - int(tcdb_year)) <= 1:  # Allow 1 year difference
                    score += 0.3
            except ValueError:
                pass
        
        # Team matching
        card_team = str(card_data.get('team', '')).lower().strip()
        tcdb_team = str(tcdb_result.get('team', '')).lower().strip()
        
        if card_team and tcdb_team:
            checks += 1
            if card_team in tcdb_team or tcdb_team in card_team:
                score += 0.3
        
        return score / max(checks, 1) if checks > 0 else 0.0
    
    def _score_bbref_match(self, bbref_result: Dict, card_data: Dict) -> float:
        """Score how well Baseball Reference result matches card data"""
        score = 0.0
        checks = 0
        
        # Name matching
        card_name = str(card_data.get('name', '')).lower().strip()
        bbref_name = str(bbref_result.get('name', '')).lower().strip()
        
        if card_name and bbref_name:
            checks += 1
            if card_name in bbref_name or bbref_name in card_name:
                score += 0.5
        
        # Year matching (check if card year falls within career)
        card_year = card_data.get('copyright_year')
        career_start = bbref_result.get('career_start')
        career_end = bbref_result.get('career_end')
        
        if card_year and career_start and career_end:
            checks += 1
            try:
                card_year_int = int(str(card_year))
                start_year = int(career_start)
                end_year = int(career_end)
                
                if start_year <= card_year_int <= end_year:
                    score += 0.3
            except ValueError:
                pass
        
        # Team matching
        card_team = str(card_data.get('team', '')).lower().strip()
        bbref_teams = [str(team).lower().strip() for team in bbref_result.get('teams', [])]
        
        if card_team and bbref_teams:
            checks += 1
            if any(card_team in team or team in card_team for team in bbref_teams):
                score += 0.2
        
        return score / max(checks, 1) if checks > 0 else 0.0
    
    def _calculate_tcdb_confidence(self, match: Dict, card_data: Dict) -> float:
        """Calculate confidence in TCDB match"""
        return self._score_tcdb_match(match, card_data)
    
    def _calculate_bbref_confidence(self, match: Dict, card_data: Dict) -> float:
        """Calculate confidence in Baseball Reference match"""
        return self._score_bbref_match(match, card_data)
    
    def _combine_verification_results(self, card_data: Dict, results: List[VerificationResult]) -> Dict[str, Any]:
        """Combine verification results to enhance card data"""
        enhanced_card = card_data.copy()
        
        if not results:
            enhanced_card['_verification'] = {
                'verified': False,
                'sources': [],
                'confidence': 0.0,
                'notes': 'No verification sources found matches'
            }
            return enhanced_card
        
        # Sort results by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        
        # Take the highest confidence result as primary
        primary_result = results[0]
        
        verification_data = {
            'verified': primary_result.confidence > 0.5,
            'primary_source': primary_result.source,
            'primary_confidence': primary_result.confidence,
            'sources': [],
            'enhanced_fields': []
        }
        
        # Add all results
        for result in results:
            verification_data['sources'].append({
                'source': result.source,
                'confidence': result.confidence,
                'query': result.query_used,
                'matched_data': result.matched_data
            })
        
        # Apply enhancements from highest confidence sources
        if primary_result.confidence > 0.6:
            enhanced_card = self._apply_verification_enhancements(
                enhanced_card, primary_result, verification_data['enhanced_fields']
            )
        
        # Calculate overall verification confidence
        if len(results) > 1:
            # Boost confidence if multiple sources agree
            avg_confidence = sum(r.confidence for r in results) / len(results)
            verification_data['overall_confidence'] = min(
                primary_result.confidence + (avg_confidence * 0.2), 1.0
            )
        else:
            verification_data['overall_confidence'] = primary_result.confidence
        
        enhanced_card['_verification'] = verification_data
        
        return enhanced_card
    
    def _apply_verification_enhancements(self, card_data: Dict, result: VerificationResult, enhanced_fields: List) -> Dict:
        """Apply enhancements from verification results"""
        enhanced = card_data.copy()
        matched_data = result.matched_data
        
        if result.source == 'tcdb':
            # Enhance from TCDB data
            if not enhanced.get('team') or enhanced.get('team') == 'unknown':
                tcdb_team = matched_data.get('team')
                if tcdb_team:
                    enhanced['team'] = tcdb_team
                    enhanced_fields.append('team')
            
            if not enhanced.get('card_set') or enhanced.get('card_set') == 'unknown':
                tcdb_set = matched_data.get('set')
                if tcdb_set:
                    enhanced['card_set'] = tcdb_set
                    enhanced_fields.append('card_set')
        
        elif result.source == 'baseball_reference':
            # Enhance from Baseball Reference data
            if matched_data.get('position'):
                enhanced['_player_position'] = matched_data['position']
                enhanced_fields.append('player_position')
            
            if matched_data.get('career_start') and matched_data.get('career_end'):
                enhanced['_career_span'] = f"{matched_data['career_start']}-{matched_data['career_end']}"
                enhanced_fields.append('career_span')
        
        return enhanced
    
    def close(self):
        """Close HTTP session"""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def verify_cards_online(cards: List[Dict]) -> List[Dict]:
    """
    Convenience function to verify multiple cards online
    """
    verified_cards = []
    
    with OnlineVerifier() as verifier:
        for i, card in enumerate(cards):
            print(f"Verifying card {i+1}/{len(cards)}: {card.get('name', 'unknown')}")
            
            try:
                verified_card = verifier.verify_card_comprehensive(card)
                verified_cards.append(verified_card)
                
                # Add delay between cards to be respectful
                if i < len(cards) - 1:
                    time.sleep(1)
                    
            except Exception as e:
                print(f"Verification failed for card {i+1}: {e}")
                card['_verification'] = {
                    'verified': False,
                    'error': str(e),
                    'sources': []
                }
                verified_cards.append(card)
    
    return verified_cards


if __name__ == "__main__":
    # Test the verifier
    test_card = {
        'name': 'Nolan Ryan',
        'team': 'California Angels',
        'copyright_year': '1979',
        'sport': 'baseball',
        'brand': 'topps'
    }
    
    print("Testing online verifier...")
    
    with OnlineVerifier() as verifier:
        result = verifier.verify_card_comprehensive(test_card)
        
        print(f"Verification result for {test_card['name']}:")
        print(f"Verified: {result.get('_verification', {}).get('verified', False)}")
        print(f"Confidence: {result.get('_verification', {}).get('overall_confidence', 0)}")
        print(f"Sources: {len(result.get('_verification', {}).get('sources', []))}")