"""Пользователи и привязки единой базы (users_web) — то же, что services_max для users_max.

Ключевая идея: id в MAX, id в TG и имя на сайте — это НЕ пользователь, а привязка (identity).
Пользователь — строка users_web, и у него одна подписка и одни лимиты на все платформы.

Схема HMAC у initData MAX и Telegram совпадает (см. webapp/auth.py), поэтому «вход»
на всех платформах одинаковый: initData мессенджера → identity → users_web.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_IDS, TG_ADMIN_IDS
from database_web import UserWeb, UserIdentity, LinkCode, async_session_web
from subscriptions import DEFAULT_SUB, get_subscription
# поля лимитов у UserMax и UserWeb одинаковые — эти функции работают с обеими моделями
from services_max import can_process_video, increment_video_counter  # noqa: F401 — реэкспорт

PLATFORMS = ("max", "tg", "site")

# ---------- сайт: пароли ----------

PBKDF2_ITERS = 200_000
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
LINK_TTL_SEC = 600          # код привязки живёт 10 минут


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------- пользователи ----------

async def get_user_web(session: AsyncSession, uid: int) -> UserWeb | None:
    result = await session.execute(select(UserWeb).where(UserWeb.id == uid))
    return result.scalar_one_or_none()


async def get_or_create_user_web(session: AsyncSession, uid: int) -> UserWeb:
    user = await get_user_web(session, uid)
    if user is None:
        sub = get_subscription(DEFAULT_SUB)
        user = UserWeb(id=uid, active_sub=DEFAULT_SUB, video_limit=sub["video_limit"],
                       videos_used_today=0, total_videos_processed=0)
        session.add(user)
        await session.commit()
    return user


async def set_user_email_web(session: AsyncSession, uid: int, email: str) -> bool:
    user = await get_user_web(session, uid)
    if not user:
        return False
    user.email = email
    await session.commit()
    return True


# ---------- привязки (identity) ----------

async def _get_identity(session: AsyncSession, platform: str, ext_id: str) -> UserIdentity | None:
    result = await session.execute(
        select(UserIdentity).where(UserIdentity.platform == platform,
                                    UserIdentity.ext_id == str(ext_id)))
    return result.scalar_one_or_none()


async def resolve_identity(platform: str, ext_id, display_name: str = None,
                            chat_id: int = None) -> UserWeb:
    """Платформенный id → единый пользователь.

    Первое появление id: создаём пользователя и привязку. Для MAX заодно переносим
    подписку/статистику из старой таблицы users_max, чтобы платные пользователи
    бота не потеряли подписку при переходе на сайт.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"Неизвестная платформа: {platform}")
    async with async_session_web() as s:
        ident = await _get_identity(s, platform, str(ext_id))
        if ident is None:
            user = await _new_user_for(s, platform, str(ext_id))
            s.add(UserIdentity(user_id=user.id, platform=platform,
                              ext_id=str(ext_id), display_name=display_name or ""))
            await s.commit()
            return user

        user = await get_user_web(s, ident.user_id)
        if user is None:
            # редкий случай: строка пользователя исчезла (например, после слияния аккаунтов) — заводим заново
            user = await _new_user_for(s, platform, str(ext_id))
            ident.user_id = user.id
            ident.display_name = display_name or ident.display_name or ""
            await s.commit()
            return user

        changed = False
        if display_name and (ident.display_name or "") != display_name:
            ident.display_name = display_name
            changed = True
        if chat_id and user and user.chat_id != chat_id:
            user.chat_id = chat_id
            changed = True
        if changed:
            await s.commit()
        return user


