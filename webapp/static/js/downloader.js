// static/js/downloader.js — скачивание готовых клипов.
import { DOWNLOAD_GAP_MS } from './config.js';
import { sleep } from './utils.js';

export class Downloader {
  constructor({ state, api, toast }) {
    this._state = state;
    this._api = api;
    this._toast = toast;
  }

  /** WebApp мессенджера, если открыто в вебвью (Telegram / MAX); иначе null. */
  _webApp() {
    const T = window.Telegram && window.Telegram.WebApp;
    if (T && T.initData) return T;
    if (window.WebApp && window.WebApp.initData) return window.WebApp;
    return null;
  }

  /** В вебвью мессенджера <a download> не работает — сохраняем/открываем через SDK. */
  _viaMessenger(url, name) {
    const W = this._webApp();
    if (!W) return false;
    if (W.downloadFile && W.isVersionAtLeast && W.isVersionAtLeast('8.0')) {
      try { W.downloadFile({ url, file_name: name }, () => {}); return true; } catch (_) { /* ниже — openLink */ }
    }
    try { W.openLink(url); return true; } catch (_) { return false; }
  }

  /** Один клип: в браузере — невидимая ссылка с атрибутом download. */
  one(i) {
    const r = this._state.renders[String(i)];
    if (!r || r.status !== 'ready') return;
    const name = r.name || `clip_${i + 1}.mp4`;
    const abs = new URL(this._api.mediaUrl(this._state.job, 'download', i), location.href).href;
    if (this._viaMessenger(abs, name)) return;    // вебвью Telegram/MAX — через SDK
    const a = document.createElement('a');
    a.href = abs;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  /** Несколько клипов подряд: браузеры не любят пачку загрузок одновременно. */
  async many(idxs) {
    this._toast.show('Сохраняю файлы по очереди');
    for (const i of idxs) {
      this.one(i);
      await sleep(DOWNLOAD_GAP_MS);
    }
  }
}
