"""Bitget 공개 캔들 API 클라이언트. API 키가 필요 없다.

문서: https://www.bitget.com/api-doc/contract/market/Get-Candle-Data
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List

BASE = "https://api.bitget.com"
TIMEOUT = 15
RETRIES = 3
MAX_LIMIT = 1000      # Bitget 이 한 번에 돌려주는 캔들 상한


@dataclass
class Candle:
    time: int      # 봉 시작 시각 (ms, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def close_time(self) -> int:
        """봉이 마감되는 시각 (ms). 1시간봉이면 시작 + 1시간."""
        return self.time + 3600 * 1000


class BitgetError(RuntimeError):
    pass


def fetch_candles(symbol, granularity, product_type, limit, now_ms=None):
    """확정된(마감된) 캔들만 오래된 것부터 정렬해 돌려준다.

    Bitget 응답의 마지막 원소는 **아직 진행 중인 미완성 봉**이다.
    이걸 그대로 쓰면 봉이 마감되기 전 값으로 신호가 떴다가 사라지는
    리페인팅이 발생한다. 마감 시각이 지난 봉만 남기는 것이 이 함수의 핵심이다.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))   # Bitget 상한

    url = (
        BASE + "/api/v2/mix/market/candles"
        "?symbol=" + symbol
        + "&granularity=" + granularity
        + "&productType=" + product_type
        + "&limit=" + str(limit)
    )

    payload = _get_json(url)
    if payload.get("code") != "00000":
        raise BitgetError(
            "Bitget 응답 오류 (" + symbol + "): "
            + str(payload.get("code")) + " " + str(payload.get("msg"))
        )

    rows = payload.get("data") or []
    if not rows:
        raise BitgetError("캔들 데이터가 비어 있음: " + symbol)

    if now_ms is None:
        now_ms = int(time.time() * 1000)

    candles: List[Candle] = []
    for row in rows:
        c = Candle(
            time=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
        )
        if c.close_time <= now_ms:      # 마감된 봉만
            candles.append(c)

    candles.sort(key=lambda c: c.time)
    return candles


def _get_json(url):
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "trend-ribbon-alert/1.0"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as err:
            last_err = err
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)      # 1s, 2s
    raise BitgetError("Bitget 요청 실패: " + str(last_err))
