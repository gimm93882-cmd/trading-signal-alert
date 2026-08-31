"""신호 기반 매매 전략 시뮬레이터.

봇과 **같은 신호 코드**(bot.signals.detect)를 쓴다. 지표를 바꾸면 백테스트도 같이 바뀐다.

    python3 -m tools.backtest                        기본 설정 1회
    python3 -m tools.backtest --leverage 20 --tranches 5 --step 1000
    python3 -m tools.backtest --sweep                조합 전수 탐색
    python3 -m tools.backtest --refresh              캔들 다시 받기

모델링 규칙
  - 진입은 BUY 봉 종가. 청산은 SELL 봉 종가(또는 손절/익절/청산 중 먼저 닿는 것).
  - 물타기: 진입가에서 --step 달러씩 내려갈 때마다 한 회차씩 추가. 최대 --tranches 회.
  - 회차당 증거금 = 매매 시작 시점 계좌의 --frac.
  - 한 봉 안의 순서는 알 수 없으므로 **불리한 쪽(저가 먼저)** 으로 가정한다.
    즉 같은 봉에서 손절선과 익절선에 모두 닿으면 손절로 친다.
"""

import argparse
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.bitget import Candle                       # noqa: E402
from bot.signals import BUY, SELL, detect           # noqa: E402
from tools import history                           # noqa: E402

MMR = 0.004          # 유지증거금률 근사
TAKER = 0.0006       # 편도 수수료


class Result(object):
    def __init__(self, equity, seed):
        self.equity = equity
        self.seed = seed
        self.wins = 0
        self.losses = 0
        self.liquidations = 0
        self.stops = 0
        self.targets = 0
        self.peak = seed
        self.max_dd = 0.0

    @property
    def mult(self):
        return self.equity / self.seed

    @property
    def trades(self):
        return self.wins + self.losses


def simulate(pairs, bars, idx, leverage, frac=0.20, tranches=1, step=1000.0,
             stop_pct=None, target_pct=None, fee=TAKER, seed=500000.0):
    """전략 하나를 처음부터 끝까지 돌린다.

    stop_pct / target_pct 는 **평단 대비 가격 변동률(%)** 이다.
    증거금 대비가 아니다. 레버리지를 곱하면 증거금 수익률이 된다.
    """
    r = Result(seed, seed)
    eq = seed

    for a, b in pairs:
        i, j = idx[a.bar_time], idx[b.bar_time]
        m = frac * eq
        if m <= 0:
            break

        entry = a.close
        fills = 1
        qty = m * leverage / entry
        margin = m
        notional = m * leverage
        fees = fee * notional
        exit_price = None

        for t in range(i + 1, j + 1):
            c = bars[t]

            # 저가가 아래 라인들을 지났으면 그만큼 추가매수가 체결된다.
            while fills < tranches and c.low <= entry - step * fills:
                p = entry - step * fills
                fills += 1
                qty += m * leverage / p
                margin += m
                notional += m * leverage
                fees += fee * m * leverage

            avg = notional / qty
            liq = margin * (leverage - 1) / (qty * (1 - MMR))

            if c.low <= liq:                       # 청산이 최우선
                exit_price = liq
                r.liquidations += 1
                break
            if stop_pct is not None and c.low <= avg * (1 + stop_pct / 100.0):
                exit_price = avg * (1 + stop_pct / 100.0)
                r.stops += 1
                break
            if target_pct is not None and c.high >= avg * (1 + target_pct / 100.0):
                exit_price = avg * (1 + target_pct / 100.0)
                r.targets += 1
                break

        if exit_price is None:
            exit_price = b.close

        avg = notional / qty
        fees += fee * qty * exit_price
        pnl = qty * (exit_price - avg) - fees
        pnl = max(pnl, -margin)                    # 손실은 투입 증거금을 넘지 않는다

        eq += pnl
        if pnl > 0:
            r.wins += 1
        else:
            r.losses += 1

        r.peak = max(r.peak, eq)
        r.max_dd = max(r.max_dd, (r.peak - eq) / r.peak * 100.0)

        if eq <= seed * 0.001:                     # 사실상 전멸
            eq = 0.0
            break

    r.equity = eq
    return r


def load_pairs(refresh=False, quiet=False):
    rows = history.load(refresh=refresh, quiet=quiet)
    bars = [Candle(time=int(x[0]), open=float(x[1]), high=float(x[2]),
                   low=float(x[3]), close=float(x[4]), volume=float(x[5]))
            for x in rows]
    idx = {c.time: k for k, c in enumerate(bars)}

    pairs, open_long = [], None
    for s in detect(bars):
        if s.kind == BUY:
            open_long = s
        elif s.kind == SELL and open_long:
            pairs.append((open_long, s))
            open_long = None
    return pairs, bars, idx


