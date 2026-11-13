"""API мини-приложения MAX. Подключение: register_miniapp(app) в main.py."""
import asyncio, hashlib, hmac, json, os, time, traceback, uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from aiohttp import web

from app import bot, engine
from config import (MAX_TOKEN, ADMIN_IDS, MAX_FILE_SIZE_BYTES, MAX_FULL_VIDEO_SEC,
                    MAX_HIGHLIGHTS, MAX_CLIPS_PER_REQUEST)
from database_max import async_session_max
from services_max import (get_or_create_user, can_process_video, increment_video_counter,
                          set_user_email, get_users_stats)
from link_downloader import detect_platform, download_audio_only, download_by_link, download_section
from payments import create_payment
from subscriptions import SUBSCRIPTIONS



import logging
log = logging.getLogger("timing")

SCAN_SLOTS = asyncio.Semaphore(2)
PREVIEW_SLOTS = asyncio.Semaphore(2)   # ← новый
RENDER_SLOTS = asyncio.Semaphore(1)
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")


class ApiError(Exception):
    def __init__(self, msg, code=400):
        self.msg, self.code = msg, code


# ---------- авторизация: проверка initData ----------
def _webapp_secrets():
    t = (MAX_TOKEN or "").encode()
    return [
        ("telegram",  hmac.new(b"WebAppData", t, hashlib.sha256).digest()),
        ("reverse",   hmac.new(t, b"WebAppData", hashlib.sha256).digest()),
        ("raw_token", t),
        ("sha_token", hashlib.sha256(t).digest()),
    ]


# ---------- авторизация: проверка initData (dev.max.ru → Валидация данных) ----------

def _auth_tokens():
    """Токены, чьей подписью может быть подписана initData.
    В проде — только MAX_TOKEN. На тестовом стенде можно добавить свои же
    токены через MAX_EXTRA_TOKENS (через запятую), чтобы вход работал
    из любого твоего бота. В прод-окружении переменная не задаётся."""
    tokens = [MAX_TOKEN or ""]
    tokens += [t.strip() for t in os.getenv("MAX_EXTRA_TOKENS", "").split(",")]
    return [t for t in tokens if t]


def _parse_init_data(raw: str):
    """Пары initData. Значения декодируются как decodeURIComponent (unquote),
    а НЕ как form-data (unquote_plus): литеральный '+' остаётся плюсом.
    MAX отдаёт имена вида 'White+and+Black' — на этом parse_qsl ломал подпись."""
    s = raw or ""
    if "WebAppData=" in s:                      # если пришёл весь фрагмент URL
        s = s.split("WebAppData=", 1)[1]
        s = s.split("&WebAppPlatform", 1)[0].split("#", 1)[0]
        s = unquote(s)                          # снять внешний слой кодирования
    pairs, seen = [], set()
    for part in s.split("&"):
        if not part:
            continue
        k, _, v = part.partition("=")
        k, v = unquote(k), unquote(v)
        if k in seen:                           # по доке: каждый параметр ровно один раз
            return None
        seen.add(k)
        pairs.append((k, v))
    return pairs


def validate_init_data(raw: str, max_age: int = 24 * 3600):
    """Возвращает user_id или None."""
    pairs = _parse_init_data(raw)
    if not pairs:
        return None
    hashes = [v for k, v in pairs if k == "hash"]
    if len(hashes) != 1:                        # по доке: hash ровно один
        return None
    got = hashes[0]
    body = sorted((k, v) for k, v in pairs if k != "hash")
    launch_params = "\n".join(f"{k}={v}" for k, v in body).encode()

    matched = False
    for tok in _auth_tokens():
        secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, launch_params, hashlib.sha256).hexdigest()
        if hmac.compare_digest(calc, got):
            matched = True
            break
    if not matched:
        if os.getenv("AUTH_DEBUG") == "1":      # только ключи, без персональных данных
            log.warning(f"[AUTH] подпись не сошлась; ключи={[k for k, _ in body]}, hash={got[:12]}…")
        return None

    d = dict(pairs)
    ts = int(d.get("auth_date") or 0)
    ts = ts / 1000 if ts > 1e11 else ts         # дока: секунды; подстрахуемся от мс
    if time.time() - ts > max_age:
        return None
    try:
        return int(json.loads(d.get("user") or "{}")["id"])
    except Exception:
        return None


