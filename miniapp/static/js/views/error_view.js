// static/js/views/error_view.js — экран ошибки.
import { View } from './view.js';
import { esc } from '../utils.js';

export class ErrorView extends View {
  render(text) {
    const { mascot } = this.ctx;
    this.root.innerHTML = `<div class="sfx">${mascot.sfx('err')}</div>${mascot.hero('err', 'err')}` +
      `<h1>Не получилось</h1><p class="sub err">${esc(text || 'Неизвестная ошибка')}</p>` +
      '<button class="pri" data-a="reset">Попробовать снова</button>';
  }
}