def _years(bars):
    return (bars[-1].time - bars[0].time) / 86400000.0 / 365.25


def _cagr(mult, years):
    if mult <= 0:
        return -100.0
    return (mult ** (1.0 / years) - 1) * 100.0


def main(argv=None):
    p = argparse.ArgumentParser(description="신호 전략 백테스트")
    p.add_argument("--leverage", type=float, default=10)
    p.add_argument("--frac", type=float, default=0.20, help="회차당 계좌 비중")
    p.add_argument("--tranches", type=int, default=5, help="최대 진입 회차 (1이면 물타기 없음)")
    p.add_argument("--step", type=float, default=1000.0, help="추가매수 간격 (달러)")
    p.add_argument("--stop", type=float, default=None, help="손절선 (평단 대비 %%, 예: -2)")
    p.add_argument("--target", type=float, default=None, help="익절선 (평단 대비 %%, 예: 1.5)")
    p.add_argument("--fee", type=float, default=TAKER * 100, help="편도 수수료 %%")
    p.add_argument("--seed", type=float, default=500000.0)
    p.add_argument("--sweep", action="store_true", help="조합 전수 탐색")
    p.add_argument("--refresh", action="store_true", help="캔들 다시 받기")
    args = p.parse_args(argv)

    print("캔들 로드 중...")
    pairs, bars, idx = load_pairs(refresh=args.refresh)
    yrs = _years(bars)
    print("%d봉 (%.1f년) · BUY→SELL %d건\n" % (len(bars), yrs, len(pairs)))

    if args.sweep:
        return _sweep(pairs, bars, idx, yrs, args.seed)

    r = simulate(pairs, bars, idx, args.leverage, args.frac, args.tranches,
                 args.step, args.stop, args.target, args.fee / 100.0, args.seed)
    print("설정  {:g}배 · 회차 {}회 × {:.0f}% · 간격 ${:,.0f} · 손절 {} · 익절 {}".format(
        args.leverage, args.tranches, args.frac * 100, args.step,
        "{}%".format(args.stop) if args.stop else "없음",
        "{}%".format(args.target) if args.target else "없음"))
    print("-" * 60)
    print("  최종 잔고    {:,.0f}원  ({:.2f}배)".format(r.equity, r.mult))
    print("  연복리       {:+.1f}%".format(_cagr(r.mult, yrs)))
    print("  매매         {}건 · 승 {} 패 {} (승률 {:.0f}%)".format(
        r.trades, r.wins, r.losses, r.wins / max(r.trades, 1) * 100))
    print("  청산 {}회 · 손절 {}회 · 익절 {}회".format(r.liquidations, r.stops, r.targets))
    print("  최대 낙폭    {:.1f}%".format(r.max_dd))
    return 0


def _sweep(pairs, bars, idx, yrs, seed):
    grid = dict(
        leverage=[1, 2, 3, 5, 10, 20],
        tranches=[1, 3, 5],
        step=[500.0, 1000.0, 2000.0],
        stop=[None, -1.0, -2.0, -3.0, -5.0],
        target=[None, 0.5, 1.0, 2.0, 4.0],
    )
    keys = list(grid)
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print("조합 %d개 탐색 중...\n" % len(combos))

    out = []
    for combo in combos:
        cfg = dict(zip(keys, combo))
        if cfg["tranches"] == 1 and cfg["step"] != 1000.0:
            continue                                # 물타기 없으면 간격은 의미 없다
        r = simulate(pairs, bars, idx, cfg["leverage"], 0.20, cfg["tranches"],
                     cfg["step"], cfg["stop"], cfg["target"], TAKER, seed)
        out.append((r.mult, cfg, r))

    out.sort(key=lambda x: -x[0])
    pos = [x for x in out if x[0] > 1.0]
    print("전체 {}조합 중 원금 이상 {}개 ({:.1f}%)\n".format(len(out), len(pos), len(pos) / len(out) * 100))

    print("  {:<5} {:<5} {:<7} {:<6} {:<6} {:>13} {:>8} {:>7} {:>6}".format(
        "배수", "회차", "간격", "손절", "익절", "최종잔고", "연복리", "최대낙폭", "청산"))
    print("  " + "-" * 74)
    for mult, cfg, r in out[:15]:
        print("  {:<5g} {:<5} {:<7} {:<6} {:<6} {:>13,.0f} {:>7.1f}% {:>6.1f}% {:>6}".format(
            cfg["leverage"], cfg["tranches"],
            "${:,.0f}".format(cfg["step"]) if cfg["tranches"] > 1 else "-",
            "{:g}%".format(cfg["stop"]) if cfg["stop"] else "-",
            "{:g}%".format(cfg["target"]) if cfg["target"] else "-",
            r.equity, _cagr(mult, yrs), r.max_dd, r.liquidations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
