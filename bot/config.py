"""감시 대상과 지표 파라미터.

값은 TradingView 인디케이터의 입력값(Settings)과 반드시 같아야 한다.
차트에서 파라미터를 바꿨다면 여기도 같이 바꿔야 신호가 일치한다.
"""

# --- 감시 대상 ---------------------------------------------------------------
# Bitget USDT-M 무기한 선물 심볼.
# 현물을 보려면 PRODUCT_TYPE 을 None 으로 두고 SPOT_GRANULARITY 를 쓴다(bitget.py 참조).
SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
]

PRODUCT_TYPE = "usdt-futures"
GRANULARITY = "1H"          # 선물은 대문자 H, 현물은 소문자 h
BAR_SECONDS = 3600

# 지표 워밍업용으로 넉넉히 받는다. EMA26 + 다이버전스 lookback 을 고려해도 충분하다.
CANDLE_LIMIT = 300


# --- 지표 파라미터 (Pine 스크립트 입력값과 동일) -------------------------------
SHORT_LEN = 9               # Short MA Length
LONG_LEN = 21               # Long MA Length
STOCH_LEN = 14              # Stoch Length
STOCH_OB = 80               # Stoch Overbought Level

# 과매수 필터를 "직전 몇 봉 안에 과매수였는가"로 볼지.
#
# 1 = 원본 Pine 과 완전히 동일 (교차가 일어난 그 봉에서만 k > 80 인지 확인).
#
# 주의: 1로 두면 이 필터는 사실상 죽어 있다. 실측 결과 BTC/ETH/SOL 1시간봉
# 각 1000봉(데드크로스 합계 71회)에서 교차 봉의 %K 가 80을 넘은 경우가 0회였고,
# 최댓값이 57.1이었다. EMA 단기선이 장기선을 아래로 뚫으려면 하락이 누적돼야 하는데,
# 그 시점의 종가는 14봉 레인지의 바닥 근처다. 두 조건은 같은 봉에서 성립하기 어렵다.
# 결과적으로 원본의 `shortFilter = stochOB or macdBearDiv` 는 macdBearDiv 하나로 축약된다.
#
# "과매수까지 올랐다가 꺾였을 때 숏"이 원래 의도라면 6~10 정도로 올린다.
# 다만 값을 바꾸면 TradingView 차트의 화살표와 봇 신호가 더 이상 일치하지 않는다.
STOCH_OB_LOOKBACK = 1

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 원본 코드의 다이버전스 근사에 쓰이는 5봉 창.
# ta.highest(close, 5) 를 5봉 전 값과 비교하는 방식이라 창 크기와 시프트가 같다.
DIV_LOOKBACK = 5


# --- 운영 --------------------------------------------------------------------
# 크론이 밀리거나 건너뛰었을 때 소급해서 보낼 최대 봉 수.
# 이보다 더 오래 멈춰 있었다면 개별 전송 대신 요약 1건만 보낸다.
MAX_BACKLOG_BARS = 24

STATE_FILE = "state.json"
