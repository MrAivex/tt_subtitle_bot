// static/js/thumbs.js — кадры-миниатюры для галереи: берём кадр прямо из превью-видео.

const W = 160;
const H = 100;

/** Кадр из видео по url → dataURL (JPEG) или null, если не вышло за 8 секунд. */
function captureFrame(url) {
  return new Promise((resolve) => {
    const v = document.createElement('video');
    v.muted = true;
    v.preload = 'metadata';
    v.src = url;

    const finish = (value) => {
      clearTimeout(timeout);
      v.src = '';
      resolve(value);
    };
    const timeout = setTimeout(() => finish(null), 8000);

    v.onloadedmetadata = () => {
      try { v.currentTime = Math.min(1.5, (v.duration || 3) / 3); }
      catch (_) { finish(null); }
    };
    v.onseeked = () => {
      try {
        const c = document.createElement('canvas');
        c.width = W;
        c.height = H;
        const vw = v.videoWidth || W;
        const vh = v.videoHeight || H;
        const s = Math.max(W / vw, H / vh);
        const dw = vw * s;
        const dh = vh * s;
        c.getContext('2d').drawImage(v, (W - dw) / 2, (H - dh) / 2, dw, dh);
        finish(c.toDataURL('image/jpeg', 0.7));
      } catch (_) {
        finish(null);
      }
    };
    v.onerror = () => finish(null);
  });
}

export class ThumbnailCache {
  /**
   * @param {object}   deps
   * @param {AppState} deps.state
   * @param {Api}      deps.api
   * @param {Function} deps.onUpdate — вызывается, когда появился новый кадр
   */
  constructor({ state, api, onUpdate }) {
    this._state = state;
    this._api = api;
    this._onUpdate = onUpdate;
    this._map = new Map();   // номер клипа → dataURL | null (null = кадр не вышел)
    this._busy = false;
    this.version = 0;        // растёт при каждом изменении — галерея по нему понимает, что пора перерисоваться
  }

  get(i) { return this._map.get(i); }
  has(i) { return this._map.has(i); }

  clear() {
    this._map.clear();
    this.version++;
  }

  /** Делает кадры по очереди для всех готовых превью, у которых их ещё нет. */
  async fill() {
    const j = this._state.job;
    if (!j || this._busy) return;
    this._busy = true;
    try {
      for (const p of j.previews || []) {
        if (this._state.job !== j) break;                       // задачу сменили — выходим
        if (p.status !== 'ready' || this._map.has(p.idx)) continue;
        const frame = await captureFrame(this._api.mediaUrl(j, 'preview', p.idx));
        this._map.set(p.idx, frame || null);
        this.version++;
        this._onUpdate();
      }
    } finally {
      this._busy = false;
    }
  }
}
