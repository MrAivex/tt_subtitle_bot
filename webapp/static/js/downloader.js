// static/js/downloader.js — готовые клипы пользователю.
// В вебвью мессенджера (TG/MAX) файл приходит сообщением в чат — большая кнопка
// дёргает /deliver, и каждое нажатие присылает файлы заново. На сайте — обычное
// скачивание браузером, по одному за раз.
import { DOWNLOAD_GAP_MS } from './config.js';
import { sleep } from './utils.js';

export class Downloader {
  constructor({ state, api, toast, platform = 'max' }) {
    this._state = state;
    this._api = api;
    this._toast = toast;
    this._platform = platform;   // 'max' | 'tg' | 'site'
  }

  /** Большая кнопка «Скачать»: в чат мессенджера (файлом) или в браузер (сайт). */
  async many(idxs) {
    if (!idxs || !idxs.length) return;
    if (this._platform === 'site') return this._browser(idxs);
    this._toast.show('Отправляю в чат — файлы придут сообщениями');
    try {
      await this._api.deliver(this._state.job.id, idxs);
    } catch (e) {
      this._toast.show(e.message);
    }
  }

  /** На сайте скачиваем по старинке: невидимые ссылки по очереди. */
  async _browser(idxs) {
    this._toast.show('Сохраняю файлы по очереди');
    for (const i of idxs) {
      this._one(i);
      await sleep(DOWNLOAD_GAP_MS);
    }
  }

  /** Один клип: невидимая ссылка с атрибутом download. */
  _one(i) {
    const r = this._state.renders[String(i)];
    if (!r || r.status !== 'ready') return;
    const a = document.createElement('a');
    a.href = this._api.mediaUrl(this._state.job, 'download', i);
    a.download = r.name || `clip_${i + 1}.mp4`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}
