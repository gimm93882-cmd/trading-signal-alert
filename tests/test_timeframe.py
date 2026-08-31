"""타임프레임 분리 검증.

1시간봉과 15분봉을 함께 돌리면서 어긋나기 쉬운 것들을 고정한다.

  1. 상태가 타임프레임별로 따로 관리되는가 (섞이면 한쪽이 과거 신호를 몰아 보낸다)
  2. 예전 상태 키가 1시간봉으로 이관되는가 (안 되면 기존 사용자가 과거 신호를 다시 받는다)
  3. SHORT/COVER 가 알림에서 빠지는가 (숏은 쓰지 않는다)
  4. 신호가 자기 봉 길이를 들고 다니는가 (알림의 마감 시각이 틀어진다)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import config, main as m       # noqa: E402
from bot.bitget import Candle           # noqa: E402
from bot.signals import BUY, SELL, SHORT, COVER, detect  # noqa: E402


class TestStateMigration(unittest.TestCase):
    def test_old_key_moves_to_1h(self):
        state = {"BTCUSDT": {"last_bar": 123}}
        m._migrate_state(state)
        self.assertEqual(state, {"BTCUSDT@1H": {"last_bar": 123}})

    def test_new_keys_untouched(self):
        state = {"BTCUSDT@1H": {"last_bar": 1}, "BTCUSDT@15m": {"last_bar": 2}}
        before = dict(state)
        m._migrate_state(state)
        self.assertEqual(state, before)

    def test_does_not_clobber_existing(self):
        """이미 1시간봉 상태가 있으면 옛 키가 덮어쓰지 않는다."""
        state = {"BTCUSDT": {"last_bar": 100}, "BTCUSDT@1H": {"last_bar": 999}}
        m._migrate_state(state)
        self.assertEqual(state["BTCUSDT@1H"]["last_bar"], 999)
        self.assertNotIn("BTCUSDT", state)


class TestTimeframeConfig(unittest.TestCase):
    def test_two_timeframes(self):
        names = [t[0] for t in config.TIMEFRAMES]
        self.assertIn("1H", names)
        self.assertIn("15m", names)

    def test_bar_seconds_match_granularity(self):
        for g, secs, _ in config.TIMEFRAMES:
            expect = {"1H": 3600, "15m": 900}.get(g)
            if expect:
                self.assertEqual(secs, expect, "%s 의 봉 길이가 어긋난다" % g)

    def test_short_and_cover_excluded(self):
        self.assertNotIn(SHORT, config.SIGNAL_KINDS)
        self.assertNotIn(COVER, config.SIGNAL_KINDS)
        self.assertIn(BUY, config.SIGNAL_KINDS)
        self.assertIn(SELL, config.SIGNAL_KINDS)


class TestSignalCarriesTimeframe(unittest.TestCase):
    """신호가 자기 봉 길이를 들고 다녀야 알림의 마감 시각이 맞는다."""

    def _bars(self, closes, bar_seconds):
        return [
            Candle(time=i * bar_seconds * 1000, open=c, high=c * 1.003,
                   low=c * 0.997, close=c, volume=1.0, bar_seconds=bar_seconds)
            for i, c in enumerate(closes)
        ]

    # 완만한 상승 뒤 급락 — 데드크로스가 확실히 나는 구간
    CLOSES = [100.0 + i * 0.15 for i in range(60)] + [99.0] + [98.0 + i * 0.2 for i in range(40)]

    def test_15m_signal_knows_its_bar_length(self):
        sigs = detect(self._bars(self.CLOSES, 900), u"15분봉")
        self.assertTrue(sigs, "전제 확인: 신호가 나와야 한다")
        for s in sigs:
            self.assertEqual(s.bar_seconds, 900)
            self.assertEqual(s.tf, u"15분봉")

    def test_1h_signal_knows_its_bar_length(self):
        sigs = detect(self._bars(self.CLOSES, 3600), u"1시간봉")
        self.assertTrue(sigs)
        for s in sigs:
            self.assertEqual(s.bar_seconds, 3600)

    def test_close_time_follows_bar_length(self):
        c15 = self._bars([1, 2, 3], 900)[0]
        c1h = self._bars([1, 2, 3], 3600)[0]
        self.assertEqual(c15.close_time - c15.time, 900 * 1000)
        self.assertEqual(c1h.close_time - c1h.time, 3600 * 1000)


class TestNotifyUsesBarLength(unittest.TestCase):
    """알림 제목·본문의 마감 시각이 봉 길이를 따라가는지."""

    def _sig(self, bar_seconds, tf):
        from bot.signals import Signal
        return Signal(kind=SELL, bar_time=1787846400000, close=77728.1,
                      ema_short=78218.6, ema_long=78330.07, stoch_k=40.1,
                      macd=115.7, macd_signal=255.4, reason="",
                      bar_seconds=bar_seconds, tf=tf)

    def _subject(self, sig):
        from bot.notify_email import EmailNotifier
        box = {}
        n = EmailNotifier("me@g.com", "pw", "me@g.com")
        n._send = lambda s, b: box.update(subject=s, body=b)
        n.send_signal("BTCUSDT", sig)
        return box

    def test_subject_shows_timeframe(self):
        self.assertIn(u"15분봉", self._subject(self._sig(900, u"15분봉"))["subject"])
        self.assertIn(u"1시간봉", self._subject(self._sig(3600, u"1시간봉"))["subject"])

    def test_close_time_differs_by_timeframe(self):
        b15 = self._subject(self._sig(900, u"15분봉"))["body"]
        b1h = self._subject(self._sig(3600, u"1시간봉"))["body"]
        self.assertNotEqual(b15, b1h, "봉 길이가 다르면 마감 시각도 달라야 한다")


if __name__ == "__main__":
    unittest.main()
