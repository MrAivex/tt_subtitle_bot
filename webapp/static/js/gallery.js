// static/js/gallery.js — сетка плиток с моментами: группы по типам, выбор сердечком,
// открытие в плеере. Скачивание — только сердечко + большая кнопка внизу.
import { $, esc, fmt } from './utils.js';

// порядок и подписи групп; kind приходит с сервера (fight/funny/talk + старые типы)
const KIND_ORDER = ['fight', 'funny', 'talk'];
const KIND_TITLES = {
  fight: '🔫 Файты', funny: '😂 Смешные', talk: '💬 Разговорники',
  shock: '😱 Шок', win: '🏆 Победы', absurd: '🤡 Абсурд', hype: '🔊 Громкие',
};

export class Gallery {
  /**
   * @param {object}         deps
   * @param {AppState}       deps.state
   * @param {ThumbnailCache} deps.thumbs
   * @param {Toast}          deps.toast
   * @param {() => number}    deps.getCurrent — какой клип сейчас в плеере
   * @param {(i) => void}    deps.onOpen     — открыть клип i в плеере
   * @param {(i) => void}    deps.onToggle   — отметить/снять клип i
   */
  constructor({ state, thumbs, toast, getCurrent, onOpen, onToggle }) {
    this._state = state;
    this._thumbs = thumbs;
    this._toast = toast;
    this._getCurrent = getCurrent;
    this._onOpen = onOpen;
    this._onToggle = onToggle;
    this._sig = '';   // «подпись» последней отрисовки: если не изменилась, DOM не трогаем
  }

  /** Забыть кадры и подпись: показывается другая задача. */
  reset() {
    this._thumbs.clear();
    this._sig = '';
  }

  update() {
    const s = this._state;
    const j = s.job;
    if (!j || !$('#grid')) return;
    const moments = j.moments || [];
    const cur = this._getCurrent();

    const sig = JSON.stringify([
      j.id,
      moments.map((m) => m.kind || 'hype').join(','),
      moments.length,
      (j.previews || []).map((p) => p.idx + p.status),
      Object.entries(s.renders).map(([k, v]) => k + v.status),
      [...s.sel],
      cur,
      this._thumbs.version,
    ]);
    if (sig === this._sig) return;
    this._sig = sig;

    $('#grid').innerHTML = this._sections(moments, cur);
    this._thumbs.fill();
  }

  /** Плитки сгруппированы по типу момента; номер на плитке = настоящий номер в списке. */
  _sections(moments, cur) {
    if (!moments.length) return '';
    const groups = new Map();
    moments.forEach((m, i) => {
      const k = m.kind || 'hype';
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(i);
    });
    const order = [
      ...KIND_ORDER.filter((k) => groups.has(k)),
      ...[...groups.keys()].filter((k) => !KIND_ORDER.includes(k)),
    ];
    return order.map((k) => {
      const idxs = groups.get(k);
      const title = KIND_TITLES[k] || k;
      return `<div class="ghead">${title} <span>· ${idxs.length}</span></div>`
        + idxs.map((i) => this._tile(moments[i], i, cur)).join('');
    }).join('');
  }

  /** @returns {boolean} true — клик обработан галереей */
  handleClick(e) {
    const chk = e.target.closest('.chk');
    if (chk) { this._onToggle(+chk.dataset.chk); return true; }   // сердечко: только выбор, плеер не трогаем

    const tile = e.target.closest('.tile');
    if (tile) {                                                   // плитка вне сердечка: показать в плеере
      const i = +tile.dataset.i;
      const p = (this._state.job.previews || []).find((x) => x.idx === i);
      if (!p || p.status !== 'ready') this._toast.show('Превью ещё готовится');
      else this._onOpen(i);
      return true;
    }
    return false;
  }

  // ---------- разметка ----------

  _cover(i) {
    const p = (this._state.job.previews || []).find((x) => x.idx === i);
    if (p && p.status === 'ready') {
      const frame = this._thumbs.get(i);
      if (frame) return `<img src="${frame}" alt="">`;
      if (this._thumbs.has(i)) return '<span class="ph" style="animation:none">▶</span>';
      return '<span class="ph"></span>';
    }
    if (p && p.status === 'error') return '<span class="ph" style="animation:none">✕</span>';
    return '<span class="ph"></span>';
  }

  _tile(m, i, cur) {
    const s = this._state;
    return `<div class="tile ${s.sel.has(i) ? 'sel' : ''} ${cur === i ? 'cur' : ''}" data-i="${i}" data-k="${m.kind || 'hype'}">
      ${this._cover(i)}
      <span class="no">${i + 1} ${esc(m.emoji || '')}</span>
      <button class="chk ${s.sel.has(i) ? 'on' : ''}" data-chk="${i}" aria-label="Выбрать">♥</button>
      <span class="dur">${fmt(m.end - m.start)}</span>
      ${(s.renders[String(i)] || {}).status === 'pending' ? '<span class="pend"><span class="spin"></span></span>' : ''}
    </div>`;
  }
}
