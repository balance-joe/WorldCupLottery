"""Sporttery API configuration."""

# ── API ──────────────────────────────────────────────────────────────────────

BASE_URL = "https://webapi.sporttery.cn/gateway"

API_MATCH_LIST = f"{BASE_URL}/uniform/fb/getMatchDataPageListV1.qry"
API_RESULT_LIST = API_MATCH_LIST
API_FIXED_BONUS = f"{BASE_URL}/uniform/football/getFixedBonusV1.qry"

SPORTTERY_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "identity",
    "origin": "https://m.sporttery.cn",
    "referer": "https://m.sporttery.cn/",
    "user-agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.5 Mobile/15E148 Safari/604.1"
    ),
}

REQUEST_TIMEOUT = 15  # seconds

# ── Play types ───────────────────────────────────────────────────────────────

PLAY_TYPES = {
    "had": "胜平负",
    "hhad": "让球胜平负",
    "ttg": "总进球",
}
