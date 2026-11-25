# Единое веб-приложение (webapp) — сайт + миниapp MAX + миниapp Telegram

Одна и та же фронтенд- и бэкенд-логика работает сразу в трёх режимах:

| Откуда открыто | Как авторизуется | Кто такой пользователь |
|---|---|---|
| Миниapp MAX | `initData` MAX (заголовок `X-Init-Data`) | `identities_web (max, id)` → `users_web` |
| Миниapp Telegram (кнопка в боте) | `initData` Telegram (заголовок `X-Init-Data`) | `identities_web (tg, id)` → `users_web` |
| Обычный браузер (сайт) | имя+пароль → токен сессии (`X-Site-Token`, 30 дней) | `identities_web (site, username)` → `users_web` |

Аккаунт один: подписка, лимиты и статистика — в `users_web`; платформенные id —
это лишь «привязки». Связать аккаунты между платформами можно кодом из профиля
(«Получить код привязки» на одной платформе → «Привязать по коду» на другой).

Отдельно от сайта работают и чат-режимы: MAX-бот (как раньше) и TG-бот
(ссылки/файлы прямо в чате) — биллинг у них тот же единый `users_web`.

```
                        ┌────────────────────────────┐
                        │  asr_service.py :8090      │  один faster-whisper
                        └──────────┬─────────────────┘  для всех процессов
        ┌──────────────┬───────────┼──────────────┬─────────────┐
        │              │           │              │             │
  main.py:8081   web_main.py:8084  tg_main.py:8083   тест:8082   (test .env)
  MAX-бот+       сайт: миниapp     TG-бот: /start,  тест-бот +   тест-копия сайта
  старый миниapp MAX/TG/логин      inline-нарезка   старый миниapp (свои таблицы
                 (webapp/)          + кнопка на сайт              в тестовой БД)
                                   (webapp)
```

## Файлы

```
web_main.py              — вход сайта (порт 8084)
database_web.py           — users_web, identities_web, link_codes_web
services_web.py           — привязки, вход на сайте, коды, подписки, статистика
web_billing.py            — UnifiedBilling (контракт miniapp.Billing)
webapp/__init__.py       — композиция приложения
webapp/auth.py           — проверка initData MAX и TG, сессии сайта, подпись медиа
webapp/middleware.py     — из запроса → единый uid (initData TG / MAX / токен сайта)
webapp/clips_handlers.py — те же эндпоинты задач, что у миниapp MAX
webapp/profile_handlers.py — профиль, email, оплата, статистика
webapp/site_handlers.py  — /site/register, /site/login, /link/start, /link/apply
webapp/index.html + webapp/static/ — фронтенд (копия миниapp MAX + вход/привязка)
```

## Новая база (та же PostgreSQL, новые таблицы)

```
users_web        — id, username?, password_hash?, chat_id?, email, подписка, лимиты
identities_web   — (platform: max|tg|site, ext_id) → user_id, UNIQUE(platform, ext_id)
link_codes_web   — одноразовые 6-значные коды привязки, 10 минут
```

Первый вход MAX-пользователя переносит его подписку/статистику из старой
`users_max` (чтобы платные не потеряли подписку при переходе на сайт). Оплаты
через сайт приходят с `platform="web"` и активируются в `users_web`; оплаты через
старого MAX-бота (`platform="max"`) применяются и к `users_max`, и к единой базе,
если человек там уже есть. Порядок запуска cron: сброс дневных лимитов 00:30 и
проверка подписок 01:00 (МСК) — у web-процесса, как раньше у MAX-процесса.

## .env (новые переменные)

```
WEB_PORT=8084
WEB_PUBLIC_URL=https://app.subtitle-bot.ru/      # https обязателен для миниapp-кнопок
WEB_SESSION_SECRET=<openssl rand -hex 24>        # сессии сайта и подпись медиа-ссылок
TG_WEBAPP_URL=https://app.subtitle-bot.ru/       # кнопка «Открыть приложение» в TG
# WEB_SESSION_TTL=2592000                        # 30 дней (по умолчанию)
```

Остальное — как в релизе общего ASR (`ASR_URL`, `ASR_TOKEN`, `TG_BOT_TOKEN`,
`TG_WEBHOOK_URL`, `TG_WEBHOOK_SECRET`).

## systemd

`/etc/systemd/system/web-bot.service`:

```ini
[Unit]
Description=tt_subtitle_bot — unified web app
After=network.target postgresql.service asr.service

[Service]
Type=simple
WorkingDirectory=/opt/tt-bot        # обязательно: downloads/ — относительные пути
EnvironmentFile=/opt/tt-bot/.env
ExecStart=/opt/tt-bot/venv/bin/python web_main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Запуск: `systemctl daemon-reload && systemctl enable --now web-bot.service`

## nginx

Сайту нужен отдельный HTTPS-домен (фронтенд ходит по абсолютным путям `/api/...`):

```nginx
server {
    server_name app.subtitle-bot.ru;
    client_max_body_size 2560m;            # загрузка больших видео, как у миниapp MAX
    proxy_read_timeout 600s;

    location / {
        proxy_pass http://127.0.0.1:8084;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Порядок запуска

1. `asr.service` (если ещё не запущен) — общий Whisper.
2. В .env добавить `WEB_*` и `TG_WEBAPP_URL`, домен направить в nginx.
3. `systemctl start web-bot` — сайт и его таблицы создаются сами (`init_db_web`).
4. Проверить сайт в браузере: https://app.subtitle-bot.ru/ — регистрация → приложение.
5. `systemctl start tg-bot` — /start в TG даёт кнопку «Открыть приложение»
   (миниapp открывается в Telegram, initData валидируется с `TG_BOT_TOKEN`).
6. Когда будете готовы перевести MAX: в консоли MAX поменять адрес миниapp
   на `https://app.subtitle-bot.ru/` (код менять не нужно: initData MAX
   валидируется тем же сайтом, старый миниapp на 8081 остаётся как запасной).

## Откат

- Сайт: `systemctl stop web-bot` и убрать домен из nginx — всё остальное работает.
- TG: убрать кнопку (`TG_WEBAPP_URL=` пусто) — останется чат-режим с inline-кнопками.
- MAX: вернуть адрес миниapp в консоли MAX на `https://subtitle-bot.ru/app/` (8081).
- Таблицы `users_web`/`identities_web` остаются в базе, старые процессы их не трогают.

## Ограничения и заметки

- Оплата через сайт — та же ЮKassa (`platform="web"`, return на сайт);
  email для чека обязателен, как и раньше.
- Привязка аккаунтов сливает лимиты/подписку в пользу аккаунта, создавшего код;
  пароль сайта переносится, только если у владельца кода своего нет.
- На сайте и в миниapp TG — те же лимиты Telegram Bot API при отправке клипов
  сообщением, но сайт их обходит: файлы до 2.5 ГБ загружаются и скачиваются
  через браузер.
- Сессия сайта живёт 30 дней (`WEB_SESSION_TTL`); просроченная — снова экран входа.
