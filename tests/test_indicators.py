"""지표 계산 검증. 표준 unittest 만 쓴다.

    python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import indicators as ind  # noqa: E402


class TestEma(unittest.TestCase):
    def test_seeds_with_sma_not_first_value(self):
        # length=3 -> alpha=0.5, 시드는 (1+2+3)/3 = 2
        # 이후 0.5*src + 0.5*prev 이므로 정확히 정수열이 나온다.
        out = ind.ema([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[3], 3.0)
        self.assertAlmostEqual(out[9], 9.0)

    def test_too_short_series_is_all_none(self):
        self.assertEqual(ind.ema([1, 2], 5), [None] * 2)

    def test_constant_series_converges_to_constant(self):
        out = ind.ema([7.0] * 50, 21)
        self.assertAlmostEqual(out[-1], 7.0)


class TestRolling(unittest.TestCase):
    def test_highest_window(self):
        out = ind.highest([3, 1, 4, 1, 5, 9, 2], 3)
        self.assertEqual(out, [None, None, 4, 4, 5, 9, 9])

    def test_lowest_window(self):
        out = ind.lowest([3, 1, 4, 1, 5, 9, 2], 3)
        self.assertEqual(out, [None, None, 1, 1, 1, 1, 2])

    def test_none_inside_window_blocks_result(self):
        out = ind.highest([None, 2, 3, 4], 3)
        self.assertEqual(out, [None, None, None, 4])


class TestStoch(unittest.TestCase):
    def test_raw_k(self):
        highs = [10, 11, 12]
        lows = [5, 6, 7]
        closes = [9, 10, 11]
        out = ind.stoch(closes, highs, lows, 3)
        self.assertEqual(out[:2], [None, None])
        # 100 * (11 - 5) / (12 - 5)
        self.assertAlmostEqual(out[2], 100.0 * 6 / 7)

    def test_at_window_high_is_100(self):
        out = ind.stoch([12, 12, 12], [10, 11, 12], [5, 6, 7], 3)
        self.assertAlmostEqual(out[2], 100.0)

    def test_flat_range_is_none_not_crash(self):
        out = ind.stoch([5, 5, 5], [5, 5, 5], [5, 5, 5], 3)
        self.assertIsNone(out[2])


class TestMacd(unittest.TestCase):
    def test_signal_line_alignment(self):
        closes = [100.0 + i for i in range(100)]
        line, signal = ind.macd(closes, 12, 26, 9)

        # macd_line 은 느린 EMA 가 뜨는 index 25 부터 유효하다.
        self.assertIsNone(line[24])
        self.assertIsNotNone(line[25])

        # signal 은 그로부터 9봉 뒤(index 33)부터 유효해야 한다.
        self.assertIsNone(signal[32])
        self.assertIsNotNone(signal[33])

    def test_rising_series_has_positive_macd(self):
        closes = [100.0 + i for i in range(100)]
        line, _ = ind.macd(closes, 12, 26, 9)
        self.assertGreater(line[-1], 0)


class TestCross(unittest.TestCase):
    def test_crossover(self):
        a = [1.0, 2.0, 4.0]
        b = [3.0, 3.0, 3.0]
        self.assertFalse(ind.crossover(a, b, 1))
        self.assertTrue(ind.crossover(a, b, 2))

    def test_crossunder(self):
        a = [4.0, 4.0, 2.0]
        b = [3.0, 3.0, 3.0]
        self.assertFalse(ind.crossunder(a, b, 1))
        self.assertTrue(ind.crossunder(a, b, 2))

    def test_touching_without_crossing_is_not_a_cross(self):
        # 같아졌다가 도로 내려가면 교차가 아니다.
        a = [1.0, 3.0, 2.0]
        b = [3.0, 3.0, 3.0]
        self.assertFalse(ind.crossover(a, b, 1))
        self.assertFalse(ind.crossover(a, b, 2))

    def test_none_never_crosses(self):
        self.assertFalse(ind.crossover([None, 5.0], [None, 1.0], 1))
        self.assertFalse(ind.crossover([1.0], [2.0], 0))


class TestCoverBugFix(unittest.TestCase):
    """원본 Pine 의 shortExit 버그가 재현되지 않는지 확인.

    원본:  shortExit = shortEntry[1] and buySignal
    -> 숏 진입 바로 다음 봉에 골든크로스가 나야만 성립한다.

    아래 시계열은 상승 -> 하락 전환 -> 회복 3구간의 합성 데이터로,
    SHORT 이후 COVER 까지 39봉이 걸린다. 원본 로직이었다면 COVER 는 나오지 않는다.
    """

    # 상승(0-69) / 하락(70-114) / 회복(115-189) 구간을 가진 합성 종가.
    CLOSES = [
    99.45, 98.94, 99.13, 99.31, 101.38, 100.96, 100.74, 100.87, 102.85, 102.39, 103.03,
    103.13, 103.81, 105.78, 105.49, 107.11, 106.61, 106.19, 107.54, 109.57, 110.50,
    112.81, 114.96, 116.25, 115.95, 116.54, 117.34, 117.20, 117.46, 119.71, 121.74,
    122.90, 122.34, 122.59, 122.10, 123.47, 123.59, 124.44, 125.32, 126.81, 128.76,
    130.72, 130.85, 131.10, 132.70, 133.69, 133.38, 134.62, 135.32, 137.81, 139.95,
    139.65, 140.61, 142.04, 141.73, 142.20, 144.24, 144.51, 144.22, 144.15, 146.19,
    146.30, 146.25, 148.69, 149.61, 149.57, 151.75, 153.59, 154.52, 156.12, 155.16,
    152.81, 150.73, 150.97, 150.89, 150.30, 150.22, 150.14, 150.32, 150.25, 150.45,
    148.79, 146.29, 145.15, 144.94, 143.40, 142.20, 140.41, 139.95, 138.32, 138.12,
    137.00, 136.62, 135.70, 133.34, 131.21, 130.56, 129.04, 128.79, 127.74, 125.97,
    126.02, 124.34, 124.29, 124.41, 122.83, 120.22, 120.56, 119.45, 117.66, 116.07,
    116.17, 116.52, 116.27, 115.59, 117.77, 117.63, 118.71, 121.25, 123.43, 124.69,
    124.79, 126.59, 127.65, 130.16, 131.50, 133.38, 135.87, 136.78, 139.33, 140.06,
    140.90, 141.52, 143.70, 145.16, 145.90, 146.76, 149.23, 149.14, 151.35, 151.51,
    153.37, 154.96, 154.58, 155.03, 157.10, 158.98, 161.56, 163.22, 164.75, 166.70,
    168.56, 169.75, 170.02, 170.63, 170.82, 171.68, 174.23, 176.54, 178.33, 180.04,
    182.28, 184.63, 185.06, 185.67, 187.50, 186.95, 189.06, 190.32, 190.65, 193.11,
    195.28, 194.80, 196.11, 198.36, 198.50, 198.57, 198.35, 199.81, 201.31, 203.09,
    203.11, 203.20, 204.83, 205.89, 205.70, 206.93, 208.38, 208.53, 210.86
    ]

    def _signals(self):
        from bot.bitget import Candle
        from bot.signals import detect

        return detect([
            Candle(
                time=i * 3600 * 1000,
                open=c, high=c * 1.002, low=c * 0.998, close=c, volume=1.0,
            )
            for i, c in enumerate(self.CLOSES)
        ])

    def test_cover_fires_long_after_short_entry(self):
        from bot.signals import COVER, SHORT

        sigs = self._signals()
        kinds = [s.kind for s in sigs]

        self.assertIn(SHORT, kinds, "숏 진입 신호가 나와야 한다")
        self.assertIn(COVER, kinds, "원본 버그라면 COVER 가 영영 안 나온다")
        self.assertLess(
            kinds.index(SHORT), kinds.index(COVER), "COVER 는 SHORT 뒤에 와야 한다"
        )

    def test_gap_is_far_too_wide_for_the_original_logic(self):
        from bot.signals import COVER, SHORT

        bar = {s.kind: s.bar_time // (3600 * 1000) for s in self._signals()}
        gap = bar[COVER] - bar[SHORT]
        self.assertEqual(gap, 39)
        self.assertGreater(gap, 1, "간격이 1봉이면 이 테스트가 버그를 못 잡는다")

    def test_sell_and_short_share_the_same_bar(self):
        """숏 진입은 롱 청산과 같은 봉에서 일어난다. 둘 다 알려야 한다."""
        from bot.signals import SELL, SHORT

        sigs = self._signals()
        sell = next(s for s in sigs if s.kind == SELL)
        short = next(s for s in sigs if s.kind == SHORT)
        self.assertEqual(sell.bar_time, short.bar_time)
        self.assertTrue(short.reason, "SHORT 은 트리거 사유가 있어야 한다")


if __name__ == "__main__":
    unittest.main()
