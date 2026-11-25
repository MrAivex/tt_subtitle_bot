// static/js/auth.js — экран входа на сайте (вход / регистрация).
import { $, esc } from './utils.js';
import { siteToken } from './api.js';

const MASCOT_FACE = ['(｡•̀ᴗ-)✧', '(๑˃ᴗ˂)ﻭ', '(≧◡≦)'];
const MASCOT_LINE = [
  'Привет-привет! Представься — и сразу займёмся делом~',
  'Ну и кто тут у нас? Войди, я ж не кусаюсь!',
  'Введи имя и пароль, и поедем нарезать хайлайты!',
];

export class AuthView {
  /**
   * @param {object}   deps
   * @param {Api}      deps.api — api в режиме 'site' (без токена)
   * @param {() => void} deps.onDone — вход/регистрация прошли: запускаем приложение
   */
  constructor({ api, onDone }) {
    this._api = api;
    this._onDone = onDone;
    this._mode = 'login';
    this._face = MASCOT_FACE[Math.floor(Math.random() * MASCOT_FACE.length)];
    this._line = MASCOT_LINE[Math.floor(Math.random() * MASCOT_LINE.length)];
  }

  render() {
    const isLogin = this._mode === 'login';
    this.root = $('#v');
    this.root.innerHTML = `
  <div class="hero"><div class="face">${esc(this._face)}</div><div class="bubble">${esc(this._line)}</div></div>
  <h1>Нарезка <span class="hl">хайлайтов</span></h1>
  <p class="sub">Тот же бот — теперь и отдельным сайтом.</p>
  <div class="tabs">
    <button id="tab-login" class="${isLogin ? 'on' : ''}">Вход</button>
    <button id="tab-reg" class="${!isLogin ? 'on' : ''}">Регистрация</button>
  </div>
  <div class="card">
    <input id="au" type="text" placeholder="Имя пользователя" autocomplete="username" maxlength="32">
    <input id="ap" type="password" placeholder="Пароль" autocomplete="${isLogin ? 'current-password' : 'new-password'}">
    <button class="pri" id="asubmit">${isLogin ? 'Войти' : 'Создать аккаунт'}</button>
    <p class="hint" id="ahint">${isLogin ? 'Открой из MAX или Telegram — логин не понадобится.' : 'Имя: 3–32 символа, пароль от 6 символов.'}</p>
  </div>`;

    $('#tab-login').onclick = () => { this._mode = 'login'; this.render(); };
    $('#tab-reg').onclick = () => { this._mode = 'reg'; this.render(); };
    $('#asubmit').onclick = () => this.submit();
    const enter = (e) => { if (e.key === 'Enter') this.submit(); };
    $('#au').onkeydown = enter;
    $('#ap').onkeydown = enter;
    $('#au').focus();
  }

  async submit() {
    const username = ($('#au').value || '').trim();
    const password = $('#ap').value || '';
    if (!username || !password) {
      this._fail('Заполни имя и пароль');
      return;
    }
    const btn = $('#asubmit');
    btn.disabled = true;
    try {
      const d = this._mode === 'reg'
        ? await this._api.register(username, password)
        : await this._api.login(username, password);
      siteToken.set(d.token);
      this._onDone();
    } catch (e) {
      this._fail(e.message || 'Не получилось');
      btn.disabled = false;
    }
  }

  _fail(msg) {
    const h = $('#ahint');
    if (h) {
      h.textContent = msg;
      h.classList.add('err');
    }
  }
}
