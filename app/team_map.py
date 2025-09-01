from __future__ import annotations

from typing import Optional


_MLB = {
    # historical + common names → canonical "city team"
    "indians": "cleveland indians",
    "guardians": "cleveland guardians",
    "rangers": "texas rangers",
    "twins": "minnesota twins",
    "athletics": "oakland athletics",
    "a's": "oakland athletics",
    "angels": "california angels",
    "california angels": "california angels",
    "los angeles angels": "los angeles angels",
    "royals": "kansas city royals",
    "yankees": "new york yankees",
    "mets": "new york mets",
    "dodgers": "los angeles dodgers",
    "giants": "san francisco giants",
    "padres": "san diego padres",
    "phillies": "philadelphia phillies",
    "pirates": "pittsburgh pirates",
    "cardinals": "st. louis cardinals",
    "cubs": "chicago cubs",
    "white sox": "chicago white sox",
    "red sox": "boston red sox",
    "brewers": "milwaukee brewers",
    "braves": "atlanta braves",
    "reds": "cincinnati reds",
    "orioles": "baltimore orioles",
    "mariners": "seattle mariners",
    "blue jays": "toronto blue jays",
    "expos": "montreal expos",
    "nationals": "washington nationals",
    "rockies": "colorado rockies",
    "diamondbacks": "arizona diamondbacks",
    "tigers": "detroit tigers",
    "marlins": "miami marlins",
    "rays": "tampa bay rays",
}

_NBA = {
    "lakers": "los angeles lakers",
    "clippers": "los angeles clippers",
    "celtics": "boston celtics",
    "knicks": "new york knicks",
    "bulls": "chicago bulls",
    "warriors": "golden state warriors",
}

_NFL = {
    "patriots": "new england patriots",
    "giants": "new york giants",
    "jets": "new york jets",
    "cowboys": "dallas cowboys",
    "packers": "green bay packers",
    "browns": "cleveland browns",
}

_NHL = {
    "canadiens": "montreal canadiens",
    "maple leafs": "toronto maple leafs",
    "red wings": "detroit red wings",
    "bruins": "boston bruins",
    "rangers": "new york rangers",
}


def canonicalize_team(team: Optional[str], sport: Optional[str] = None) -> Optional[str]:
    if not team or not isinstance(team, str):
        return team
    t = team.strip().lower()
    # if already looks like city + team (contains space and not just a nickname), keep it
    if any(ch.isspace() for ch in t) and t not in {"st.louis", "st.louis cardinals", "st. louis"}:
        # normalize St. Louis
        t = t.replace("st.louis", "st. louis")
        return t

    tables = []
    sport = (sport or "").strip().lower()
    if sport == "baseball":
        tables.append(_MLB)
    elif sport == "basketball":
        tables.append(_NBA)
    elif sport == "football":
        tables.append(_NFL)
    elif sport == "hockey":
        tables.append(_NHL)
    else:
        tables.extend([_MLB, _NBA, _NFL, _NHL])

    for tbl in tables:
        if t in tbl:
            return tbl[t]
    return t

