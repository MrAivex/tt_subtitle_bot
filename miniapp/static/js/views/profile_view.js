// static/js/views/profile_view.js — профиль: тариф, email для чека, оплата, статистика админа.
import { View } from './view.js';
import { $, esc } from '../utils.js';

export class ProfileView extends View {
  async render() {
    const { state, api, mascot, showError } = this.ctx;
    let m;
    try {
      m = state.me = await api.me();
    } catch (e) {
      return showError(e.message);
    }
    if (state.tab !== 'profile') return;

    const free = m.sub === 'default';
    const unlimited = m.free_period || m.limit > 1000;
    this.root.innerHTML = `${mascot.hero('blush', 'profile')}
  <h1><span class="hl">Профиль</span></h1>
  <div class="card"><b>${free ? 'Бесплатный тариф' : 'Подписка активна'}</b>
  <p>${unlimited ? 'Без ограничений по видео' : 'Использовано сегодня: ' + m.used + ' из ' + m.limit}</p>
  ${m.expiry ? `<p>Действует до ${esc(m.expiry)}</p>` : ''}</div>
  <div class="card"><b>Email для чека</b><br><br>
  <input id="email" type="email" value="${esc(m.email)}" placeholder="name@example.com">
  <button data-a="email">Сохранить email</button></div>
  ${m.free_period ? '' : m.subs.map((s) => this._subCard(s)).join('')}
  <div id="adm"></div>`;

    if (m.is_admin) await this._renderStats();
  }

  /**
   * Кнопки профиля: email, pay, link.
   * @returns {Promise<boolean>} true — действие было нашим
   */
  async handleAction(action, button) {
    const { api, toast } = this.ctx;
    if (action === 'email') {
      try {
        await api.saveEmail($('#email').value);
        toast.show('Email сохранён');
      } catch (x) {
        toast.show(x.message);
      }
      return true;
    }
    if (action === 'pay') {
      try {
        const d = await api.pay(button.dataset.id);
        // первая кнопка создаёт платёж, превращается в ссылку на оплату
        button.dataset.a = 'link';
        button.dataset.url = d.url;
        button.textContent = 'Перейти к оплате';
      } catch (x) {
        toast.show(x.message);
      }
      return true;
    }
    if (action === 'link') {
      const url = button.dataset.url;
      const W = window.WebApp;
      if (W && W.openLink) W.openLink(url);
      else window.open(url, '_blank');
      return true;
    }
    return false;
  }

  _subCard(s) {
    return `<div class="card sub-card"><b>${esc(s.name)}, ${s.price} ₽</b><p>${esc(s.description)}</p>
  <button class="pri" data-a="pay" data-id="${esc(s.id)}">Оформить ♡</button></div>`;
  }

  async _renderStats() {
    try {
      const s = await this.ctx.api.stats();
      $('#adm').innerHTML = `<div class="card"><b>Статистика</b><p>Пользователей: ${s.total}</p>` +
        `<p>С подпиской: ${s.paid}</p><p>С email: ${s.with_email}</p></div>`;
    } catch (_) { /* статистика — необязательная часть */ }
  }
}
