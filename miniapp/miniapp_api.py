"""API мини-приложения MAX: превью клипов + скачивание без отправки в чат."""
import asyncio, hashlib, hmac, json, logging, os, time, traceback, uuid
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

log = logging.getLogger("timing")

SCAN_SLOTS = asyncio.Semaphore(2)
PREVIEW_SLOTS = asyncio.Semaphore(2)   # превью не должны занимать слоты сканирования
RENDER_SLOTS = asyncio.Semaphore(1)

VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")
SECRET = (MAX_TOKEN or "secret").encode()


class ApiError(Exception):
    def __init__(self, msg, code=400):
        self.msg, self.code = msg, code


# ---------- авторизация: проверка initData (dev.max.ru → Валидация данных) ----------

def _auth_tokens():
    """В проде — только MAX_TOKEN. На тестовом стенде можно добавить свои же
    токены через MAX_EXTRA_TOKENS (через запятую). В проде переменная не задаётся."""
    tokens = [MAX_TOKEN or ""]
    tokens += [t.strip() for t in os.getenv("MAX_EXTRA_TOKENS", "").split(",")]
    return [t for t in tokens if t]


def _parse_init_data(raw: str):
    """Значения декодируются как decodeURIComponent (unquote), а НЕ как form-data:
    литеральный '+' остаётся плюсом (MAX отдаёт имена вида 'White+and+Black')."""
    s = raw or ""
    if "WebAppData=" in s:                      # если пришёл весь фрагмент URL
        s = s.split("WebAppData=", 1)[1]
        s = s.split("&WebAppPlatform", 1)[0].split("#", 1)[0]
        s = unquote(s)
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
    if len(hashes) != 1:
        return None
    got = hashes[0]
    body = sorted((k, v) for k, v in pairs if k != "hash")
    launch_params = "\n".join(f"{k}={v}" for k, v in body).encode()

    for tok in _auth_tokens():
        secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, launch_params, hashlib.sha256).hexdigest()
        if hmac.compare_digest(calc, got):
            break
    else:
        if os.getenv("AUTH_DEBUG") == "1":      # только ключи, без персональных данных
            log.warning(f"[AUTH] подпись не сошлась; ключи={[k for k, _ in body]}, hash={got[:12]}…")
        return None

    d = dict(pairs)
    ts = int(d.get("auth_date") or 0)
    ts = ts / 1000 if ts > 1e11 else ts
    if time.time() - ts > max_age:
        return None
    try:
        return int(json.loads(d.get("user") or "{}")["id"])
    except Exception:
        return None


def _media_token(job_id: str) -> str:
    """Подпись для <video src> и ссылок скачивания — заголовок туда не поставить."""
    return hmac.new(SECRET, job_id.encode(), hashlib.sha256).hexdigest()[:32]


def _prev_path(job_id: str, idx: int) -> str:
    """Единая точка правды для имени превью (используется везде)."""
    return f"downloads/prev_{job_id}_{idx}.mp4"


@web.middleware
async def _mw(request, handler):
    try:
        path = request.path
        # Медиа (превью/скачивание): авторизация подписанным токеном ?t=
        if path.startswith("/api/jobs/") and ("/preview/" in path or "/download/" in path):
            jid = path.split("/")[3]
            if hmac.compare_digest(request.query.get("t", ""), _media_token(jid)):
                job = JOBS.get(jid)
                if job:
                    request["uid"] = job.user_id
                    return await handler(request)
            raise ApiError("Открой приложение из MAX", 401)

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
    status: str = "scanning"          # scanning | ready | error
    progress: str = ""
    done: int = 0
    total: int = 0
    error: str = ""
    ts: float = field(default_factory=time.time)
    seen: bool = False
    charged: bool = False
    premium: bool = False
    previews: list = field(default_factory=list)
    previews_status: str = "pending"  # pending | done | error
    renders: dict = field(default_factory=dict)   # idx -> {status, path, name, error}

    def public(self):
        d = {k: getattr(self, k) for k in
             ("id", "status", "progress", "done", "total", "error",
              "duration", "moments", "previews", "previews_status")}
        d["renders"] = {str(k): {kk: vv for kk, vv in v.items() if kk != "path"}
                        for k, v in self.renders.items()}
        d["media_token"] = _media_token(self.id)
        return d

    def busy(self) -> bool:
        return self.status == "scanning" or any(
            r.get("status") == "pending" for r in self.renders.values())


