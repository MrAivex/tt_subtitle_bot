// static/js/views/profile_view.js — профиль: тариф, email для чека, оплата, аккаунты и их привязка.
import { View } from './view.js';
import { $, esc, openExternal } from '../utils.js';
import { siteToken } from '../api.js';

const PLATFORM_NAMES = { max: 'MAX', tg: 'Telegram', site: 'Сайт' };

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
  ${this._accountsCard(m)}
  <div id="adm"></div>`;

    if (m.is_admin) await this._renderStats();
  }

  /**
   * Кнопки профиля: email, pay, link (оплата), привязка аккаунтов, выход.
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
      openExternal(button.dataset.url);
      return true;
    }
    if (action === 'linkstart') {
      try {
        const d = await api.linkStart();
        $('#linkbox').hidden = false;
        $('#linkcode').textContent = d.code;
        toast.show('Код живёт 10 минут');
      } catch (x) {
        toast.show(x.message);
      }
      return true;
    }
    if (action === 'linkapply') {
      const input = $('#linkin');
      const code = (input && input.value) || '';
      if (!code.trim()) {
        toast.show('Введи код с другого устройства');
        return true;
      }
      try {
        await api.linkApply(code.trim());
        toast.show('Аккаунты связаны ♡');
        await this.render();
      } catch (x) {
        toast.show(x.message);
      }
      return true;
    }
    if (action === 'logout') {
      siteToken.clear();
      location.reload();
      return true;
    }
    return false;
  }

  _subCard(s) {
    return `<div class="card sub-card"><b>${esc(s.name)}, ${s.price} ₽</b><p>${esc(s.description)}</p>
  <button class="pri" data-a="pay" data-id="${esc(s.id)}">Оформить ♡</button></div>`;
  }

  _accountsCard(m) {
    const pills = (m.identities || []).map((i) =>
      `<span class="pill">${esc(PLATFORM_NAMES[i.platform] || i.platform)}${i.name && i.name !== i.platform ? ' · ' + esc(i.name) : ''}</span>`).join('');
    return `<div class="card"><b>Аккаунты</b>
  <p>${pills || 'Пока только этот'}</p>
  <p>Один аккаунт — одни лимиты и одна подписка, откуда бы ты ни зашёл.</p>
  <button data-a="linkstart">Получить код привязки</button>
  <div id="linkbox" hidden>
    <div class="code-big" id="linkcode"></div>
    <p class="hint">Введите этот код в приложении на другой платформе (Профиль → «Привязать по коду») — аккаунты объединятся. Подписка и лимиты останутся у того, кто создал код.</p>
  </div>
  <input id="linkin" type="tel" placeholder="Код с другого устройства" inputmode="numeric" maxlength="6" autocomplete="off">
  <button data-a="linkapply">Привязать по коду</button>
  ${this.ctx.platform === 'site' ? '<button data-a="logout">Выйти из аккаунта</button>' : ''}
</div>`;
  }

  async _renderStats() {
    try {
      const s = await this.ctx.api.stats();
      $('#adm').innerHTML = `<div class="card"><b>Статистика</b><p>Пользователей: ${s.total}</p>` +
        `<p>С подпиской: ${s.paid}</p><p>С email: ${s.with_email}</p>` +
        `<p>Привязки: MAX ${s.max} · TG ${s.tg} · сайт ${s.site}</p></div>`;
    } catch (_) { /* статистика — необязательная часть */ }
  }
}
