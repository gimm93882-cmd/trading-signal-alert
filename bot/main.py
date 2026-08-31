"""엔트리포인트. 매시 정각 직후 1회 실행되는 것을 전제로 한다.

    python3 -m bot.main                      실제 전송
    python3 -m bot.main --dry-run            전송 없이 출력만
    python3 -m bot.main --backfill 200       최근 200봉 신호 전부 출력 (검증용)
    python3 -m bot.main --symbols BTCUSDT    심볼 지정
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config, notify
from .bitget import BitgetError, fetch_candles
from .signals import detect

KST = timezone(timedelta(hours=9))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, config.STATE_FILE)


def main(argv=None):
    args = _parse_args(argv)
    symbols = args.symbols or config.SYMBOLS

    if args.backfill:
        return _backfill(symbols, args.backfill)

    senders = [] if args.dry_run else notify.build_senders()
    if senders:
        print("알림 채널: " + ", ".join(x.name for x in senders))

    state = _load_state()
    failures = []

    for symbol in symbols:
        try:
            _run_symbol(symbol, state, senders, args.dry_run)
        except (BitgetError, notify.NotifyError) as err:
            print("[%s] 실패: %s" % (symbol, err), file=sys.stderr)
            failures.append(symbol)

    if not args.dry_run:
        _save_state(state)

    if failures:
        print("실패한 심볼: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def _run_symbol(symbol, state, senders, dry_run):
    now = int(time.time() * 1000)

    # 형성 중인 봉까지 받아온다. 확정 판정에는 쓰지 않고, 트레이딩뷰 화면에
    # 지금 보이는 것과 같은 상태를 재현해 잠정 신호를 내는 데만 쓴다.
    rows = fetch_candles(
        symbol,
        config.GRANULARITY,
        config.PRODUCT_TYPE,
        config.CANDLE_LIMIT,
        include_forming=True,
    )
    candles = [c for c in rows if c.is_closed(now)]
    forming = rows[-1] if rows and not rows[-1].is_closed(now) else None

    if not candles:
        raise BitgetError("확정된 캔들이 없음: " + symbol)

    newest = candles[-1].time
    signals = detect(candles)

    entry = state.get(symbol)

    # 첫 실행: 과거 300봉의 신호를 몰아서 보내면 안 된다. 기준점만 잡고 넘어간다.
    if entry is None:
        state[symbol] = {"last_bar": newest}
        print(
            "[%s] 초기화 — 기준봉 %s. 다음 실행부터 알림을 보냅니다."
            % (symbol, _kst(newest))
        )
        return

    last_bar = entry.get("last_bar", 0)

    if newest > last_bar:
        _emit_confirmed(symbol, entry, signals, last_bar, newest, senders, dry_run)
        entry["last_bar"] = newest
    else:
        print("[%s] 새 확정봉 없음 (마지막 %s)" % (symbol, _kst(last_bar)))

    _resolve_provisional(symbol, entry, signals, newest, senders, dry_run)

    if forming is not None:
        _emit_provisional(symbol, entry, candles, forming, now, senders, dry_run)


def _emit_confirmed(symbol, entry, signals, last_bar, newest, senders, dry_run):
    fresh = [s for s in signals if s.bar_time > last_bar]
    if not fresh:
        print("[%s] 신호 없음 — %s 까지 확인" % (symbol, _kst(newest)))
        return

    # 크론이 오래 멈춰 있었다면 지나간 신호를 하나씩 울리는 건 소음일 뿐이다.
    cutoff = newest - config.MAX_BACKLOG_BARS * config.BAR_SECONDS * 1000
    if last_bar < cutoff:
        print("[%s] 밀린 신호 %d건 — 요약으로 전송" % (symbol, len(fresh)))
        if dry_run:
            for s in fresh:
                print("    " + _line(s))
        else:
            for sender in senders:
                sender.send_backlog_summary(symbol, fresh)
        return

    for s in fresh:
        print("[%s] 확정 %s" % (symbol, _line(s)))
        for sender in senders:
            sender.send_signal(symbol, s)


def _resolve_provisional(symbol, entry, signals, newest, senders, dry_run):
    """잠정으로 알렸던 봉이 닫혔으면, 확정됐는지 확인하고 아니면 취소를 알린다.

    잠정 신호는 봉 중간의 값으로 판정한 것이라 봉이 닫히면서 조건이 무효가 될 수 있다.
    알리고 끝내면 사용자는 없어진 신호를 붙잡고 있게 되므로 반드시 뒷정리를 보낸다.
    """
    prov = entry.get("provisional")
    if not prov or prov["bar"] > newest:
        return                                  # 아직 그 봉이 닫히지 않았다

    held = {s.kind for s in signals if s.bar_time == prov["bar"]}
    dropped = [k for k in prov["kinds"] if k not in held]

    if dropped:
        print("[%s] 잠정 취소 %s (%s 봉)"
              % (symbol, "/".join(dropped), _kst(prov["bar"] + config.BAR_SECONDS * 1000)))
        if not dry_run:
            for sender in senders:
                sender.send_cancelled(symbol, prov["bar"], dropped)

    entry.pop("provisional", None)


def _emit_provisional(symbol, entry, candles, forming, now, senders, dry_run):
    """형성 중인 봉에서 조건이 성립하면 봉 마감을 기다리지 않고 바로 알린다.

    확정만 기다리면 최대 1시간 늦는다. 차트를 계속 볼 수 없어서 알림을 쓰는데
    차트보다 느리면 알림의 목적이 사라진다. 대신 확정이 아님을 명시해서 보낸다.
    같은 봉·같은 종류는 한 번만 보낸다(10분마다 재전송 방지).
    """
    if not config.PROVISIONAL_ALERTS:
        return

    live = detect(candles + [forming])
    fresh = [s for s in live if s.bar_time == forming.time]
    if not fresh:
        return

    prov = entry.get("provisional")
    sent = set(prov["kinds"]) if prov and prov["bar"] == forming.time else set()
    new = [s for s in fresh if s.kind not in sent]

    for s in new:
        left = max(0, (forming.time + config.BAR_SECONDS * 1000 - now) // 60000)
        print("[%s] 잠정 %s (마감 %d분 전)" % (symbol, _line(s), left))
        if not dry_run:
            for sender in senders:
                sender.send_provisional(symbol, s, now)

    # dry-run 이면 _save_state 가 호출되지 않으므로 여기서 따로 가를 필요가 없다.
    entry["provisional"] = {
        "bar": forming.time,
        "kinds": sorted(sent | {s.kind for s in new}),
    }


def _backfill(symbols, bars):
    """최근 N봉 구간의 신호를 표로 출력한다. TradingView 차트와 대조하기 위한 것."""
    for symbol in symbols:
        candles = fetch_candles(
            symbol,
            config.GRANULARITY,
            config.PRODUCT_TYPE,
            max(config.CANDLE_LIMIT, bars + config.LONG_LEN + config.DIV_LOOKBACK),
        )
        signals = detect(candles)

        if bars < len(candles):
            floor = candles[-bars].time
            signals = [s for s in signals if s.bar_time >= floor]

        span = "%s ~ %s" % (_kst(candles[-min(bars, len(candles))].time), _kst(candles[-1].time))
        print("\n=== %s  (확정봉 %d개, %s) ===" % (symbol, len(candles), span))
        print("%-16s  %-6s  %12s  %8s  %s" % ("봉 마감(KST)", "신호", "종가", "Stoch%K", "비고"))
        print("-" * 72)
        for s in signals:
            print(_line(s))
        print("-> 신호 %d건" % len(signals))
    return 0


def _line(s):
    return "%-16s  %-6s  %12s  %8s  %s" % (
        _kst(s.bar_time + config.BAR_SECONDS * 1000),
        s.kind,
        notify._price(s.close),
        notify._num(s.stoch_k, 1),
        s.reason,
    )


def _kst(ms):
    return datetime.fromtimestamp(ms / 1000.0, KST).strftime("%Y-%m-%d %H:%M")


def _load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as err:
        # 상태 파일이 깨졌으면 비운다. 다음 실행이 초기화 경로를 타서
        # 과거 신호를 몰아 보내는 사고를 막는다.
        print("state.json 을 읽을 수 없어 초기화합니다: %s" % err, file=sys.stderr)
        return {}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")


def _parse_args(argv):
    p = argparse.ArgumentParser(description="1시간봉 신호 → 디스코드 알림")
    p.add_argument("--dry-run", action="store_true", help="전송하지 않고 출력만")
    p.add_argument("--backfill", type=int, metavar="N", help="최근 N봉 신호 전부 출력")
    p.add_argument("--symbols", nargs="+", metavar="SYM", help="심볼 지정")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
