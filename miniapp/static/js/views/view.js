// static/js/views/view.js — базовый класс экрана.
import { $ } from '../utils.js';

/**
 * Экран рисует себя в <main id="v">. Всё, что ему нужно, приходит одним объектом ctx:
 *   state, api, mascot, toast, showError(text)
 */
export class View {
  constructor(ctx) {
    this.ctx = ctx;
  }

  get root() {
    return $('#v');
  }
}