JOBS: dict = {}


def _rm(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def _cleanup_job(j: Job):
    _rm(j.path)
    for i in range(len(j.moments)):
        _rm(_prev_path(j.id, i))
    for r in j.renders.values():
        _rm(r.get("path"))


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
        if j.user_id == uid and j.busy():
            raise ApiError("Предыдущая задача ещё выполняется — дождись окончания", 409)
        # чужие/свои старые задачи убираем, но НЕ трогаем те, что сейчас работают
        if not j.busy() and (j.user_id == uid or now - j.ts > 6 * 3600):
            _cleanup_job(j)
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
    async with async_session_max() as s:
        user = await get_or_create_user(s, job.user_id, job.chat_id)
        premium = user.active_sub != "default"
        if job.user_id not in ADMIN_IDS:
            await increment_video_counter(user, s)
        return premium


# ---------- превью ----------

async def _make_previews(job: Job):
    """Лёгкие 360p превью на каждый момент — для плеера в мини-приложении."""
    try:
        async with PREVIEW_SLOTS:
            for i, m in enumerate(job.moments):
                job.progress = f"Превью {i + 1}/{len(job.moments)}"
                prev = _prev_path(job.id, i)
                try:
                    if job.source_url:
                        await download_section(job.source_url, m["start"], m["end"],
                                               prev, max_height=360)
                        await asyncio.to_thread(engine.faststart, prev)
                    else:
                        await asyncio.to_thread(engine.make_preview, job.path,
                                                m["start"], m["end"], prev)
                    job.previews.append({"idx": i, "status": "ready"})
                except Exception as e:
                    traceback.print_exc()
                    job.previews.append({"idx": i, "status": "error", "error": str(e)[:100]})
        job.previews_status = "done"
        job.progress = ""
    except Exception:
        traceback.print_exc()
        job.previews_status = "error"


# ---------- сканирование ----------

async def _scan(job: Job, url: str = ""):
    try:
        async with SCAN_SLOTS:
            if url:
                job.progress = "Качаю звук"
                job.path = f"downloads/max_{job.user_id}_{job.id}.wav"
                await download_audio_only(url, job.path)
            job.progress = "Ищу громкие моменты"
            res = await asyncio.to_thread(
                engine.scan_audio_wav if url else engine.scan_highlights,
                job.path, MAX_HIGHLIGHTS)
        job.duration = max(res["duration"], 1.0)
        job.moments = res["moments"]
        job.status = "ready"
        job.progress = ""
        if job.moments:
            asyncio.create_task(_make_previews(job))
        else:
            job.previews_status = "done"
    except Exception as e:
        traceback.print_exc()
        job.status, job.error = "error", f"{type(e).__name__}: {str(e)[:150]}"
        _rm(job.path)


# ---------- рендер полного качества ----------

async def _render_one(job: Job, idx: int, subs: bool, vertical: bool):
    """idx = -1 — всё видео целиком."""
    try:
        async with RENDER_SLOTS:
            if not job.charged:
                job.premium = await _charge(job)
                job.charged = True

            if idx == -1:
                if await asyncio.to_thread(engine.get_video_duration, job.path) > MAX_FULL_VIDEO_SEC:
                    raise ApiError(f"Видео длиннее {MAX_FULL_VIDEO_SEC // 60} минут — только хайлайты")
                src = job.path
                if job.source_url and src.endswith(".wav"):
                    job.progress = "Качаю полное видео"
                    src = await download_by_link(job.source_url, job.path[:-4] + ".mp4")
                job.progress = "Субтитры на всё видео"
                r = await asyncio.to_thread(engine.process_video, src, str(job.user_id),
                                            job.premium, None, vertical)
                job.renders[idx] = {"status": "ready", "path": r["video_path"],
                                    "name": "full_subtitled.mp4"}
            else:
                m = job.moments[idx]
                job.progress = f"Клип {idx + 1}"
                clip = f"downloads/clip_{job.id}_{idx}.mp4"
                if job.source_url:
                    clip = await download_section(job.source_url, m["start"], m["end"], clip)
                else:
                    await asyncio.to_thread(engine.cut_clip, job.path, m["start"], m["end"], clip)

                final = clip
                if subs:
                    r = await asyncio.to_thread(engine.process_video, clip, str(job.user_id),
                                                job.premium, None, vertical)
                    final = r["video_path"]
                elif vertical:
                    v = clip[:-4] + "_v.mp4"
                    await asyncio.to_thread(engine.crop_to_vertical, clip, v)
                    final = v
                job.renders[idx] = {"status": "ready", "path": final, "name": f"clip_{idx + 1}.mp4"}
            job.progress = ""
    except ApiError as e:
        job.renders[idx] = {"status": "error", "error": e.msg}
    except Exception as e:
        traceback.print_exc()
        job.renders[idx] = {"status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}"}


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
    if job.status == "error":
        job.seen = True
    return web.json_response(job.public())


async def api_active(request):
    mine = [j for j in JOBS.values() if j.user_id == request["uid"]]
    job = max(mine, key=lambda j: j.ts, default=None)
    if job and job.status == "error":
        if job.seen:
            job = None
        else:
            job.seen = True
    return web.json_response({"job": job.public() if job else None})


async def api_prepare(request):
    job = _job_of(request)
    body = await request.json()
    idx = int(body.get("idx", -1))
    if idx != -1 and not (0 <= idx < len(job.moments)):
        raise ApiError("Неверный момент")
    if job.status != "ready":
        raise ApiError("Задача сейчас занята", 409)
    cur = job.renders.get(idx)
    if cur and cur["status"] in ("pending", "ready"):
        return web.json_response(job.public())
    job.renders[idx] = {"status": "pending"}
    asyncio.create_task(_render_one(job, idx, bool(body.get("subtitles", True)),
                                    bool(body.get("vertical", False))))
    return web.json_response(job.public())


async def api_preview(request):
    job = _job_of(request)
    idx = int(request.match_info["idx"])
    path = _prev_path(job.id, idx)
    if not os.path.exists(path):
        raise ApiError("Превью ещё не готово", 404)
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


async def api_download(request):
    job = _job_of(request)
    idx = int(request.match_info["idx"])
    r = job.renders.get(idx)
    if not r or r["status"] != "ready" or not os.path.exists(r.get("path", "")):
        raise ApiError("Файл ещё не готов", 404)
    return web.FileResponse(r["path"], headers={
        "Content-Disposition": f'attachment; filename="{r["name"]}"',
        "Cache-Control": "no-store",
    })


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
    api = web.Application(middlewares=[_mw], client_max_size=3 * 1024 ** 3)
    api.add_routes([
        web.get("/me", api_me), web.get("/active", api_active),
        web.post("/scan", api_scan), web.post("/upload", api_upload),
        web.get("/jobs/{id}", api_job),
        web.post("/jobs/{id}/prepare", api_prepare),
        web.get("/jobs/{id}/preview/{idx}", api_preview),
        web.get("/jobs/{id}/download/{idx}", api_download),
        web.post("/email", api_email), web.post("/pay", api_pay), web.get("/stats", api_stats),
    ])
    app.add_subapp("/api", api)
    app.router.add_get("/app", _index)
    app.router.add_get("/app/", _index)