// static/js/toast.js — всплывающая подсказка снизу.
import { TOAST_MS } from './config.js';

export class Toast {
  constructor(el) {
    this._el = el;
    this._timer = null;
  }

  show(text) {
    this._el.textContent = text;
    this._el.style.display = 'block';
    clearTimeout(this._timer);
    this._timer = setTimeout(() => { this._el.style.display = 'none'; }, TOAST_MS);
  }
}
