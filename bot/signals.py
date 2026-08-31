"""원본 Pine 로직을 그대로 옮기되, COVER 버그만 고친 신호 판정.

원본:
    shortExit = shortEntry[1] and buySignal

숏 진입 **바로 다음 봉**에 EMA 가 다시 위로 교차해야만 성립한다.
EMA 가 한 봉 만에 아래로 뚫고 다시 위로 뚫는 일은 거의 없어서 COVER 가 사실상 안 뜬다.
여기서는 상태 변수(in_short)로 바꿔, 숏 진입 이후 언제든 골든크로스가 나오면 청산 신호를 낸다.
"""

from dataclasses import dataclass
from typing import List, Optional

from . import config, indicators
from .bitget import Candle

BUY = "BUY"
SELL = "SELL"
SHORT = "SHORT"
COVER = "COVER"


@dataclass
class Signal:
    kind: str
    bar_time: int              # 봉 시작 시각 (ms)
    close: float
    ema_short: float
    ema_long: float
    stoch_k: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    reason: str = ""           # SHORT 일 때 어떤 필터가 걸렸는지
    bar_seconds: int = 3600    # 이 신호가 나온 봉의 길이
    tf: str = ""               # 표시용 타임프레임 이름 ("1시간봉")


def detect(candles: List[Candle], tf: str = "") -> List[Signal]:
    """확정된 캔들 목록에서 발생한 모든 신호를 시간순으로 돌려준다."""
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    ema_s = indicators.ema(closes, config.SHORT_LEN)
    ema_l = indicators.ema(closes, config.LONG_LEN)
    k = indicators.stoch(closes, highs, lows, config.STOCH_LEN)
    macd_line, macd_sig = indicators.macd(
        closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )

    # 원본의 다이버전스 근사: 5봉 창의 고점을 5봉 전 같은 창과 비교한다.
    #   priceHighCond = ta.highest(close, 5) > ta.highest(close[5], 5)
    #   macdLowCond   = ta.highest(macd, 5)  < ta.highest(macd[5], 5)
    lb = config.DIV_LOOKBACK
    hh_close = indicators.highest(closes, lb)
    hh_macd = indicators.highest(macd_line, lb)

    # 과매수 필터. STOCH_OB_LOOKBACK 이 1이면 교차 봉만 보므로 원본과 동일하다.
    # (그 설정에서 이 필터가 왜 사실상 죽어 있는지는 config.py 주석 참조)
    k_high = indicators.highest(k, config.STOCH_OB_LOOKBACK)

    out: List[Signal] = []
    in_short = False

    for i in range(len(candles)):
        buy = indicators.crossover(ema_s, ema_l, i)
        sell = indicators.crossunder(ema_s, ema_l, i)

        if not (buy or sell):
            continue

        peak_k = k_high[i]
        stoch_ob = peak_k is not None and peak_k > config.STOCH_OB
        bear_div = _bear_div(hh_close, hh_macd, i, lb)

        def make(kind, reason=""):
            return Signal(
                kind=kind,
                bar_time=candles[i].time,
                close=closes[i],
                ema_short=ema_s[i],
                ema_long=ema_l[i],
                stoch_k=k[i],
                macd=macd_line[i],
                macd_signal=macd_sig[i],
                reason=reason,
                bar_seconds=candles[i].bar_seconds,
                tf=tf,
            )

        if buy:
            # 숏 청산이 먼저다. 포지션을 닫고 나서 롱을 잡는 순서.
            if in_short:
                out.append(make(COVER))
                in_short = False
            out.append(make(BUY))

        elif sell:
            out.append(make(SELL))
            if stoch_ob or bear_div:
                reasons = []
                if stoch_ob:
                    window = (
                        "" if config.STOCH_OB_LOOKBACK == 1
                        else " · 최근 %d봉 최고" % config.STOCH_OB_LOOKBACK
                    )
                    reasons.append(
                        "Stoch 과매수(%.1f > %d%s)"
                        % (peak_k, config.STOCH_OB, window)
                    )
                if bear_div:
                    reasons.append("MACD 약세 다이버전스")
                out.append(make(SHORT, " + ".join(reasons)))
                in_short = True

    return out


def _bear_div(hh_close, hh_macd, i, lb):
    """가격은 고점을 높였는데 MACD 는 못 따라온 구간인지."""
    j = i - lb
    if j < 0:
        return False
    if hh_close[i] is None or hh_close[j] is None:
        return False
    if hh_macd[i] is None or hh_macd[j] is None:
        return False
    return hh_close[i] > hh_close[j] and hh_macd[i] < hh_macd[j]
