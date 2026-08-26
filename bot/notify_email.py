"""Gmail SMTP 로 신호를 보낸다.

푸시 알림에 실제로 보이는 건 **제목 한 줄**이다. 그래서 제목에
신호 종류·종목·가격을 다 넣고, 본문에 나머지를 담는다.

Gmail 은 일반 계정 비밀번호로는 SMTP 로그인이 안 된다.
2단계 인증을 켜고 **앱 비밀번호**(16자리)를 만들어 써야 한다. README 참조.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import List

from .signals import BUY, COVER, SELL, SHORT, Signal
from .notify import FOOTER, KST, STYLE, _num, _price, NotifyError

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
TIMEOUT = 20

ENV_USER = "GMAIL_USER"
ENV_PASS = "GMAIL_APP_PASSWORD"
ENV_TO = "MAIL_TO"

from datetime import datetime


class EmailNotifier:
    def __init__(self, user, password, to):
        self.user = user
        self.password = password
        # to 는 한 명일 수도, 쉼표로 구분된 여러 명일 수도 있다.
        self.recipients = _parse_recipients(to) or [user]

    @classmethod
    def from_env(cls):
        """환경변수가 갖춰져 있으면 인스턴스를, 아니면 None 을 돌려준다."""
        user = os.environ.get(ENV_USER, "").strip()
        password = os.environ.get(ENV_PASS, "").strip().replace(" ", "")
        if not user or not password:
            return None
        to = os.environ.get(ENV_TO, "").strip() or user
        return cls(user, password, to)

    @property
    def name(self):
        n = len(self.recipients)
        return "이메일" if n == 1 else "이메일(%d명)" % n

    def send_signal(self, symbol: str, sig: Signal) -> None:
        style = STYLE[sig.kind]
        closed = datetime.fromtimestamp((sig.bar_time + 3600 * 1000) / 1000.0, KST)

        subject = "%s %s · %s · %s" % (
            style["emoji"], style["label"], symbol, _price(sig.close)
        )

        lines = [
            "%s (%s)" % (style["label"], style["desc"]),
            "",
            "종목        %s  1시간봉" % symbol,
            "종가        %s" % _price(sig.close),
            "봉 마감     %s KST" % closed.strftime("%Y-%m-%d %H:%M"),
            "",
            "EMA 단기    %s" % _price(sig.ema_short),
            "EMA 장기    %s" % _price(sig.ema_long),
            "Stoch %%K    %s" % _num(sig.stoch_k, 1),
            "MACD        %s  (signal %s)" % (_num(sig.macd, 2), _num(sig.macd_signal, 2)),
        ]
        if sig.reason:
            lines += ["", "트리거      %s" % sig.reason]
        lines += ["", "-" * 40, FOOTER]

        self._send(subject, "\n".join(lines))

    def send_backlog_summary(self, symbol: str, signals: List[Signal]) -> None:
        subject = "⏸ %s · 놓친 신호 %d건" % (symbol, len(signals))

        rows = []
        for sig in signals:
            closed = datetime.fromtimestamp((sig.bar_time + 3600 * 1000) / 1000.0, KST)
            rows.append(
                "%s   %-6s %12s" % (closed.strftime("%m-%d %H:%M"), sig.kind, _price(sig.close))
            )

        body = "\n".join(
            [
                "봇이 한동안 멈춰 있었습니다. 그 사이 발생한 신호입니다.",
                "이미 지나간 신호이므로 그대로 진입하지 마세요.",
                "",
            ]
            + rows[-30:]
            + ["", "-" * 40, FOOTER]
        )
        self._send(subject, body)

    def _send(self, subject, body):
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.user

        # 수신자가 여러 명이면 반드시 숨은참조로 보낸다.
        # To 에 나열하면 받는 사람들끼리 서로의 이메일 주소를 전부 보게 되고,
        # 그건 동의 없는 개인정보 제3자 제공에 해당한다.
        if len(self.recipients) == 1:
            msg["To"] = self.recipients[0]
        else:
            msg["To"] = self.user
            msg["Bcc"] = ", ".join(self.recipients)

        msg.set_content(body)

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=TIMEOUT) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as err:
            raise NotifyError("수신 거부된 주소가 있습니다: " + str(err.recipients))
        except smtplib.SMTPAuthenticationError:
            raise NotifyError(
                "Gmail 로그인 실패. 일반 비밀번호가 아니라 **앱 비밀번호**(16자리)여야 합니다.\n"
                "2단계 인증을 먼저 켜야 앱 비밀번호를 만들 수 있습니다."
            )
        except (smtplib.SMTPException, OSError) as err:
            raise NotifyError("메일 전송 실패: " + str(err))


def _parse_recipients(raw):
    """쉼표·세미콜론·줄바꿈 아무거나로 구분된 주소 목록을 정리한다."""
    if not raw:
        return []
    out = []
    for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
        addr = chunk.strip()
        if addr and addr not in out:
            out.append(addr)
    return out