@web.middleware
async def _mw(request, handler):
    try:
        uid = validate_init_data(request.headers.get("X-Init-Data", ""))
        if not uid:
            raise ApiError("Открой приложение из MAX", 401)
        request["uid"] = uid
        return await handler(request)
    except ApiError as e:
        return web.json_response({"error": e.msg}, status=e.code)
    except web.HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return web.json_response({"error": f"{type(e).__name__}: {str(e)[:150]}"}, status=500)


# ---------- задачи ----------
@dataclass
class Job:
    id: str
    user_id: int
    chat_id: int
    source_url: str = ""
    path: str = ""
    duration: float = 1.0
    moments: list = field(default_factory=list)
    status: str = "scanning"      # scanning | ready | rendering | done | error
    progress: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    ts: float = field(default_factory=time.time)
    seen: bool = False            # клиент уже получил финальный статус (done/error)

    def public(self):
        return {k: getattr(self, k) for k in
                ("id", "status", "progress", "done", "total", "error", "duration", "moments")}


JOBS: dict = {}


def _rm(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


async def _user(uid):
    async with async_session_max() as s:
        return await get_or_create_user(s, uid)


async def _new_job(uid) -> Job:
    user = await _user(uid)
    if not user.chat_id:
        raise ApiError("Сначала нажми «Старт» в чате с ботом")
    if uid not in ADMIN_IDS and not can_process_video(user):
        raise ApiError("Видео на сегодня закончились. Оформи подписку в профиле.", 403)
    now = time.time()
    for k, j in list(JOBS.items()):
        if j.user_id == uid and (j.status == "rendering"
                                 or (j.status == "scanning" and now - j.ts < 1800)):
            raise ApiError("Предыдущая задача ещё выполняется — дождись окончания", 409)
        if j.user_id == uid or (now - j.ts > 6 * 3600 and j.status != "rendering"):
            _rm(j.path)
            JOBS.pop(k, None)
    job = Job(id=uuid.uuid4().hex[:10], user_id=uid, chat_id=user.chat_id)
    JOBS[job.id] = job
    os.makedirs("downloads", exist_ok=True)
    return job


def _job_of(request) -> Job:
    job = JOBS.get(request.match_info["id"])
    if not job or job.user_id != request["uid"]:
        raise ApiError("Задача не найдена", 404)
    return job


async def _charge(job: Job) -> bool:
    """Списывает попытку, возвращает is_premium."""
    async with async_session_max() as s:
        user = await get_or_create_user(s, job.user_id, job.chat_id)
        premium = user.active_sub != "default"
        if job.user_id not in ADMIN_IDS:
            await increment_video_counter(user, s)
    return premium


# ---------- сканирование ----------
async def _scan(job: Job, url: str = ""):
    try:
        async with SCAN_SLOTS:
            if url:
                job.progress = "Качаю звук"
                job.path = f"downloads/max_{job.user_id}_{job.id}.wav"
                await download_audio_only(url, job.path)
                job.progress = "Ищу громкие моменты"
                res = await asyncio.to_thread(engine.scan_audio_wav, job.path, MAX_HIGHLIGHTS)
            else:
                job.progress = "Ищу громкие моменты"
                res = await asyncio.to_thread(engine.scan_highlights, job.path, MAX_HIGHLIGHTS)
        job.duration = max(res["duration"], 1.0)
        job.moments = res["moments"]
        job.status = "ready"
    except Exception as e:
        traceback.print_exc()
        job.status, job.error = "error", f"{type(e).__name__}: {str(e)[:150]}"
        _rm(job.path)


# ---------- нарезка / полные субтитры ----------
async def _render(job: Job, mode: str, idxs: list, subs: bool, vertical: bool):
    outs, keep = [], False
    try:
        async with RENDER_SLOTS:
            job.status, job.done, job.error = "rendering", 0, ""
            if mode == "full":
                job.total = 1
                if await asyncio.to_thread(engine.get_video_duration, job.path) > MAX_FULL_VIDEO_SEC:
                    keep = True
                    raise ApiError(f"Видео длиннее {MAX_FULL_VIDEO_SEC // 60} минут. "
                                   "Для полных субтитров это слишком много, но хайлайты можно.")
                premium = await _charge(job)
                if job.source_url and job.path.endswith(".wav"):
                    job.progress = "Качаю полное видео"
                    full = await download_by_link(job.source_url, job.path[:-4] + ".mp4")
                    _rm(job.path)
                    job.path = full
                if subs:
                    job.progress = "Накладываю субтитры"
                    r = await asyncio.to_thread(engine.process_video, job.path, str(job.user_id), premium)
                    outs.append(r["video_path"])
                    job.progress = "Отправляю в чат"
                    if not await bot.send_video(job.chat_id, final, caption=f"✅ Клип #{n}"):
                        raise RuntimeError("не удалось отправить клип") 
                    if r.get("srt_path"):
                        txt = r["srt_path"][:-4] + ".txt"
                        os.replace(r["srt_path"], txt)
                        outs.append(txt)
                        await bot.send_document(job.chat_id, txt, caption="📄 Файл субтитров")
                else:
                    if not await bot.send_video(job.chat_id, final, caption=f"✅ Клип #{n}"):
                        raise RuntimeError("не удалось отправить клип")                   
            else:
                premium = await _charge(job)
                job.total = len(idxs)
                for n, idx in enumerate(idxs, 1):
                    m = job.moments[idx]
                    job.done, job.progress = n - 1, f"Клип {n} из {len(idxs)}"
                    clip = f"downloads/clip_{job.id}_{idx}.mp4"
                    if job.source_url:
                        clip = await download_section(job.source_url, m["start"], m["end"], clip)
                    else:
                        await asyncio.to_thread(engine.cut_clip, job.path, m["start"], m["end"], clip)
                    outs.append(clip)
                    got = await asyncio.to_thread(engine.get_video_duration, clip)
                    if got > (m["end"] - m["start"]) + 30:
                        raise RuntimeError(f"фрагмент скачался целиком ({got:.0f} с)")
                    final = clip
                    if subs:
                        r = await asyncio.to_thread(engine.process_video, clip, str(job.user_id),
                                                    premium, None, vertical)
                        final = r["video_path"]
                        outs += [final, r.get("srt_path")]
                    elif vertical:
                        final = clip[:-4] + "_v.mp4"
                        await asyncio.to_thread(engine.crop_to_vertical, clip, final)
                        outs.append(final)
                    if not await bot.send_video(job.chat_id, final, caption=f"✅ Клип #{n}"):
                        raise RuntimeError("не удалось отправить клип")
                    job.done = n
        job.status = "done"
    except ApiError as e:
        job.status, job.error = "ready", e.msg
    except Exception as e:
        traceback.print_exc()
        job.status, job.error = "error", f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        _rm(*outs)
        if job.status != "ready" and not keep:
            _rm(job.path)


# ---------- хендлеры ----------
async def api_me(request):
    uid = request["uid"]
    u = await _user(uid)
    return web.json_response({
        "is_admin": uid in ADMIN_IDS, "sub": u.active_sub, "limit": u.video_limit,
        "used": u.videos_used_today, "email": u.email or "",
        "expiry": u.subscription_expiry.strftime("%d.%m.%Y") if u.subscription_expiry else "",
        "subs": [{"id": k, "name": v["name"], "price": v["price"], "description": v["description"]}
                 for k, v in SUBSCRIPTIONS.items() if v["price"] > 0],
    })


async def api_scan(request):
    url = ((await request.json()).get("url") or "").strip()
    if not detect_platform(url):
        raise ApiError("Не узнаю ссылку. Подойдут YouTube, Twitch, TikTok, Google Drive и Яндекс.Диск.")
    job = await _new_job(request["uid"])
    job.source_url = url
    asyncio.create_task(_scan(job, url))
    return web.json_response(job.public())


async def api_upload(request):
    job = await _new_job(request["uid"])
    field_ = await (await request.multipart()).next()
    if field_ is None:
        JOBS.pop(job.id, None)
        raise ApiError("Файл не получен")
    name = (getattr(field_, "filename", "") or "").lower()
    if not name.endswith(VIDEO_EXT):
        JOBS.pop(job.id, None)
        raise ApiError("Нужен видеофайл: mp4, mov, avi, mkv или webm")
    job.path = f"downloads/max_{job.user_id}_{job.id}{os.path.splitext(name)[1]}"
    size = 0
    try:
        with open(job.path, "wb") as f:
            while chunk := await field_.read_chunk(1 << 20):
                size += len(chunk)
                if size > MAX_FILE_SIZE_BYTES:
                    raise ApiError("Файл больше 2.5 ГБ")
                f.write(chunk)
    except Exception:
        _rm(job.path)
        JOBS.pop(job.id, None)
        raise
    asyncio.create_task(_scan(job))
    return web.json_response(job.public())


async def api_job(request):
    job = _job_of(request)
    if job.status in ("done", "error"):
        job.seen = True
    return web.json_response(job.public())


async def api_active(request):
    """Текущая задача пользователя — чтобы приложение могло подхватить её после выхода."""
    mine = [j for j in JOBS.values() if j.user_id == request["uid"]]
    job = max(mine, key=lambda j: j.ts, default=None)
    if job and job.status in ("done", "error"):
        if job.seen:
            job = None            # финал уже показывали, второй раз не надо
        else:
            job.seen = True
    return web.json_response({"job": job.public() if job else None})


async def api_render(request):
    job = _job_of(request)
    body = await request.json()
    if job.status != "ready":
        raise ApiError("Задача сейчас занята", 409)
    mode = body.get("mode")
    idxs = sorted({int(i) for i in body.get("moments", [])})
    if mode == "highlights":
        if not idxs or any(not 0 <= i < len(job.moments) for i in idxs):
            raise ApiError("Выбери моменты")
        if len(idxs) > MAX_CLIPS_PER_REQUEST:
            raise ApiError(f"Можно выбрать не больше {MAX_CLIPS_PER_REQUEST}")
    elif mode != "full":
        raise ApiError("Неизвестный режим")
    job.status = "rendering"
    job.progress = "В очереди"
    asyncio.create_task(_render(job, mode, idxs, bool(body.get("subtitles", True)),
                                bool(body.get("vertical", False))))
    return web.json_response(job.public())


async def api_email(request):
    email = ((await request.json()).get("email") or "").strip()
    if "@" not in email or "." not in email:
        raise ApiError("Похоже, email неверный")
    async with async_session_max() as s:
        await get_or_create_user(s, request["uid"])
        await set_user_email(s, request["uid"], email)
    return web.json_response({"ok": True})


async def api_pay(request):
    sub_id = (await request.json()).get("sub_id")
    if sub_id not in SUBSCRIPTIONS or SUBSCRIPTIONS[sub_id]["price"] == 0:
        raise ApiError("Неизвестный тариф")
    user = await _user(request["uid"])
    if not user.email:
        raise ApiError("Сначала сохрани email — он нужен для чека")
    _, url = await create_payment(request["uid"], sub_id, user.email, platform="max")
    return web.json_response({"url": url})


async def api_stats(request):
    if request["uid"] not in ADMIN_IDS:
        raise ApiError("Недостаточно прав", 403)
    total, paid, with_email = await get_users_stats()
    return web.json_response({"total": total, "paid": paid, "with_email": with_email})


async def _index(request):
    return web.FileResponse(INDEX_PATH, headers={"Cache-Control": "no-cache"})


def register_miniapp(app: web.Application):
    print(f"[MINIAPP] index.html: {INDEX_PATH} exists={os.path.exists(INDEX_PATH)}", flush=True)    
    api = web.Application(middlewares=[_mw])
    api.add_routes([
        web.get("/me", api_me), web.get("/active", api_active), web.post("/scan", api_scan), web.post("/upload", api_upload),
        web.get("/jobs/{id}", api_job), web.post("/jobs/{id}/render", api_render),
        web.post("/email", api_email), web.post("/pay", api_pay), web.get("/stats", api_stats),
    ])
    app.add_subapp("/api", api)
    app.router.add_get("/app", _index)
    app.router.add_get("/app/", _index)


def _cleanup_job(j: Job):
    _rm(j.path)  # ← было rm
    for i in range(len(j.moments)):
        _rm(f"downloads/prev_{j.id}_{i}.mp4")
    for r in j.renders.values():
        _rm(r.get("path"))