async def _new_user_for(session: AsyncSession, platform: str, ext_id: str) -> UserWeb:
    sub = get_subscription(DEFAULT_SUB)
    fields = dict(active_sub=DEFAULT_SUB, video_limit=sub["video_limit"],
                  videos_used_today=0, total_videos_processed=0)
    if platform == "max":
        # человек уже пользовался MAX-ботом? Переносим его данные из users_max.
        try:
            from database_max import async_session_max, UserMax
            async with async_session_max() as smax:
                row = (await smax.execute(
                    select(UserMax).where(UserMax.user_id == int(ext_id)))).scalar_one_or_none()
                if row is not None:
                    fields.update(active_sub=row.active_sub, video_limit=row.video_limit,
                                  videos_used_today=row.videos_used_today,
                                  total_videos_processed=row.total_videos_processed,
                                  subscription_expiry=row.subscription_expiry,
                                  email=row.email, chat_id=row.chat_id)
        except Exception:
            pass          # старой таблицы нет/доступа нет — просто новый пользователь
    user = UserWeb(**fields)
    session.add(user)
    await session.flush()          # нужен user.id до вставки привязки
    return user


async def list_identities(uid: int) -> list[UserIdentity]:
    async with async_session_web() as s:
        result = await s.execute(
            select(UserIdentity).where(UserIdentity.user_id == uid).order_by(UserIdentity.id))
        return list(result.scalars().all())


async def is_admin_web(uid: int) -> bool:
    """Админ — если хоть одна привязка пользователя входит в MAX_ADMIN_IDS/TG_ADMIN_IDS."""
    async with async_session_web() as s:
        result = await s.execute(select(UserIdentity).where(UserIdentity.user_id == uid))
        for i in result.scalars().all():
            try:
                ext = int(i.ext_id)
            except (TypeError, ValueError):
                continue
            if i.platform == "max" and ext in ADMIN_IDS:
                return True
            if i.platform == "tg" and ext in TG_ADMIN_IDS:
                return True
        return False


# ---------- сайт: регистрация и вход ----------

async def register_site_user(username: str, password: str) -> UserWeb:
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("Имя: 3–32 символа, латиница, цифры, точка, дефис или _")
    if len(password or "") < 6:
        raise ValueError("Пароль: минимум 6 символов")
    async with async_session_web() as s:
        ident = await _get_identity(s, "site", username)
        if ident is not None:
            raise ValueError("Такое имя уже занято")
        sub = get_subscription(DEFAULT_SUB)
        user = UserWeb(username=username, password_hash=hash_password(password),
                       active_sub=DEFAULT_SUB, video_limit=sub["video_limit"],
                       videos_used_today=0, total_videos_processed=0)
        s.add(user)
        await s.flush()
        s.add(UserIdentity(user_id=user.id, platform="site",
                           ext_id=username, display_name=username))
        await s.commit()
        return user


async def login_site_user(username: str, password: str) -> UserWeb:
    async with async_session_web() as s:
        ident = await _get_identity(s, "site", (username or "").strip())
        if ident is None:
            raise ValueError("Неверное имя или пароль")
        user = await get_user_web(s, ident.user_id)
        if user is None or not user.password_hash or not verify_password(password, user.password_hash):
            raise ValueError("Неверное имя или пароль")
        return user


# ---------- привязка аккаунтов ----------

async def issue_link_code(uid: int) -> tuple[str, int]:
    """Шесть цифр, действуют LINK_TTL_SEC, одноразовые."""
    async with async_session_web() as s:
        await s.execute(delete(LinkCode).where(LinkCode.expires_at < datetime.now()))
        for _ in range(5):
            code = f"{secrets.randbelow(1_000_000):06d}"
            exists = (await s.execute(select(LinkCode).where(LinkCode.code == code))).scalar_one_or_none()
            if exists is None:
                s.add(LinkCode(code=code, user_id=uid,
                               expires_at=datetime.now() + timedelta(seconds=LINK_TTL_SEC)))
                await s.commit()
                return code, LINK_TTL_SEC
    raise RuntimeError("Не получилось создать код — попробуй ещё раз")


