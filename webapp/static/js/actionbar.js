// static/js/actionbar.js — большая нижняя кнопка: «Подготовить» → «Готовлю…» → «Скачать».
// В миниapp файлы приходят сообщением в чат (кнопка шлёт в чат, повторный клик — повторная отправка).
import { $, etaText } from './utils.js';

export class ActionBar {
  /**
   * @param {object}     deps
   * @param {AppState}   deps.state
   * @param {Downloader} deps.downloader
   * @param {string}     deps.platform — 'max' | 'tg' | 'site' (подпись кнопки)
   * @param {(idxs: number[]) => Promise<void>} deps.onPrepare — запустить рендер выбранных клипов
   */
  constructor({ state, downloader, onPrepare, platform = 'max' }) {
    this._state = state;
    this._downloader = downloader;
    this._onPrepare = onPrepare;
    this._platform = platform;
    this._bar = $('#actbar');
    this._btn = $('#big');
    this._btn.onclick = () => this._click();
  }

  hide() {
    this._bar.hidden = true;
    document.body.classList.remove('hasact');
  }

  update() {
    const s = this._state;
    const j = s.job;
    const show = !!(j && j.status !== 'error' && (j.moments || []).length);
    this._bar.hidden = !show;
    document.body.classList.toggle('hasact', show);
    if (!show) return;

    const idxs = s.selectedSorted();
    const rs = s.renders;
    const st = idxs.map((i) => (rs[String(i)] || {}).status);
    const b = this._btn;

    if (!idxs.length) {
      this._set(b, true, 'Отметь клипы галочками', 'none');
    } else if (st.some((x) => x === 'pending')) {
      const left = Math.max(0, ...idxs.map((i) => (rs[String(i)] || {}).eta_left || 0));
      this._set(b, true, '<span class="spin"></span> Готовлю… ' + (left ? etaText(left) : ''), 'wait');
    } else if (st.every((x) => x === 'ready')) {
      const verb = this._platform === 'site' ? 'Скачать' : 'Прислать в чат';
      this._set(b, false, `⬇ ${verb}: ${idxs.length}`, 'dl');
    } else if (st.some((x) => x === 'error')) {
      this._set(b, false, `↻ Повторить: ${idxs.length}`, 'prep');
    } else {
      this._set(b, false, `⚡ Подготовить выбранные: ${idxs.length}`, 'prep');
    }
  }

  _set(btn, disabled, html, mode) {
    btn.disabled = disabled;
    btn.innerHTML = html;
    btn.dataset.m = mode;
  }

  async _click() {
    const mode = this._btn.dataset.m;
    const idxs = this._state.selectedSorted();
    if (mode === 'prep') await this._onPrepare(idxs);
    else if (mode === 'dl') this._downloader.many(idxs);
  }
}
