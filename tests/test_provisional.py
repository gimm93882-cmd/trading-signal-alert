"""잠정(봉 마감 전) 신호 흐름 검증.

확정만 기다리면 알림이 최대 1시간 늦는다. 그래서 형성 중인 봉에서도 신호를 보내는데,
그 신호는 봉이 닫히면서 사라질 수 있다. 여기서 고정하는 계약은 셋이다.

  1. 형성 중인 봉에 조건이 성립하면 즉시 보낸다.
  2. 같은 봉·같은 종류를 반복해서 보내지 않는다 (몇 분마다 실행되므로).
  3. 봉이 조건 없이 닫히면 반드시 취소를 알린다. 알리고 끝내면 사용자가
     이미 사라진 신호를 붙잡고 있게 된다.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import main as m          # noqa: E402
from bot.bitget import Candle      # noqa: E402
from bot.signals import SELL       # noqa: E402

HOUR = 3600 * 1000


class FakeSender:
    name = "가짜"

    def __init__(self):
        self.provisional, self.confirmed, self.cancelled = [], [], []

    def send_provisional(self, symbol, sig, now_ms):
        self.provisional.append((symbol, sig.kind, sig.bar_time))

    def send_signal(self, symbol, sig):
        self.confirmed.append((symbol, sig.kind, sig.bar_time))

    def send_cancelled(self, symbol, bar_time, kinds):
        self.cancelled.append((symbol, bar_time, list(kinds)))

    def send_backlog_summary(self, symbol, signals):
        raise AssertionError("이 테스트에서 요약이 나올 일이 없다")


def bars(closes, start=0):
    return [
        Candle(time=start + i * HOUR, open=c, high=c * 1.003, low=c * 0.997,
               close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


# 60봉 완만한 상승 뒤 급락 한 봉.
# 램프가 완만해야 EMA9 와 EMA21 격차가 좁아 현실적인 낙폭으로 교차가 난다.
# step 0.15 기준 교차 임계 종가는 약 100.75(-7.4%)이므로 그보다 아래로 잡는다.
RISING = [100.0 + i * 0.15 for i in range(60)]
CRASH = 99.0                       # 데드크로스가 확실히 나는 값
RECOVER = RISING[-1] + 0.15        # 되돌리면 교차가 없던 일이 된다


class TestProvisionalEmit(unittest.TestCase):
    def setUp(self):
        self.confirmed = bars(RISING)
        self.forming = bars(RISING + [CRASH])[-1]
        self.sender = FakeSender()

    def test_fires_on_forming_bar(self):
        entry = {"last_bar": self.confirmed[-1].time}
        m._emit_provisional("BTCUSDT", entry, self.confirmed, self.forming,
                            self.forming.time + 10 * 60000, [self.sender], False)

        kinds = [k for _, k, _ in self.sender.provisional]
        self.assertIn(SELL, kinds, "형성 중인 봉의 데드크로스를 잡아야 한다")
        self.assertEqual(entry["provisional"]["bar"], self.forming.time)

    def test_does_not_resend_same_bar(self):
        entry = {"last_bar": self.confirmed[-1].time}
        for _ in range(3):
            m._emit_provisional("BTCUSDT", entry, self.confirmed, self.forming,
                                self.forming.time + 10 * 60000, [self.sender], False)

        sells = [k for _, k, _ in self.sender.provisional if k == SELL]
        self.assertEqual(len(sells), 1, "몇 분마다 실행돼도 한 번만 보내야 한다")

    def test_disabled_by_config(self):
        from bot import config
        saved = config.PROVISIONAL_ALERTS
        config.PROVISIONAL_ALERTS = False
        try:
            entry = {"last_bar": self.confirmed[-1].time}
            m._emit_provisional("BTCUSDT", entry, self.confirmed, self.forming,
                                self.forming.time, [self.sender], False)
        finally:
            config.PROVISIONAL_ALERTS = saved

        self.assertEqual(self.sender.provisional, [])
        self.assertNotIn("provisional", entry)


class TestProvisionalResolve(unittest.TestCase):
    """오늘 아침 실제로 일어난 상황: 장중에 뚫었다가 마감에 되돌아왔다."""

    def setUp(self):
        self.sender = FakeSender()
        self.prov_bar = 60 * HOUR

    def test_cancels_when_bar_closes_without_the_signal(self):
        closed = bars(RISING + [RECOVER])          # 되돌려서 교차가 사라진 봉
        signals = m.detect(closed)
        entry = {"last_bar": closed[-1].time,
                 "provisional": {"bar": self.prov_bar, "kinds": [SELL]}}

        m._resolve_provisional("BTCUSDT", entry, signals, closed[-1].time,
                               [self.sender], False)

        self.assertEqual(len(self.sender.cancelled), 1, "취소를 반드시 알려야 한다")
        self.assertEqual(self.sender.cancelled[0][2], [SELL])
        self.assertNotIn("provisional", entry)

    def test_silent_when_the_signal_held(self):
        closed = bars(RISING + [CRASH])            # 그대로 닫혀 확정된 봉
        signals = m.detect(closed)
        self.assertIn(SELL, [s.kind for s in signals if s.bar_time == self.prov_bar],
                      "전제 확인: 이 봉은 확정 신호를 낸다")

        entry = {"last_bar": closed[-1].time,
                 "provisional": {"bar": self.prov_bar, "kinds": [SELL]}}
        m._resolve_provisional("BTCUSDT", entry, signals, closed[-1].time,
                               [self.sender], False)

        self.assertEqual(self.sender.cancelled, [], "확정됐으면 취소를 보내면 안 된다")
        self.assertNotIn("provisional", entry)

    def test_waits_while_the_bar_is_still_open(self):
        entry = {"last_bar": 59 * HOUR,
                 "provisional": {"bar": self.prov_bar, "kinds": [SELL]}}
        m._resolve_provisional("BTCUSDT", entry, [], 59 * HOUR, [self.sender], False)

        self.assertEqual(self.sender.cancelled, [])
        self.assertIn("provisional", entry, "아직 닫히지 않았으면 그대로 둬야 한다")


if __name__ == "__main__":
    unittest.main()
