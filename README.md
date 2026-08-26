# 1시간봉 신호 → 디스코드 알림

TradingView 인디케이터 `Trend Ribbon + Buy/Sell + Short Cycle` 의 신호를
1시간봉 기준으로 자동 감시해서 디스코드로 보내는 봇입니다.

**월 비용 0원, 서버 0대.** 맥을 꺼놔도 돌아갑니다.

---

## 왜 TradingView 알림을 안 쓰나

쓸 수 없기 때문입니다. TradingView 무료(Basic) 플랜은

| | 무료 | Essential (월 $14.95~) |
|---|---|---|
| 가격 알림 | 3개 | 20개 |
| **기술적 알림 (인디케이터 기반)** | **0개** | 20개 |
| 웹훅 | 없음 | 있음 |

Pine 스크립트로 만든 알림은 전부 "기술적 알림"이라 **무료 플랜에서는 개수가 0**입니다.
그래서 TradingView를 거치지 않고, **비트겟 공개 API에서 캔들을 직접 받아
같은 로직을 다시 계산**합니다. API 키도 필요 없습니다.

---

## 세팅 (약 10분)

### 1. 디스코드 웹훅 만들기

1. 디스코드에서 알림 받을 서버 → 채널 우클릭 → **채널 편집**
2. **연동** → **웹후크** → **새 웹후크** → **웹후크 URL 복사**

이 URL을 아는 사람은 누구나 그 채널에 글을 쓸 수 있습니다. **어디에도 공개하지 마세요.**

핸드폰 푸시를 받으려면 디스코드 모바일 앱에서 해당 채널의 알림을
**모든 메시지**로 켜두면 됩니다.

### 2. 로컬에서 먼저 확인

```bash
cd "/Users/kinampark/Desktop/LCI 트레이딩"
python3 -m unittest discover -s tests
```

```bash
python3 -m bot.main --backfill 200 --symbols BTCUSDT
```

최근 200봉에서 발생한 신호가 표로 나옵니다. 전송은 하지 않습니다.

실제로 디스코드에 도착하는지 보려면:

```bash
export DISCORD_WEBHOOK_URL='여기에_웹훅_URL'
python3 -m bot.main
```

> 첫 실행은 **기준점만 잡고 아무것도 보내지 않습니다.** 과거 300봉 신호가
> 한꺼번에 쏟아지는 걸 막기 위해서입니다. 알림은 다음 실행부터 옵니다.

### 3. GitHub에 올리고 자동 실행 걸기

**저장소는 private로 만드세요.** 공개할 이유가 없습니다.

```bash
git init && git add -A && git commit -m "1시간봉 신호 알림 봇"
```

GitHub에서 새 private 저장소를 만든 뒤:

```bash
git remote add origin https://github.com/<계정>/<저장소>.git
git branch -M main && git push -u origin main
```

그다음 GitHub 저장소 페이지에서:

