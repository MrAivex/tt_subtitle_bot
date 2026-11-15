"""miniapp/auth.py — проверка initData MAX и подпись ссылок на медиа."""
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import unquote

log = logging.getLogger("timing")


def auth_tokens(main_token: str) -> list:
    """В проде — только MAX_TOKEN. На тестовом стенде можно добавить MAX_EXTRA_TOKENS."""
    tokens = [main_token or ""]
    tokens += [t.strip() for t in os.getenv("MAX_EXTRA_TOKENS", "").split(",")]
    return [t for t in tokens if t]


class InitDataValidator:
    def __init__(self, tokens: list, max_age: int = 24 * 3600, debug: bool = False):
        self._tokens = tokens
        self._max_age = max_age
        self._debug = debug

    @staticmethod
    def _parse(raw: str):
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

    def _why(self, msg: str):
        if self._debug:
            log.warning(f"[AUTH] {msg}")

    def validate(self, raw: str):
        """Возвращает user_id или None."""
        pairs = self._parse(raw)
        if not pairs:
            self._why(f"initData пустая (len={len(raw or '')}) — открыто не из MAX?")
            return None

        hashes = [v for k, v in pairs if k == "hash"]
        if len(hashes) != 1:
            self._why(f"hash отсутствует или дублируется; ключи={[k for k, _ in pairs]}")
            return None

        got = hashes[0]
        body = sorted((k, v) for k, v in pairs if k != "hash")
        launch_params = "\n".join(f"{k}={v}" for k, v in body).encode()

        for tok in self._tokens:
            secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
            calc = hmac.new(secret, launch_params, hashlib.sha256).hexdigest()
            if hmac.compare_digest(calc, got):
                break
        else:
            self._why(f"подпись не сошлась ни с одним из {len(self._tokens)} токенов")
            return None

        d = dict(pairs)
        ts = int(d.get("auth_date") or 0)
        ts = ts / 1000 if ts > 1e11 else ts
        if time.time() - ts > self._max_age:
            self._why(f"initData просрочена: auth_date={ts}")
            return None
        try:
            return int(json.loads(d.get("user") or "{}")["id"])
        except Exception as e:
            self._why(f"не разобрал user: {type(e).__name__}")
            return None


class MediaTokenSigner:
    """Подпись для <video src> и ссылок скачивания — заголовок туда не поставить."""

    def __init__(self, secret: bytes):
        self._secret = secret

    def sign(self, job_id: str) -> str:
        return hmac.new(self._secret, job_id.encode(), hashlib.sha256).hexdigest()[:32]

    def verify(self, job_id: str, token: str) -> bool:
        return hmac.compare_digest(token or "", self.sign(job_id))