async def apply_link_code(code: str, source_uid: int) -> UserWeb:
    """Аккаунт source_uid вливается в аккаунт владельца кода.

    Подписка, лимиты и статистика остаются у владельца кода (его аккаунт «главный»);
    все привязки source_uid переезжают к нему. Пароль и email забираем, если у владельца своих нет.
    """
    async with async_session_web() as s:
        lc = (await s.execute(
            select(LinkCode).where(LinkCode.code == (code or "").strip()))).scalar_one_or_none()
        if lc is None or lc.used or lc.expires_at < datetime.now():
            raise ValueError("Код неверный или истёк")
        target = await get_user_web(s, lc.user_id)
        source = await get_user_web(s, source_uid)
        if target is None or source is None:
            raise ValueError("Аккаунт не найден")
        if target.id == source.id:
            raise ValueError("Это уже один аккаунт")

        lc.used = True
        await s.execute(update(UserIdentity)
                        .where(UserIdentity.user_id == source.id)
                        .values(user_id=target.id))
        if not target.password_hash and source.password_hash:
            target.password_hash = source.password_hash
            target.username = target.username or source.username
        if not target.email and source.email:
            target.email = source.email
        target.total_videos_processed += source.total_videos_processed
        await s.delete(source)
        await s.commit()
        return target


# ---------- подписки и лимиты ----------

async def activate_subscription_web(session: AsyncSession, user_id: int, sub_id: str):
    """Активация подписки у единого пользователя (id — users_web.id, приходит из ЮKassa)."""
    sub = get_subscription(sub_id)
    if sub["price"] == 0:
        return None
    user = await get_user_web(session, user_id)
    if not user:
        return None
    duration = sub.get("duration_days", 0)
    now = datetime.now()
    base_date = now
    if user.subscription_expiry and user.subscription_expiry > now:
        base_date = user.subscription_expiry
    expiry = base_date + timedelta(days=duration) if duration > 0 else None

    user.active_sub = sub_id
    user.video_limit = sub["video_limit"]
    user.videos_used_today = 0
    user.subscription_expiry = expiry
    await session.commit()
    return {
        "sub_name": sub["name"],
        "expiry": expiry.strftime("%d.%m.%Y %H:%M") if expiry else "навсегда",
        "video_limit": sub["video_limit"],
    }


async def activate_subscription_web_by_max(max_uid: int, sub_id: str):
    """Человек платил через старый MAX-бот (users_max), а в сайт уже заходил —
    применяем ту же подписку и к его единому аккаунту."""
    async with async_session_web() as s:
        ident = await _get_identity(s, "max", str(max_uid))
        if ident is None:
            return None
        return await activate_subscription_web(s, ident.user_id, sub_id)


async def reset_all_daily_limits_web():
    async with async_session_web() as s:
        await s.execute(update(UserWeb).values(videos_used_today=0))
        await s.commit()


async def check_expired_subscriptions_web():
    async with async_session_web() as s:
        now = datetime.now()
        result = await s.execute(
            select(UserWeb).where(UserWeb.subscription_expiry.isnot(None),
                                  UserWeb.subscription_expiry < now))
        for user in result.scalars().all():
            default_sub = get_subscription(DEFAULT_SUB)
            user.active_sub = DEFAULT_SUB
            user.video_limit = default_sub["video_limit"]
            user.videos_used_today = 0
            user.subscription_expiry = None
        await s.commit()


async def get_users_stats_web():
    """(всего, с подпиской, с email, привязок max, привязок tg, аккаунтов сайта)."""
    async with async_session_web() as s:
        total = (await s.execute(select(func.count(UserWeb.id)))).scalar() or 0
        paid = (await s.execute(
            select(func.count(UserWeb.id)).where(UserWeb.active_sub != DEFAULT_SUB))).scalar() or 0
        with_email = (await s.execute(
            select(func.count(UserWeb.id)).where(UserWeb.email.isnot(None)))).scalar() or 0
        n_max = (await s.execute(
            select(func.count(UserIdentity.id)).where(UserIdentity.platform == "max"))).scalar() or 0
        n_tg = (await s.execute(
            select(func.count(UserIdentity.id)).where(UserIdentity.platform == "tg"))).scalar() or 0
        n_site = (await s.execute(
            select(func.count(UserIdentity.id)).where(UserIdentity.platform == "site"))).scalar() or 0
        return total, paid, with_email, n_max, n_tg, n_site