1. **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DISCORD_WEBHOOK_URL`
   - Secret: 1번에서 복사한 URL
2. **Settings → Actions → General → Workflow permissions**
   → **Read and write permissions** 선택 후 저장
   (봇이 `state.json`을 커밋해야 중복 알림이 안 갑니다)
3. **Actions** 탭 → `1H signal alert` → **Run workflow** 로 수동 실행해서 확인

이후로는 매시 정각 직후 자동으로 돕니다.

---

## TradingView 차트에도 적용하기

`pine/trend-ribbon.pine` 을 파인 에디터에 붙여넣고 저장 → **차트에 추가**.

봇이 알림을 담당하므로 차트는 눈으로 확인하는 용도지만,
차트에서 직접 알림을 만들 거라면 (Essential 이상 필요):

> 알림 생성 창에서 **"Once Per Bar Close"** (봉 마감 시 한 번)를 **반드시** 선택하세요.
> 기본값인 "Once Per Bar"로 두면 봉이 완성되기 전에 알림이 울렸다가
> 조건이 풀리면서 신호가 사라지는 **리페인팅**이 발생합니다.

---

## 봇이 차트와 같은 신호를 내는지 확인하는 법

이게 가장 중요한 검증입니다.

1. `python3 -m bot.main --backfill 200 --symbols BTCUSDT` 실행
2. TradingView에서 **BTCUSDT 1시간봉** 차트에 위 Pine 스크립트를 올림
3. 출력된 신호의 **시각과 종류**를 차트 화살표와 하나씩 대조

개수와 타임스탬프가 맞아야 합니다. 어긋난다면 원인은 거의 항상 둘 중 하나입니다.

- 차트의 인디케이터 설정값이 `bot/config.py` 와 다름
- 차트 심볼이 다름 (비트겟 선물 `BITGET:BTCUSDT.P` 기준으로 계산합니다)

---

## 원본 코드에서 고친 것

### 1. COVER 신호가 사실상 안 뜨던 버그

```pinescript
shortExit = shortEntry[1] and buySignal   // 원본
```

숏 진입 **바로 다음 봉**에 골든크로스가 나야만 성립합니다.
EMA가 한 봉 만에 아래로 뚫고 다시 위로 뚫는 일은 거의 없어서 청산 신호가 안 나옵니다.

상태 변수로 바꿔 진입 이후 언제든 골든크로스가 나오면 청산하도록 했습니다.

> 실제 BTCUSDT 1시간봉 검증: `08-23 07:00 SHORT` → `08-23 23:00 COVER`.
> **16시간 간격**이라 원본 로직으로는 나올 수 없던 신호입니다.

### 2. 알림 호출이 하나도 없었음

원본에는 `alert()` 도 `alertcondition()` 도 없어서, **유료 플랜이어도
이 코드로는 알림을 만들 수 없었습니다.** 4종 신호 각각에 대해 추가했습니다.

### 3. 화살표 중복

`sellSignal` 과 `shortEntry` 가 같은 봉에서 빨강·주황 세모를 겹쳐 그렸습니다.
SHORT이 뜨는 봉에서는 `SELL+SHORT` 하나로 표시합니다.

---

## 알아두셔야 할 설계 이슈: 과매수 필터가 작동하지 않습니다

원본의 숏 진입 조건입니다.

```pinescript
shortFilter = stochOB_cond or macdBearDiv
```

**`stochOB_cond` 는 실전에서 한 번도 성립하지 않습니다.**

실측 (BTC / ETH / SOL 1시간봉, 각 1000봉):

| 심볼 | 데드크로스 | %K > 80 인 경우 | 교차 시점 %K 최댓값 |
|---|---|---|---|
| BTCUSDT | 22회 | **0회** | 43.2 |
| ETHUSDT | 29회 | **0회** | 57.1 |
| SOLUSDT | 20회 | **0회** | 55.3 |

구조적인 이유가 있습니다. EMA 단기선이 장기선을 **아래로** 뚫으려면 하락이
누적돼야 하는데, 그 시점의 종가는 이미 14봉 레인지의 **바닥 근처**입니다.
"과매수"와 "데드크로스"는 같은 봉에서 동시에 성립할 수 없습니다.

결과적으로 `shortFilter` 는 `macdBearDiv` 하나로 축약됩니다.

의도하신 게 **"과매수까지 올랐다가 꺾였을 때 숏"** 이라면, 교차 봉 하나가 아니라
**직전 N봉 안에 과매수가 있었는지**를 봐야 합니다. 옵션으로 넣어뒀습니다.

`bot/config.py`:
```python
STOCH_OB_LOOKBACK = 1    # 6~10 으로 올리면 과매수 필터가 살아납니다
```

Pine 쪽은 인디케이터 설정의 `Stoch OB Lookback` 입력값입니다.

**기본값은 1(원본과 완전 동일)로 뒀습니다.** 값을 바꾸면 차트와 봇 신호가
더 이상 일치하지 않아 위의 대조 검증이 안 되기 때문입니다.
먼저 검증을 끝낸 뒤에 바꾸시는 걸 권합니다. **양쪽을 같이** 바꿔야 합니다.

---

## 설정 바꾸기

전부 `bot/config.py` 한 곳에 있습니다.

```python
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]   # 감시할 종목
SHORT_LEN = 9                                  # 단기 EMA
LONG_LEN  = 21                                 # 장기 EMA
STOCH_OB  = 80                                 # 과매수 기준
MAX_BACKLOG_BARS = 24                          # 이보다 오래 멈췄으면 요약 1건만
```

**차트 설정과 반드시 같은 값이어야 합니다.**

---

## 운영 시 알아둘 것

- **크론이 5~15분 밀릴 수 있습니다.** GitHub Actions 공용 큐 사정입니다.
  1시간봉이라 실사용에는 지장이 없습니다.
- **60일간 저장소에 활동이 없으면 크론이 자동 중지됩니다.** 신호가 나면
  `state.json` 커밋이 일어나 갱신되지만, 60일 내내 신호가 없을 수도 있습니다.
  GitHub에서 중지 경고 메일이 오면 아무 커밋이나 하나 밀면 되살아납니다.
- 봇이 한동안 멈췄다 재개되면 지나간 신호를 하나씩 울리지 않고
  **요약 1건**으로 보냅니다 (`MAX_BACKLOG_BARS` 기준).
- 비트겟 API 장애 시 지수 백오프로 3회 재시도합니다.
  한 종목이 실패해도 나머지는 계속 처리합니다.

---

## 구조

```
bot/
  config.py       감시 종목 · 지표 파라미터   ← 여기만 만지면 됩니다
  bitget.py       공개 캔들 API (인증 불필요)
  indicators.py   EMA / Stoch / MACD — TradingView와 수치가 일치해야 하는 부분
  signals.py      신호 판정 (COVER 버그 수정 지점)
  notify.py       디스코드 전송
  main.py         엔트리포인트
