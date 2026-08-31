"""백테스트용 장기 캔들 확보.

봇 본체(bot/bitget.py)는 최근 300봉만 있으면 되지만, 백테스트는 수년치가 필요하다.
Bitget 은 엔드포인트가 둘로 나뉘어 있어 이어 붙여야 한다.

  /candles          최근 1,000봉까지. limit 1000 가능. 그보다 과거는 빈 배열.
  /history-candles  과거 구간. limit 이 200 이 상한이라 여러 번 나눠 받는다.

받은 결과는 data/ 에 캐시한다. 같은 구간을 다시 받지 않기 위한 것으로,
--refresh 로 갱신한다.
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE = "https://api.bitget.com/api/v2/mix/market"
TIMEOUT = 25
RETRIES = 4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")


def _get(path, symbol, granularity, limit, end=None):
    url = ("%s/%s?symbol=%s&granularity=%s&productType=usdt-futures&limit=%d"
           % (BASE, path, symbol, granularity, limit))
    if end:
        url += "&endTime=%d" % end

    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "backtest/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("code") == "00000":
                return payload.get("data") or []
            last = payload.get("msg")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as err:
            last = err
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError("Bitget 요청 실패: %s" % last)


def load(symbol="BTCUSDT", granularity="1H", max_bars=20000, refresh=False, quiet=False):
    """오래된 것부터 정렬된 원시 캔들 행을 돌려준다. 미완성 봉은 잘라낸다."""
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR)
    cache = os.path.join(DATA_DIR, "%s_%s.json" % (symbol, granularity.lower()))

    if os.path.exists(cache) and not refresh:
        with open(cache, "r") as f:
            rows = json.load(f)
        if len(rows) >= max_bars * 0.9:
            return rows

    rows = {}
    for r in _get("candles", symbol, granularity, 1000):
        rows[int(r[0])] = r
    if not quiet:
        print("  최근 %d봉" % len(rows))

    end = min(rows)
    while len(rows) < max_bars:
        chunk = _get("history-candles", symbol, granularity, 200, end)
        if not chunk:
            break
        before = len(rows)
        for r in chunk:
            rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in chunk)
        if len(rows) == before or oldest >= end:
            break
        end = oldest
        if not quiet and len(rows) % 2000 < 200:
            print("  %d봉 (%s 까지)" % (len(rows), time.strftime("%Y-%m-%d", time.localtime(oldest / 1000))))
        time.sleep(0.25)

    out = [rows[k] for k in sorted(rows)]
    now = int(time.time() * 1000)
    step = _granularity_ms(granularity)
    out = [r for r in out if int(r[0]) + step <= now]      # 미완성 봉 제거

    with open(cache, "w") as f:
        json.dump(out, f)
    return out


def _granularity_ms(g):
    unit = g[-1].lower()
    n = int(g[:-1])
    return n * {"m": 60, "h": 3600, "d": 86400}[unit] * 1000
