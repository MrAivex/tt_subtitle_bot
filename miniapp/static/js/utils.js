// static/js/utils.js — мелкие чистые функции без состояния.

export const $ = (selector) => document.querySelector(selector);

const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };

/** Экранирование для вставки в innerHTML. */
export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ESC_MAP[c]);

/** Секунды → «м:сс» или «ч:мм:сс». */
export function fmt(t) {
  t = Math.max(0, Math.round(t || 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
}

/** Оставшееся время словами. */
export function etaText(s) {
  if (s == null) return '';
  if (s <= 0) return 'почти готово';
  if (s < 45) return 'меньше минуты';
  const m = Math.ceil(s / 60);
  const word =
    m % 10 === 1 && m % 100 !== 11
      ? 'минута'
      : m % 10 >= 2 && m % 10 <= 4 && (m % 100 < 10 || m % 100 >= 20)
        ? 'минуты'
        : 'минут';
  return '≈ ' + m + ' ' + word;
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
