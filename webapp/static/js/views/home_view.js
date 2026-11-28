// static/js/views/home_view.js — стартовый экран: ссылка или файл + типы моментов.
import { View } from './view.js';

// Типы моментов: подпись, эмодзи, «что ищем и сколько». Порядок = порядок на экране.
export const CATS = [
  { kind: 'fight', emoji: '🔫', title: 'Файты', hint: '10 × 2–5 с' },
  { kind: 'funny', emoji: '😂', title: 'Смешные', hint: '5 × до 1 мин' },
  { kind: 'talk', emoji: '💬', title: 'Разговорники', hint: '3 × до 2 мин' },
];

export class HomeView extends View {
  async render() {
    const { state, api, mascot, showError } = this.ctx;
    try {
      state.me = await api.me();
    } catch (e) {
      return showError(e.message);
    }
    if (state.tab !== 'home') return;     // пока ждали ответ, пользователь ушёл в профиль

    const m = state.me;
    const left = m.free_period || m.is_admin || m.limit > 1000 ? 'без ограничений' : Math.max(0, m.limit - m.used);
    this.root.innerHTML = `${mascot.hero('idle', 'idle')}
  <h1>Нарезка <span class="hl">хайлайтов</span></h1>
  ${m.free_period ? '<p class="sub">🎁 Бесплатно, пока бот в тестировании!</p>' : ''}
  <p class="sub">Видео на сегодня: <b>${left}</b></p>
  <input id="url" type="url" placeholder="Ссылка на YouTube, Twitch, TikTok, Диск" autocomplete="off">
  <button class="pri" data-a="scan">Найти моменты ✦</button>
  <div class="or">или</div>
  <label class="file"><input id="file" type="file" accept="video/*,.mkv" hidden>Загрузить файл с устройства</label>
  <div class="cats">${CATS.map((c) => `
    <label class="cat"><input type="checkbox" data-kind="${c.kind}" checked>
      <span><i>${c.emoji}</i> ${c.title}<small>${c.hint}</small></span></label>`).join('')}
  </div>`;
  }
}
