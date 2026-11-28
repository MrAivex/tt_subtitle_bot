// static/js/views/results_view.js — найденные моменты: плеер, галерея, опции, нижняя кнопка.
import { View } from './view.js';
import { $ } from '../utils.js';

const HINT = 'Смотри превью, отмечай сердечками нужные — большая кнопка внизу подготовит их и пришлёт в чат ♡';
const EMPTY = 'Жду новые видео от тебя ♡';

// подписи кнопок формата и расположения субтитров
const FMT_TITLES = { source: 'исходный', vert: '9:16', tiktok: 'TikTok' };
const POS_TITLES = { bottom: 'внизу', middle: 'по центру', top: 'вверху' };

export class ResultsView extends View {
  /** @param {object} parts — { player, gallery, actionBar }: готовые компоненты, которые экран собирает вместе */
  constructor(ctx, { player, gallery, actionBar }) {
    super(ctx);
    this._player = player;
    this._gallery = gallery;
    this._actionBar = actionBar;
  }

  render() {
    const j = this.ctx.state.job;
    if (!$('#pbox')) this._scaffold();

    const ms = j.moments || [];
    $('#mh').innerHTML = ms.length ? `Найдено <span class="hl">моментов: ${ms.length}</span>` : 'Ярких моментов нет';

    const tt = $('#tt');
    tt.hidden = !(ms.length && j.title);
    if (j.title) tt.textContent = '🎞 «' + j.title + '»';

    $('#ms').textContent = j.error || (
      j.previews_status === 'pending' && j.progress ? j.progress : ms.length ? HINT : EMPTY
    );

    this._player.ensure();
    this._gallery.update();
    this.renderOptions();
    this._actionBar.update();
  }

  /** Кнопки «Субтитры / Цвет / Анимация / Расположение / Формат / Новое видео». */
  renderOptions() {
    const { state } = this.ctx;
    const sw = (c) => `<i class="sw" style="background:${c}"></i>`;
    $('#opts').innerHTML = `
    <button data-a="subs" class="${state.subs ? 'on' : ''}">Субтитры: ${state.subs ? 'да' : 'нет'}</button>
    <button data-a="color">Цвет ${sw(state.color)}</button>
    <button data-a="anim" class="${state.anim ? 'on' : ''}">Анимация: ${state.anim ? 'караоке' : 'обычные'}</button>
    <button data-a="pos">Расположение: ${POS_TITLES[state.pos] || 'внизу'}</button>
    <button data-a="fmt" class="${state.fmt !== 'source' ? 'on' : ''}" title="TikTok: вебка стримера сверху, стрим снизу — 9:16. Вебку ищем на видео автоматически; если её нет — просто обрезка в 9:16">Формат: ${FMT_TITLES[state.fmt] || 'исходный'}</button>
    <button data-a="reset">Новое видео</button>`;
  }

  _scaffold() {
    this.root.innerHTML = `<h1 id="mh"></h1><p class="sub" id="ms"></p><div class="name" id="tt" hidden></div>
      <div id="pbox"></div><div class="grid" id="grid"></div><div class="opts" id="opts"></div>`;
  }
}
