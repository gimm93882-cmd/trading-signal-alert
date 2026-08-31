"""디스코드 웹훅 전송.

웹훅 URL 은 환경변수 DISCORD_WEBHOOK_URL 로 받는다. 코드나 저장소에 넣지 않는다.
URL 을 아는 사람은 누구나 그 채널에 글을 쓸 수 있으므로 Secret 으로만 다룬다.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List

from .signals import BUY, COVER, SELL, SHORT, Signal

KST = timezone(timedelta(hours=9))
TIMEOUT = 15

ENV_KEY = "DISCORD_WEBHOOK_URL"

STYLE = {
    BUY:   {"color": 3447003,  "emoji": "\U0001F7E6", "label": "BUY",   "desc": "롱 진입"},
    SELL:  {"color": 15158332, "emoji": "\U0001F7E5", "label": "SELL",  "desc": "롱 청산"},
    SHORT: {"color": 15105570, "emoji": "\U0001F7E7", "label": "SHORT", "desc": "숏 진입"},
    COVER: {"color": 16776960, "emoji": "\U0001F7E8", "label": "COVER", "desc": "숏 청산"},
}

FOOTER = "자동 계산된 기술적 지표입니다. 투자 판단과 그 결과는 본인 책임입니다."

# 잠정 신호: 봉이 아직 닫히지 않았다. 트레이딩뷰 화면에 지금 보이는 것과 같은 상태이며,
# 봉이 닫히면서 조건이 무효가 되면 사라진다(리페인팅). 그래서 확정 신호와 반드시 구분한다.
PROVISIONAL_COLOR = 10070709      # 회색 — 확정 신호의 원색과 구분
CANCELLED_COLOR = 6323595
PROVISIONAL_NOTE = "봉이 닫히기 전이라 사라질 수 있습니다. 확정 알림이 뒤따릅니다."
CANCELLED_NOTE = "봉이 닫히면서 조건이 무효가 됐습니다. 이 신호로 진입하지 마세요."


class NotifyError(RuntimeError):
    pass


def webhook_url():
    url = os.environ.get(ENV_KEY, "").strip()
    if not url:
        raise NotifyError(
            "환경변수 " + ENV_KEY + " 가 비어 있습니다.\n"
            "로컬에서는  export " + ENV_KEY + "='https://discord.com/api/webhooks/...'\n"
            "GitHub Actions 에서는 저장소 Settings > Secrets 에 등록하세요."
        )
    return url


def _signal_fields(sig, closed_at, provisional):
    fields = [
        _field("종가", _price(sig.close)),
        _field(
            "마감 예정 (KST)" if provisional else "봉 마감 (KST)",
            closed_at.strftime("%m/%d %H:%M"),
        ),
        _field(
            "EMA",
            "단기 %s\n장기 %s" % (_price(sig.ema_short), _price(sig.ema_long)),
        ),
        _field("Stoch %K", _num(sig.stoch_k, 1)),
        _field(
            "MACD",
            "%s / sig %s" % (_num(sig.macd, 2), _num(sig.macd_signal, 2)),
        ),
    ]
    if sig.reason:
        fields.append(_field("트리거", sig.reason, inline=False))
    return fields


def send_signal(symbol: str, sig: Signal, url: str) -> None:
    style = STYLE[sig.kind]
    closed_at = datetime.fromtimestamp(
        (sig.bar_time + sig.bar_seconds * 1000) / 1000.0, KST)

    embed = {
        "title": "%s %s · %s %s" % (style["emoji"], style["label"], symbol, sig.tf or "1H"),
        "description": style["desc"],
        "color": style["color"],
        "fields": _signal_fields(sig, closed_at, False),
        "footer": {"text": FOOTER},
        "timestamp": closed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _post(url, {"embeds": [embed]})


def send_provisional(symbol: str, sig: Signal, url: str, now_ms: int) -> None:
    """봉이 닫히기 전에 조건이 성립한 시점에 바로 보낸다.

    차트를 계속 볼 수 없어서 알림을 쓰는 것이므로, 확정까지 최대 1시간을
    기다리게 하면 알림의 목적 자체가 사라진다. 대신 **확정이 아님을 제목에 박아**
    확정 신호와 헷갈리지 않게 한다.
    """
    style = STYLE[sig.kind]
    closes_at_ms = sig.bar_time + sig.bar_seconds * 1000
    closed_at = datetime.fromtimestamp(closes_at_ms / 1000.0, KST)
    left = max(0, (closes_at_ms - now_ms) // 60000)

    embed = {
        "title": "\u26A1 %s 잠정 · %s %s" % (style["label"], symbol, sig.tf or "1H"),
        "description": "%s — **아직 확정 아님** (마감 %d분 전)\n%s"
                       % (style["desc"], left, PROVISIONAL_NOTE),
        "color": PROVISIONAL_COLOR,
        "fields": _signal_fields(sig, closed_at, True),
        "footer": {"text": FOOTER},
    }
    _post(url, {"embeds": [embed]})


def send_cancelled(symbol: str, bar_time: int, kinds, url: str,
                   bar_seconds: int = 3600, tf: str = "") -> None:
    """잠정으로 알렸던 신호가 봉 마감과 함께 무효가 됐을 때."""
    closed_at = datetime.fromtimestamp((bar_time + bar_seconds * 1000) / 1000.0, KST)
    labels = " · ".join(STYLE[k]["label"] for k in kinds)

    embed = {
        "title": "\u2716 %s 잠정 취소 · %s %s" % (labels, symbol, tf or "1H"),
        "description": "%s 봉 기준 %s"
                       % (closed_at.strftime("%m/%d %H:%M"), CANCELLED_NOTE),
        "color": CANCELLED_COLOR,
        "footer": {"text": FOOTER},
    }
    _post(url, {"embeds": [embed]})


def send_backlog_summary(symbol: str, signals: List[Signal], url: str) -> None:
    """오래 멈춰 있다 재개된 경우, 개별 전송 대신 요약 1건만 보낸다."""
    lines = []
    for sig in signals:
        closed_at = datetime.fromtimestamp(
        (sig.bar_time + sig.bar_seconds * 1000) / 1000.0, KST)
        lines.append(
            "`%s`  %s  %s"
            % (closed_at.strftime("%m/%d %H:%M"), sig.kind.ljust(5), _price(sig.close))
        )

    embed = {
        "title": "⏸ %s · 놓친 신호 %d건" % (symbol, len(signals)),
        "description": (
            "봇이 한동안 멈춰 있었습니다. 그 사이 발생한 신호를 모아서 보냅니다.\n"
            "**이미 지나간 신호이므로 그대로 진입하지 마세요.**\n\n"
            + "\n".join(lines[-30:])
        ),
        "color": 9807270,
        "footer": {"text": FOOTER},
    }
    _post(url, {"embeds": [embed]})


def send_text(message: str, url: str) -> None:
    _post(url, {"content": message})


# --- 내부 -------------------------------------------------------------------

def _field(name, value, inline=True):
    return {"name": name, "value": value, "inline": inline}


def _price(v):
    if v is None:
        return "-"
    if abs(v) >= 1000:
        return "{:,.2f}".format(v)
    if abs(v) >= 1:
        return "{:,.4f}".format(v)
    return "{:.6f}".format(v)


def _num(v, digits):
    if v is None:
        return "-"
    return ("{:,.%df}" % digits).format(v)


def _post(url, payload, attempt=0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "trend-ribbon-alert/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            resp.read()
        time.sleep(0.4)          # 웹훅 레이트리밋(2초당 5건) 여유
    except urllib.error.HTTPError as err:
        if err.code == 429 and attempt < 3:
            retry_after = 2.0
            try:
                info = json.loads(err.read().decode("utf-8"))
                retry_after = float(info.get("retry_after", 2.0))
            except Exception:
                pass
            time.sleep(min(retry_after, 10.0))
            return _post(url, payload, attempt + 1)
        raise NotifyError("디스코드 전송 실패 (HTTP %d)" % err.code)
    except urllib.error.URLError as err:
        if attempt < 2:
            time.sleep(2 ** attempt)
            return _post(url, payload, attempt + 1)
        raise NotifyError("디스코드 전송 실패: " + str(err))


# --- 채널 디스패처 -----------------------------------------------------------

class DiscordNotifier:
    name = "디스코드"

    def __init__(self, url):
        self.url = url

    @classmethod
    def from_env(cls):
        url = os.environ.get(ENV_KEY, "").strip()
        return cls(url) if url else None

    def send_signal(self, symbol, sig):
        send_signal(symbol, sig, self.url)

    def send_backlog_summary(self, symbol, signals):
        send_backlog_summary(symbol, signals, self.url)

    def send_provisional(self, symbol, sig, now_ms):
        send_provisional(symbol, sig, self.url, now_ms)

    def send_cancelled(self, symbol, bar_time, kinds, bar_seconds=3600, tf=""):
        send_cancelled(symbol, bar_time, kinds, self.url, bar_seconds, tf)


def build_senders():
    """환경변수를 보고 활성화된 알림 채널을 모은다.

    디스코드와 이메일을 둘 다 설정하면 같은 신호가 양쪽으로 나간다.
    한쪽이 막혀도 다른 쪽이 도착하도록 하는 게 목적이다.
    """
    from .notify_email import EmailNotifier

    senders = [n for n in (DiscordNotifier.from_env(), EmailNotifier.from_env()) if n]
    if not senders:
        raise NotifyError(
            "알림 채널이 하나도 설정되지 않았습니다.\n"
            "  디스코드: " + ENV_KEY + "\n"
            "  이메일  : GMAIL_USER + GMAIL_APP_PASSWORD (+ 선택 MAIL_TO)\n"
            "둘 중 하나 이상을 환경변수 또는 GitHub Secret 으로 설정하세요."
        )
    return senders