tests/            지표 검증 18건
pine/             수정된 TradingView 스크립트
state.json        마지막으로 처리한 봉 (중복 알림 방지)
```

**외부 패키지를 쓰지 않습니다.** 파이썬 표준 라이브러리만으로 동작하므로
`pip install` 이 필요 없고, 맥의 기본 파이썬(3.9)에서도 그대로 돕니다.

---

## 참고: 무료 배포 + 레퍼럴 수익화를 검토하신다면

작업 전에 확인한 사실만 적습니다. 판단은 직접 하셔야 합니다.

- **TradingView House Rules**는 스크립트 설명·릴리즈노트·제목·차트·코드에
  **모든 링크와 홍보를 금지**합니다. 위반 시 게시물이 숨겨지고 얻은 평판이 사라지며,
  경고·정지까지 갈 수 있습니다.
  → 스크립트 공개는 가능하지만, 설명란에 레퍼럴 링크는 넣을 수 없습니다.
- **특정금융정보법**: FIU는 불법 가상자산 취급업자 유형으로
  **"미신고 사업자에 대한 블로그·SNS 홍보·알선(레퍼럴)"** 을 직접 적시했습니다.
  내국인을 대상으로 미신고 거래소를 반복 홍보하고 수수료를 계속 받는 구조는
  **5년 이하 징역 또는 5천만원 이하 벌금** 대상이 될 수 있습니다.
  비트겟은 FIU 미신고 상태입니다.
- 유료 정보 제공(멤버십·구독) 형태로 가면 **자본시장법상 유사투자자문업 신고**
  대상인지 별도로 확인이 필요합니다.

이 저장소는 **본인 전용**으로 만들어져 있습니다. 다수에게 뿌리는 기능은 없습니다.

### 출처

- [TradingView 무료 플랜 알림 제한](https://www.tv-hub.org/guide/tradingview-alerts-setup)
- [TradingView House Rules](https://www.tradingview.com/support/solutions/43000591638-our-house-rules/)
- [Bitget 캔들 API 문서](https://www.bitget.com/api-doc/contract/market/Get-Candle-Data)
- [FIU 불법 가상자산 취급업자 유형](https://fsc.go.kr/po010101/87177)
- [코인 레퍼럴 법률 리스크 정리](https://bh-law.kr/ko/news/column/coin-referral-vasp)

---

## 면책

이 도구는 가격 데이터로 기술적 지표를 계산해 알려줄 뿐입니다.
매매 권유가 아니며, 신호의 정확성이나 수익성을 보장하지 않습니다.
투자 판단과 그 결과는 전적으로 사용자 본인의 책임입니다.
