// static/js/api.js — весь сетевой код. Остальные модули про fetch/XHR не знают.
//
// Авторизация зависит от того, откуда открыто приложение:
//   MAX / Telegram — initData мессенджера в заголовке X-Init-Data (+ подсказка X-Platform);
//   сайт           — токен сессии из логина в X-Site-Token (хранится в localStorage).

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

/** Пользователь сам отменил загрузку файла. */
export class UploadAborted extends Error {}

/** Откуда открыто приложение. */
export function detectPlatform() {
  const T = window.Telegram && window.Telegram.WebApp;
  if (T && T.initData) return 'tg';
  if (window.WebApp && window.WebApp.initData) return 'max';
  const q = new URLSearchParams(location.search);
  if (q.get('tg_init_data')) return 'tg';       // отладка TG в обычном браузере
  if (q.get('init_data')) return 'max';         // отладка MAX в обычном браузере
  return 'site';
}

/** Токен сессии сайта (после входа по имени/паролю). */
export const siteToken = {
  get: () => localStorage.getItem('site_token') || '',
  set: (t) => localStorage.setItem('site_token', t),
  clear: () => localStorage.removeItem('site_token'),
};

export class Api {
  /**
   * @param {() => string} getInitData — initData мессенджера (для max/tg)
   * @param {string} platform — 'max' | 'tg' | 'site'
   */
  constructor(getInitData, platform = 'max') {
    this._initData = getInitData;
    this._platform = platform;
    this.onUnauthorized = null;      // сессия сайта истекла — покажем экран входа
  }

  _headers() {
    if (this._platform === 'site') {
      const t = siteToken.get();
      return t ? { 'X-Site-Token': t } : {};
    }
    return { 'X-Init-Data': this._initData(), 'X-Platform': this._platform };
  }

  async request(path, method = 'GET', body) {
    const headers = this._headers();
    if (body) headers['Content-Type'] = 'application/json';
    const r = await fetch('/api' + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      if (r.status === 401 && this._platform === 'site' && siteToken.get()) {
        siteToken.clear();           // сессия протухла — назад к экрану входа
        if (this.onUnauthorized) this.onUnauthorized();
      }
      throw new ApiError(d.error || 'Ошибка ' + r.status, r.status);
    }
    return d;
  }

  // ---------- задачи ----------
  active() { return this.request('/active'); }
  job(id) { return this.request('/jobs/' + id); }
  scan(url) { return this.request('/scan', 'POST', { url }); }
  cancel(id) { return this.request(`/jobs/${id}/cancel`, 'POST'); }
  prepare(id, idx, subtitles, vertical) {
    return this.request(`/jobs/${id}/prepare`, 'POST', { idx, subtitles, vertical });
  }

  // ---------- профиль ----------
  me() { return this.request('/me'); }
  stats() { return this.request('/stats'); }
  saveEmail(email) { return this.request('/email', 'POST', { email }); }
  pay(subId) { return this.request('/pay', 'POST', { sub_id: subId }); }

  // ---------- сайт: вход и привязка ----------
  register(username, password) { return this.request('/site/register', 'POST', { username, password }); }
  login(username, password) { return this.request('/site/login', 'POST', { username, password }); }
  linkStart() { return this.request('/link/start', 'POST'); }
  linkApply(code) { return this.request('/link/apply', 'POST', { code }); }

  /** Ссылка на превью/скачивание: <video src> и <a download> заголовков не шлют, поэтому токен в query. */
  mediaUrl(job, kind, idx) {
    return `/api/jobs/${job.id}/${kind}/${idx}?t=${job.media_token || ''}`;
  }

  /**
   * Загрузка файла с прогрессом (fetch этого не умеет, поэтому XHR).
   * @returns {{ promise: Promise<object>, abort: () => void }}
   */
  upload(file, onProgress) {
    const xhr = new XMLHttpRequest();
    const promise = new Promise((resolve, reject) => {
      xhr.open('POST', '/api/upload');
      for (const [k, v] of Object.entries(this._headers())) xhr.setRequestHeader(k, v);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        let d = {};
        try { d = JSON.parse(xhr.responseText); } catch (_) { /* не JSON */ }
        if (xhr.status !== 200) reject(new ApiError(d.error || 'Не удалось загрузить файл', xhr.status));
        else resolve(d);
      };
      xhr.onerror = () => reject(new ApiError('Нет связи с сервером'));
      xhr.onabort = () => reject(new UploadAborted());
      const fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    });
    return { promise, abort: () => xhr.abort() };
  }
}

/** initData из SDK мессенджера, а при отладке в браузере — из query-параметра. */
export function readInitData(platform) {
  if (platform === 'tg') {
    const T = window.Telegram && window.Telegram.WebApp;
    return (T && T.initData) || new URLSearchParams(location.search).get('tg_init_data') || '';
  }
  const W = window.WebApp;
  return (W && W.initData) || new URLSearchParams(location.search).get('init_data') || '';
}
