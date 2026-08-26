"""Pine Script 내장 함수와 수치가 일치하는 지표 계산.

이 모듈의 목적은 단 하나, TradingView 차트에 찍히는 값과 같은 숫자를 내는 것이다.
특히 ema() 의 SMA 시딩은 바꾸면 안 된다. 첫 값을 그대로 시드로 쓰는 흔한 구현은
TradingView 값과 어긋나고, 그 오차가 EMA 교차 시점을 한두 봉씩 밀어버린다.

워밍업이 끝나지 않은 구간은 None(= Pine 의 na)으로 둔다.
"""

from typing import List, Optional

Series = List[Optional[float]]


def ema(values: List[float], length: int) -> Series:
    """Pine `ta.ema`.

    Pine 정의: ema = na(ema[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*ema[1]
    즉 index length-1 에서 앞 length 개의 단순평균으로 시작한다.
    """
    out: Series = [None] * len(values)
    if len(values) < length:
        return out

    alpha = 2.0 / (length + 1)
    prev = sum(values[:length]) / float(length)
    out[length - 1] = prev

    for i in range(length, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def highest(values: Series, length: int) -> Series:
    """Pine `ta.highest`. index i 에서 values[i-length+1 .. i] 의 최댓값."""
    return _rolling(values, length, max)


def lowest(values: Series, length: int) -> Series:
    """Pine `ta.lowest`. index i 에서 values[i-length+1 .. i] 의 최솟값."""
    return _rolling(values, length, min)


def _rolling(values: Series, length: int, fn) -> Series:
    out: Series = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = fn(window)
    return out


def stoch(
    close: List[float], high: List[float], low: List[float], length: int
) -> Series:
    """Pine `ta.stoch(source, high, low, length)`.

    평활이 없는 raw %K 다. TradingView 의 Stochastic 인디케이터가 기본으로 보여주는
    3봉 평활된 %K 와는 다르므로, 차트와 대조할 때는 데이터 윈도우의 원본 값을 봐야 한다.
    """
    hh = highest(high, length)
    ll = lowest(low, length)

    out: Series = [None] * len(close)
    for i in range(len(close)):
        if hh[i] is None or ll[i] is None:
            continue
        rng = hh[i] - ll[i]
        if rng == 0:
            # 창 전체가 완전 횡보. Pine 은 0/0 → na 를 내므로 동일하게 둔다.
            continue
        out[i] = 100.0 * (close[i] - ll[i]) / rng
    return out


def macd(
    close: List[float], fast: int, slow: int, signal_len: int
):
    """원본 Pine 코드와 같은 방식의 MACD.

    내장 ta.macd 가 아니라 EMA 두 개를 직접 뺀 형태다(원본이 그렇게 짜여 있다).
    결과는 같지만 계산 순서를 맞춰 둔다.

    반환: (macd_line, signal_line)
    """
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)

    line: Series = [None] * len(close)
    for i in range(len(close)):
        if fast_ema[i] is None or slow_ema[i] is None:
            continue
        line[i] = fast_ema[i] - slow_ema[i]

    # signal 은 macd_line 의 EMA 다. macd_line 앞쪽 None 구간을 건너뛰고 계산한 뒤
    # 원래 위치로 다시 정렬한다.
    first = next((i for i, v in enumerate(line) if v is not None), None)
    signal: Series = [None] * len(close)
    if first is not None:
        dense = [v for v in line[first:] if v is not None]
        dense_signal = ema(dense, signal_len)
        for offset, v in enumerate(dense_signal):
            signal[first + offset] = v

    return line, signal


def crossover(a: Series, b: Series, i: int) -> bool:
    """Pine `ta.crossover(a, b)` 를 index i 에서 평가."""
    if i == 0:
        return False
    if a[i] is None or b[i] is None or a[i - 1] is None or b[i - 1] is None:
        return False
    return a[i - 1] <= b[i - 1] and a[i] > b[i]


def crossunder(a: Series, b: Series, i: int) -> bool:
    """Pine `ta.crossunder(a, b)` 를 index i 에서 평가."""
    if i == 0:
        return False
    if a[i] is None or b[i] is None or a[i - 1] is None or b[i - 1] is None:
        return False
    return a[i - 1] >= b[i - 1] and a[i] < b[i]
