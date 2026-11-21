// static/js/downloader.js — скачивание готовых клипов.
import { DOWNLOAD_GAP_MS } from './config.js';
import { sleep } from './utils.js';

export class Downloader {
  constructor({ state, api, toast }) {
    this._state = state;
    this._api = api;
    this._toast = toast;
  }

  /** Один клип: невидимая ссылка с атрибутом download. */
  one(i) {
    const r = this._state.renders[String(i)];
    if (!r || r.status !== 'ready') return;
    const a = document.createElement('a');
    a.href = this._api.mediaUrl(this._state.job, 'download', i);
    a.download = r.name || `clip_${i + 1}.mp4`;
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
