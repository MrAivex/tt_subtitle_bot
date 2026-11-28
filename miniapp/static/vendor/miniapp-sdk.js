/* vendor/miniapp-sdk.js — компактная локальная замена двух внешних SDK:
 *     https://telegram.org/js/telegram-web-app.js   (127 КБ)
 *     https://st.max.ru/js/max-web-app.js           (28 КБ)
 *
 * Зачем: эти домены недоступны в ряде стран. Из-за них страница висела белой
 * ~10 секунд, а window.Telegram / window.WebApp так и не появлялись —
 * приложение считало, что его открыли из браузера, и требовало регистрацию.
 *
 * Поддерживается ровно та поверхность API, которую использует приложение
 * (проверено поиском по static/js):
 *   Telegram.WebApp: initData, initDataUnsafe, version, platform, themeParams,
 *                    ready(), expand(), openLink(url)
 *   WebApp (MAX):    initData, initDataUnsafe, version, platform,
 *                    ready(), openLink(url)
 *
 * Механизм тот же, что в официальных SDK: initData приходит в hash URL
 * (tgWebAppData=… у Telegram, WebAppData=… у MAX), а события уходят в
 * нативный мост вебвью (TelegramWebviewProxy / WebViewHandler) или
 * postMessage (iframe-клиенты). Разбор параметров повторяет официальный
 * код один в один.
 *
 * Если понадобится полный SDK (MainButton, хаптика, payments, тема…):
 * скачайте официальные файлы в эту же папку (через прокси, из страны, где
 * домены доступны) и верните два <script> в index.html.
 */
(function () {
  'use strict';

  var isIframe = false;
  try { isIframe = (window.parent != null && window != window.parent); } catch (e) {}

  // ---------- разбор параметров (порт из telegram-web-app.js) ----------

  function urlSafeDecode(urlencoded) {
    try {
      urlencoded = urlencoded.replace(/\+/g, '%20');
      return decodeURIComponent(urlencoded);
    } catch (e) {
      return urlencoded;
    }
  }

  function urlParseQueryString(queryString) {
    var params = {};
    if (!queryString.length) return params;
    var parts = queryString.split('&');
    for (var i = 0; i < parts.length; i++) {
      var kv = parts[i].split('=');
      var k = urlSafeDecode(kv[0]);
      var v = kv[1] == null ? null : urlSafeDecode(kv[1]);
      params[k] = v;
    }
    return params;
  }

  function urlParseHashParams(locationHash) {
    locationHash = locationHash.replace(/^#/, '');
    var params = {};
    if (!locationHash.length) return params;
    if (locationHash.indexOf('=') < 0 && locationHash.indexOf('?') < 0) {
      params._path = urlSafeDecode(locationHash);
      return params;
    }
    var qIndex = locationHash.indexOf('?');
    if (qIndex >= 0) locationHash = locationHash.substr(qIndex + 1);
    var query = urlParseQueryString(locationHash);
    for (var k in query) params[k] = query[k];
    return params;
  }

  function sessionStorageGet(name) {
    try { return JSON.parse(sessionStorage.getItem(name) || '{}'); } catch (e) { return {}; }
  }
  function sessionStorageSet(name, value) {
    try { sessionStorage.setItem(name, JSON.stringify(value)); } catch (e) {}
  }

  // ---------- события (мосты вебвью — как в официальных SDK) ----------

  function tgPostEvent(eventType, eventData) {
    eventData = eventData === undefined ? '' : eventData;
    if (window.TelegramWebviewProxy !== undefined) {
      window.TelegramWebviewProxy.postEvent(eventType, JSON.stringify(eventData));
    } else if (window.external && 'notify' in window.external) {
      window.external.notify(JSON.stringify({ eventType: eventType, eventData: eventData }));
    } else if (isIframe) {
      try {
        window.parent.postMessage(
          JSON.stringify({ eventType: eventType, eventData: eventData }), '*');
      } catch (e) {}
    }
    // обычный браузер — транспорта нет, тихо ничего не делаем
  }

  function maxPostEvent(eventType, data) {
    data = data || {};
    if (window.WebViewHandler) {
      window.WebViewHandler.postEvent(eventType, JSON.stringify(data));
    } else if (isIframe) {
      try {
        window.parent.postMessage(
          JSON.stringify(Object.assign({ type: eventType }, data)), '*');
      } catch (e) {}
    }
  }

  // ---------- window.Telegram.WebApp ----------

  if (!window.Telegram) window.Telegram = {};

  if (!window.Telegram.WebApp) {
    // как в официальном SDK: hash + сохранённые в sessionStorage параметры
    var tp = urlParseHashParams(String(location.hash));
    var stored = sessionStorageGet('initParams');
    for (var key in stored) {
      if (typeof tp[key] === 'undefined') tp[key] = stored[key];
    }
    sessionStorageSet('initParams', tp);

    var tgInitData = (tp.tgWebAppData && tp.tgWebAppData.length) ? tp.tgWebAppData : '';
    var tgThemeParams = {};
    try { tgThemeParams = JSON.parse(tp.tgWebAppThemeParams || '{}'); } catch (e) {}

    window.Telegram.WebApp = {
      initData: tgInitData,
      initDataUnsafe: tgInitData ? urlParseQueryString(tgInitData) : {},
      version: (tp.tgWebAppVersion && tp.tgWebAppVersion.length) ? tp.tgWebAppVersion : '6.0',
      platform: (tp.tgWebPlatform && tp.tgWebPlatform.length) ? tp.tgWebPlatform : 'unknown',
      colorScheme: 'light',
      themeParams: tgThemeParams,
      ready: function () { tgPostEvent('web_app_ready'); },
      expand: function () { tgPostEvent('web_app_expand'); },
      openLink: function (url) { tgPostEvent('web_app_open_link', { url: url }); },
    };
  }

  // ---------- window.WebApp (MAX) ----------

  if (!window.WebApp) {
    // официальный MAX SDK берёт параметры из hash (ключи WebAppData и т.д.)
    // и дублирует их в sessionStorage
    function maxHashParam(name) {
      var v = null;
      try {
        var h = String(location.hash).replace(/^#/, '');
        if (h) v = new URLSearchParams(h).get(name);
      } catch (e) {}
      if (v === null) {
        try { v = sessionStorage.getItem(name); } catch (e) {}
      }
      if (v !== null && v !== undefined) {
        try { sessionStorage.setItem(name, v); } catch (e) {}
      }
      return v;
    }

    var maxInitData = maxHashParam('WebAppData') || '';

    function maxParseInitData(raw) {
      var t = {};
      if (!raw) return t;
      try {
        new URLSearchParams(decodeURIComponent(raw)).forEach(function (v, k) {
          if (k === 'hash' || k === 'ip' || k === 'query_id' || k === 'start_param') t[k] = v;
          else if (k === 'auth_date') t[k] = Number(v);
          else if (k === 'user' || k === 'chat') {
            try { t[k] = JSON.parse(v); } catch (e) {}
          }
        });
      } catch (e) {}
      return t;
    }

    window.WebApp = {
      initData: maxInitData,
      initDataUnsafe: maxParseInitData(maxInitData),
      platform: maxHashParam('WebAppPlatform') || null,
      version: maxHashParam('WebAppVersion') || null,
      deviceName: maxHashParam('WebAppDeviceName') || null,
      ready: function () { maxPostEvent('WebAppReady', {}); },
      openLink: function (url) { maxPostEvent('WebAppOpenLink', { url: url }); },
    };
  }
})();
