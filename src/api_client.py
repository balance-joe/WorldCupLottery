"""竞彩 API 客户端，返回原始 JSON 字典。"""

from __future__ import annotations

import time

import requests

from src.config import (
    API_FUTURE_MATCHES,
    API_FIXED_BONUS,
    API_INJURY_SUSPENSION,
    API_MATCH_LIST,
    API_MATCH_FEATURE,
    API_MATCH_HEAD,
    API_MATCH_PLAYER,
    API_MATCH_RESULT,
    API_MATCH_TABLES,
    API_RESULT_LIST,
    API_RESULT_HISTORY,
    API_SAME_ODDS,
    REQUEST_TIMEOUT,
    SPORTTERY_HEADERS,
    API_TEAM_POOLDIV_STATS,
)

# 重试默认参数
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # 秒；每次重试翻倍：1s、2s、4s

DETAIL_APIS = {
    "matchHead": API_MATCH_HEAD,
    "matchFeature": API_MATCH_FEATURE,
    "matchResult": API_MATCH_RESULT,
    "resultHistory": API_RESULT_HISTORY,
    "futureMatches": API_FUTURE_MATCHES,
    "matchTables": API_MATCH_TABLES,
    "matchPlayer": API_MATCH_PLAYER,
    "injurySuspension": API_INJURY_SUSPENSION,
    "sameOdds": API_SAME_ODDS,
    "teamPooldivStats": API_TEAM_POOLDIV_STATS,
}


def _get(
    url: str,
    params: dict | None = None,
    *,
    max_retries: int = _MAX_RETRIES,
) -> tuple[dict | None, str | None]:
    """带指数退避重试的 GET 请求。返回 (data, error_msg)。

    遇到瞬时故障（网络异常 / HTTP 5xx / 超时）时，最多重试 *max_retries* 次，
    每次间隔指数递增。不可重试的错误（HTTP 4xx、API 层 success=false）立即失败。
    """
    last_err: str | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=SPORTTERY_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            # 遇到 5xx 服务端错误时重试
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < max_retries - 1:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                return None, last_err

            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                return None, f"API error: {data.get('errorMessage', 'unknown')}"
            return data, None

        except requests.ConnectionError as e:
            last_err = f"ConnectionError: {e}"
        except requests.Timeout as e:
            last_err = f"Timeout: {e}"
        except requests.HTTPError as e:
            # 4xx —— 非瞬时错误，立即失败
            return None, str(e)
        except requests.RequestException as e:
            return None, str(e)
        except ValueError as e:
            # JSONDecodeError —— 响应体格式错误
            return None, f"JSON decode error: {e}"

        if attempt < max_retries - 1:
            time.sleep(_BACKOFF_BASE * (2 ** attempt))

    return None, last_err or "unknown error"


def fetch_match_list() -> tuple[dict | None, str | None]:
    """获取关注赛事列表。"""
    return _get(API_MATCH_LIST, params={"method": "concern"})


def fetch_fixed_bonus(match_id: str | int) -> tuple[dict | None, str | None]:
    """获取单场比赛的完整 SP 固定奖金。"""
    return _get(API_FIXED_BONUS, params={"clientCode": "3001", "matchId": str(match_id)})


def fetch_result_list(
    *,
    page_size: int = 20,
    page_no: int | None = None,
    match_date: str | None = None,
) -> tuple[dict | None, str | None]:
    """从足球数据结果页获取赛果列表。"""
    params = {"method": "result", "pageSize": str(page_size)}
    if page_no is not None:
        params["pageNo"] = str(page_no)
    if match_date:
        params["matchDate"] = match_date
    return _get(API_RESULT_LIST, params=params)


def fetch_detail_api(
    source_name: str,
    match_id: str | int,
    *,
    extra_params: dict | None = None,
) -> tuple[dict | None, str | None]:
    """根据 source_name 获取一个足球详情接口。"""
    url = DETAIL_APIS.get(source_name)
    if not url:
        return None, f"unsupported detail api: {source_name}"
    params = {"matchId": str(match_id)}
    if extra_params:
        params.update(extra_params)
    return _get(url, params=params)


def fetch_match_detail_bundle(
    match_id: str | int,
    *,
    sources: tuple[str, ...] | list[str] | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """批量获取多个足球详情接口。

    返回 `(payloads, errors)`。
    """
    selected = tuple(sources) if sources else tuple(DETAIL_APIS.keys())
    payloads: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for source_name in selected:
        data, err = fetch_detail_api(source_name, match_id)
        if err:
            errors[source_name] = err
        elif data is not None:
            payloads[source_name] = data
    return payloads, errors
