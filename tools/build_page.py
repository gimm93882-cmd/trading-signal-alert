"""아티팩트용 조각을 단독 호스팅 가능한 완전한 HTML 문서로 감싼다.

web/compound-calculator.html 은 아티팩트 환경을 전제로 쓰여 있어
<!doctype>, <html>, <head>, <body> 가 없다. 아티팩트는 게시할 때 그 뼈대를
붙여주지만, GitHub Pages 처럼 직접 호스팅할 때는 우리가 붙여야 한다.

특히 <meta charset> 이 없으면 브라우저가 인코딩을 추측해 한글이 깨진다.

    python3 -m tools.build_page ../복리계산기/index.html
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "web", "compound-calculator.html")

TITLE = "복리 계산기"
DESC = ("원금과 회차당 수익률로 복리를 계산합니다. 레버리지와 수수료를 수익률로 환산하고, "
        "목표 금액까지 걸리는 회차를 역산하며, 승률을 넣으면 실제 기대값으로 다시 계산합니다.")
FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           "<text y='.9em' font-size='90'>📈</text></svg>")

SKELETON = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="theme-color" content="#FF6B00">
<link rel="icon" href="{favicon}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta name="twitter:card" content="summary">
<style>
  *,*::before,*::after{{box-sizing:border-box}}
  html{{-webkit-text-size-adjust:100%}}
  body{{margin:0}}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def build(out_path):
    body = io.open(SRC, encoding="utf-8").read()

    # 단독 문서에는 head 에 진짜 뷰포트 태그가 들어가므로 주입 스크립트는 필요 없다.
    body = re.sub(
        r'<script>\s*/\* 이 파일을 단독으로.*?</script>\s*',
        "", body, count=1, flags=re.S,
    )

    html = SKELETON.format(title=TITLE, desc=DESC, favicon=FAVICON, body=body.strip())

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    io.open(out_path, "w", encoding="utf-8").write(html)
    return len(html)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    n = build(sys.argv[1])
    print("생성: %s (%d bytes)" % (sys.argv[1], n))
