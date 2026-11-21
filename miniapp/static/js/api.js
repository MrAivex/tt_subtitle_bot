// static/js/api.js — весь сетевой код. Остальные модули про fetch/XHR не знают.

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

/** Пользователь сам отменил загрузку файла. */
export class UploadAborted extends Error {}

export class Api {
  /** @param {() => string} getInitData — откуда брать initData мессенджера MAX */
  constructor(getInitData) {
    this._initData = getInitData;
  }

  async request(path, method = 'GET', body) {
    const headers = { 'X-Init-Data': this._initData() };
    if (body) headers['Content-Type'] = 'application/json';
    const r = await fetch('/api' + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new ApiError(d.error || 'Ошибка ' + r.status, r.status);
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
      xhr.setRequestHeader('X-Init-Data', this._initData());
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

/** initData из SDK MAX, а при отладке в браузере — из ?init_data=. */
export function readInitData() {
  const W = window.WebApp;
  return (W && W.initData) || new URLSearchParams(location.search).get('init_data') || '';
}
