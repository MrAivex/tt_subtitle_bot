// static/js/poller.js — периодический вызов функции, пока идёт обработка.
import { POLL_INTERVAL_MS } from './config.js';

export class Poller {
  constructor(fn, intervalMs = POLL_INTERVAL_MS) {
    this._fn = fn;
    this._ms = intervalMs;
    this._timer = null;
  }

  get active() {
    return this._timer !== null;
  }

  start() {
    if (!this._timer) this._timer = setInterval(this._fn, this._ms);
  }

  stop() {
    clearInterval(this._timer);
    this._timer = null;
  }
}
