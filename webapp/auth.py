"""webapp/auth.py — вход из MAX, из Telegram и с сайта; подписи медиа и сессий.

Схема подписи initData у MAX и Telegram одинаковая:
    secret  = HMAC_SHA256(key="WebAppData", data=<токен бота>)
    hash    = HMAC_SHA256(key=secret,  data=check_string)
Отличия мелкие:
    MAX    — initData обёрнут в «WebAppData=…», значения в check_string декодированы (unquote);
    TG     — initData это обычная query string, значения в check_string тоже декодированы
             (parse_qsl), как в эталонных реализациях aiogram / pyTelegramBotAPI.
Различные токены → разные подписи, поэтому перепутать платформы невозможно.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl, unquote

log = logging.getLogger("timing")


class MultiInitDataValidator:
    """Возвращает (platform, ext_id, display_name) или None."""

    def __init__(self, max_tokens: list, tg_token: str,
                 max_age: int = 24 * 3600, debug: bool = False):
        self._max_tokens = [t for t in max_tokens if t]
        self._tg_token = tg_token or ""
        self._max_age = max_age
        self._debug = debug

    def _why(self, msg: str):
        if self._debug:
            log.warning(f"[AUTH] {msg}")

    def validate(self, raw: str, platform: str = ""):
        """platform — подсказка с клиента (X-Platform). Пусто — пробуем обе."""
        order = ("max", "tg")
        if platform == "tg":
            order = ("tg",)
        elif platform == "max":
            order = ("max",)
        for cand in order:
            got = self._validate_max(raw) if cand == "max" else self._validate_tg(raw)
            if got is not None:
                return cand, got[0], got[1]
        return None

    # ---------- MAX ----------

    def _validate_max(self, raw: str):
        pairs = self._parse_max(raw)
        if not pairs:
            self._why(f"MAX: initData пустая (len={len(raw or '')})")
            return None
        got = [v for k, v in pairs if k == "hash"]
        if len(got) != 1:
            self._why(f"MAX: hash отсутствует; ключи={[k for k, _ in pairs]}")
            return None
        body = sorted((k, v) for k, v in pairs if k != "hash")
        launch_params = "\n".join(f"{k}={v}" for k, v in body).encode()
        for tok in self._max_tokens:
            secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
            calc = hmac.new(secret, launch_params, hashlib.sha256).hexdigest()
            if hmac.compare_digest(calc, got[0]):
                d = dict(pairs)
                ts = self._auth_date(d)
                if ts is None or time.time() - ts > self._max_age:
                    self._why(f"MAX: initData просрочена (auth_date={ts})")
                    return None
                return self._user(d)
        self._why(f"MAX: подпись не сошлась ({len(self._max_tokens)} токенов)")
        return None

    @staticmethod
    def _parse_max(raw: str):
        """Значения декодируются как decodeURIComponent: литеральный '+' остаётся плюсом."""
        s = raw or ""
        if "WebAppData=" in s:
            s = s.split("WebAppData=", 1)[1]
            s = s.split("&WebAppPlatform", 1)[0].split("#", 1)[0]
            s = unquote(s)
        pairs, seen = [], set()
        for part in s.split("&"):
            if not part:
                continue
            k, _, v = part.partition("=")
            k, v = unquote(k), unquote(v)
            if k in seen:
                return None
            seen.add(k)
            pairs.append((k, v))
        return pairs

    # ---------- Telegram ----------

    def _validate_tg(self, raw: str):
        if not raw or "WebAppData=" in raw:
            return None                    # TG присылает обычную query string
        pairs = parse_qsl(raw, keep_blank_values=True)
        if not pairs:
            self._why(f"TG: initData не парсится (len={len(raw or '')})")
            return None
        d = dict(pairs)
        if "hash" not in d or "user" not in d:
            self._why("TG: нет hash/user")
            return None
        # check_string — из ДЕКОДИРОВАННЫХ значений (так подписывает сам Telegram;
        # ровно так делают aiogram и pyTelegramBotAPI: parse_qsl + sorted)
        check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()) if k != "hash").encode()
        secret = hmac.new(b"WebAppData", self._tg_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, d["hash"]):
            self._why("TG: подпись не сошлась")
            return None
        ts = self._auth_date(d)
        if ts is None or time.time() - ts > self._max_age:
            self._why(f"TG: initData просрочена (auth_date={ts})")
            return None
        try:
            u = json.loads(d["user"])          # parse_qsl уже декодировал значение
            return str(u["id"]), self._display_name(u)
        except Exception as e:
            self._why(f"TG: не разобрал user: {type(e).__name__}")
            return None

    # ---------- общие ----------

    @staticmethod
    def _auth_date(d: dict):
        try:
            ts = int(d.get("auth_date") or 0)
        except (TypeError, ValueError):
            return None
        return ts / 1000 if ts > 1e11 else ts

    @staticmethod
    def _display_name(u: dict) -> str:
        return str(u.get("name") or u.get("first_name") or u.get("username") or "")

    def _user(self, d: dict):
        try:
            u = json.loads(d.get("user") or "{}")
            return str(u["id"]), self._display_name(u)
        except Exception as e:
            self._why(f"MAX: не разобрал user: {type(e).__name__}")
            return None


class SessionTokens:
    """Токен сессии сайта: «uid.exp.подпись». Без состояния, живёт WEB_SESSION_TTL."""

    def __init__(self, secret: bytes, ttl: int):
        self._secret = secret
        self._ttl = ttl

    def issue(self, uid: int) -> str:
        exp = int(time.time()) + self._ttl
        payload = f"{uid}.{exp}"
        sig = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{payload}.{sig}"

    def verify(self, token: str):
        try:
            uid_s, exp_s, sig = (token or "").split(".")
            uid, exp = int(uid_s), int(exp_s)
            if exp < time.time():
                return None
            payload = f"{uid}.{exp}"
            calc = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()[:32]
            if hmac.compare_digest(calc, sig):
                return uid
        except Exception:
            pass
        return None


class MediaTokenSigner:
    """Подпись для <video src> и ссылок скачивания — заголовок туда не поставить."""

    def __init__(self, secret: bytes):
        self._secret = secret

    def sign(self, job_id: str) -> str:
        return hmac.new(self._secret, job_id.encode(), hashlib.sha256).hexdigest()[:32]

    def verify(self, job_id: str, token: str) -> bool:
        return hmac.compare_digest(token or "", self.sign(job_id))
