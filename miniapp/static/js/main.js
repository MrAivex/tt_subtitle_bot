// static/js/main.js — точка входа: только сборка и запуск.
import { state } from './state.js';
import { Api, readInitData } from './api.js';
import { App } from './app.js';

try { window.WebApp && window.WebApp.ready(); } catch (_) { /* открыто не из MAX */ }

new App({ state, api: new Api(readInitData) }).start();
