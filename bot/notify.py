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


def send_signal(symbol: str, sig: Signal, url: str) -> None:
    style = STYLE[sig.kind]
    closed_at = datetime.fromtimestamp((sig.bar_time + 3600 * 1000) / 1000.0, KST)

    fields = [
        _field("종가", _price(sig.close)),
        _field("봉 마감 (KST)", closed_at.strftime("%m/%d %H:%M")),
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

    embed = {
        "title": "%s %s · %s 1H" % (style["emoji"], style["label"], symbol),
        "description": style["desc"],
        "color": style["color"],
        "fields": fields,
        "footer": {"text": FOOTER},
        "timestamp": closed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _post(url, {"embeds": [embed]})


def send_backlog_summary(symbol: str, signals: List[Signal], url: str) -> None:
    """오래 멈춰 있다 재개된 경우, 개별 전송 대신 요약 1건만 보낸다."""
    lines = []
    for sig in signals:
        closed_at = datetime.fromtimestamp((sig.bar_time + 3600 * 1000) / 1000.0, KST)
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
