#!/usr/bin/env python3
"""webapp/fetch_fonts.py — локализует шрифты Nunito/Rubik (Google Fonts).

Зачем: index.html грузит шрифты с fonts.googleapis.com в неблокирующем режиме.
Где Google доступен — шрифты просто догружаются. Где нет — сайт живёт на
системных шрифтах. Этот скрипт делает «шрифты как в дизайне» офлайн:
скачивает woff2 (cyrillic+latin) и собирает static/css/fonts.css, в котором
шрифты зашиты как data-URI, затем подключает его в index.html.

Запуск (из корня репозитория, рядом с .env):
    python3 webapp/fetch_fonts.py

Прокси: если в .env есть DOWNLOAD_PROXY (или TG_API_PROXY), скачивание идёт
через него — так же, как качает видео yt-dlp. Формат: http://…, socks5://…,
socks5h://… (для socks нужен PySocks — уже в requirements.txt).
Повторный запуск безопасен (идемпотентен): просто обновит fonts.css.
"""
import base64
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # корень репозитория
OUT_CSS = os.path.join(ROOT, "webapp", "static", "css", "fonts.css")
INDEX = os.path.join(ROOT, "webapp", "index.html")
CSS_URL = ("https://fonts.googleapis.com/css2"
           "?family=Nunito:wght@600;700;800&family=Rubik:wght@600;800;900&display=swap")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
KEEP_SUBSETS = {"cyrillic", "latin"}  # русский интерфейс + латиница
LINK_TAG = '<link rel="stylesheet" href="/static/css/fonts.css">'


def load_env(path=".env"):
    """Мини-парсер .env без python-dotenv (чтобы работало всегда)."""
    env = {}
    if not os.path.exists(path):
        return env
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def setup_proxy(env):
    """DOWNLOAD_PROXY/TG_API_PROXY → сетевой стек urllib'а."""
    raw = env.get("DOWNLOAD_PROXY") or env.get("TG_API_PROXY") or ""
    if not raw:
        print("Прокси не задан — иду напрямую (Google должен быть доступен)")
        return
    if raw.startswith("http://") or raw.startswith("https://"):
        os.environ["http_proxy"] = raw
        os.environ["https_proxy"] = raw
        print(f"Прокси http: {raw.split('@')[-1]}")
        return
    # socks5:// socks5h:// — через PySocks
    try:
        import socks
    except ImportError:
        print(" socks-прокси указан, но PySocks не установлен (pip install PySocks)")
        sys.exit(1)
    m = re.match(r"socks5h?://(?:([^:@/]+):([^@/]+)@)?([^:/]+)(?::(\d+))?", raw)
    if not m:
        print(f"Не понял формат прокси: {raw}")
        sys.exit(1)
    user, pwd, host, port = m.groups()
    socks.set_default_proxy(socks.SOCKS5, host, int(port or 1080),
                            username=user, password=pwd)
    import socket
    socket.socket = socks.socksocket
    print(f"Прокси socks5: {host}:{port or 1080}")


def fetch(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=30).read()


def main():
    env = load_env(os.path.join(ROOT, ".env"))
    if not env:
        env = load_env(".env")
    setup_proxy(env)

    print(f"Качаю css: {CSS_URL}")
    css = fetch(CSS_URL).decode("utf-8")
    blocks = re.findall(r'/\*\s*([a-z-]+)\s*\*/\s*(@font-face\s*\{[^}]+\})', css)
    if not blocks:
        print("Google не отдал @font-face — проверь доступность/прокси")
        sys.exit(1)

    out, total, n = [], 0, 0
    for subset, face in blocks:
        if subset not in KEEP_SUBSETS:
            continue
        m = re.search(r"src:\s*url\((https://[^)]+)\)\s*format\('woff2'\)", face)
        if not m:
            continue
        data = fetch(m.group(1))
        b64 = base64.b64encode(data).decode("ascii")
        fam = re.search(r"font-family:\s*'([^']+)'", face).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", face).group(1)
        urange = re.search(r"unicode-range:\s*([^;]+);", face).group(1)
        out.append(
            f"/* {fam} {weight} — {subset} ({len(data)//1024} КБ) */\n"
            "@font-face{\n"
            f"font-family:'{fam}';font-style:normal;font-weight:{weight};font-display:swap;\n"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');\n"
            f"unicode-range:{urange};\n}}\n")
        print(f"  {fam} {weight} {subset}: {len(data)//1024} КБ")
        total += len(data)
        n += 1

    if not n:
        print("Не скачалось ни одного шрифта — проверь доступность/прокси")
        sys.exit(1)

    header = ("/* fonts.css — Nunito/Rubik, cyrillic+latin, woff2 зашиты как data-URI.\n"
              "   Сгенерировано webapp/fetch_fonts.py; обновить — просто запустить его снова. */\n\n")
    with open(OUT_CSS, "w", encoding="utf-8") as f:
        f.write(header + "".join(out))
    print(f"Готово: {n} шрифтов, {total//1024} КБ woff2 → {OUT_CSS}")

    # подключаем в index.html, если ещё не подключено
    html = open(INDEX, encoding="utf-8").read()
    if "/static/css/fonts.css" not in html:
        anchor = '<link rel="stylesheet" href="/static/css/base.css">'
        if anchor in html:
            html = html.replace(anchor, LINK_TAG + "\n" + anchor, 1)
            with open(INDEX, "w", encoding="utf-8") as f:
                f.write(html)
            print("index.html: подключил /static/css/fonts.css перед base.css")
        else:
            print("index.html: не нашёл точку вставки — добавь вручную " + LINK_TAG)
    else:
        print("index.html: fonts.css уже подключён")


if __name__ == "__main__":
    main()
