// static/js/views/busy_view.js — экран ожидания: сканирование или загрузка файла.
import { View } from './view.js';
import { $, esc } from '../utils.js';

export class BusyView extends View {
  /**
   * @param {object}      o
   * @param {string}      o.text — что происходит сейчас
   * @param {number|null} o.pct  — проценты; null — бегущая полоска без числа
   * @param {'scan'|'up'} o.kind
   * @param {string}      o.eta  — оставшееся время (может быть пустым)
   */
  render({ text, pct = null, kind = 'scan', eta = '' }) {
    const { mascot } = this.ctx;
    const etaHtml = eta
      ? `<p class="pct">${eta.startsWith('дольше') ? esc(eta) : 'Осталось: ' + esc(eta)}</p>`
      : '';
    const isUpload = kind === 'up';
    this.root.innerHTML = `<div class="sfx">${mascot.sfx(kind)}</div>${mascot.hero('idle', kind)}
  <p class="status">${esc(text)}</p>
  ${etaHtml}
  <div class="bar"><i class="${pct == null ? 'ind' : ''}" style="width:${pct == null ? 35 : pct}%"></i></div>
  ${pct == null ? '' : `<p class="pct">${pct}%</p>`}
  <button data-a="${isUpload ? 'cancelup' : 'cancel'}">${isUpload ? 'Отменить загрузку' : 'Прервать обработку'}</button>`;
  }

  /** Обновить только полоску и проценты, не перерисовывая экран (идёт загрузка файла). */
  setProgress(pct) {
    if (this.ctx.state.tab !== 'home') return;
    const bar = $('.bar i');
    if (bar) bar.style.width = pct + '%';
    const label = $('.pct');
    if (label) label.textContent = pct + '%';
  }
}
