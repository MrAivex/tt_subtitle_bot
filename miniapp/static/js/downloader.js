// static/js/downloader.js — готовые клипы документом в чат MAX.
// <a download> в вебвью MAX уводит на сайт, поэтому большая кнопка «Скачать»
// шлёт файлы сообщением в чат; повторное нажатие присылает их заново.
export class Downloader {
  constructor({ state, api, toast }) {
    this._state = state;
    this._api = api;
    this._toast = toast;
  }

  /** Большая кнопка «Скачать»: файлы приходят сообщением в чат. */
  async many(idxs) {
    if (!idxs || !idxs.length) return;
    this._toast.show('Отправляю в чат — файлы придут сообщениями');
    try {
      await this._api.deliver(this._state.job.id, idxs);
    } catch (e) {
      this._toast.show(e.message);
    }
  }
}
