// static/js/main.js — точка входа: только сборка и запуск.
//
// Приложение открывается из трёх мест:
//   из Telegram (Telegram.WebApp.initData) или из MAX (WebApp.initData) — сразу работает;
//   просто в браузере — сначала экран входа (auth.js), после входа запускается App.
import { state } from './state.js';
import { Api, readInitData, detectPlatform, siteToken } from './api.js';
import { App } from './app.js';
import { AuthView } from './auth.js';

const platform = detectPlatform();

// SDK мессенджеров: сообщаем, что готовы разворачиваться
try {
  if (platform === 'tg' && window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();
  }
  if (window.WebApp && window.WebApp.ready) window.WebApp.ready();
} catch (_) { /* открыто не из мессенджера */ }

function boot() {
  const nav = document.querySelector('nav');
  if (nav) nav.hidden = false;      // до входа на сайте навигацию прячем
  const api = new Api(() => readInitData(platform), platform);
  api.onUnauthorized = () => location.reload();   // сессия истекла → экран входа
  new App({ state, api, platform }).start();
}

if (platform === 'site' && !siteToken.get()) {
  const api = new Api(() => '', 'site');
  new AuthView({ api, onDone: boot }).render();
} else {
  boot();
}
