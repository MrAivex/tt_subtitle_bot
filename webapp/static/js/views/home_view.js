// static/js/views/home_view.js — стартовый экран: ссылка или файл.
import { View } from './view.js';

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
  <label class="file"><input id="file" type="file" accept="video/*,.mkv" hidden>Загрузить файл с устройства</label>`;
  }
}
