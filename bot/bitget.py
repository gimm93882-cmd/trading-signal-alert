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

    def is_closed(self, now_ms: int) -> bool:
        return self.close_time <= now_ms


class BitgetError(RuntimeError):
    pass


def fetch_candles(symbol, granularity, product_type, limit, now_ms=None,
                  include_forming=False):
    """캔들을 오래된 것부터 정렬해 돌려준다.

    Bitget 응답의 마지막 원소는 **아직 진행 중인 미완성 봉**이다.
    기본값(include_forming=False)은 이걸 잘라내고 마감된 봉만 준다.
    확정 신호는 반드시 이쪽을 써야 리페인팅이 없다.

    include_forming=True 면 미완성 봉까지 포함한다. 트레이딩뷰 화면에
    **지금 보이는 것과 같은 상태**를 재현하기 위한 것으로, 잠정 신호 판정에만 쓴다.
    이 봉의 신호는 봉이 닫히면서 사라질 수 있다는 전제로 다뤄야 한다.
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
        if include_forming or c.close_time <= now_ms:
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
