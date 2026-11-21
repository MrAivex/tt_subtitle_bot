// static/js/state.js — единственное место, где живёт состояние приложения.
import { MAX_SELECTED_CLIPS } from './config.js';

export class AppState {
  constructor() {
    this.me = null;          // профиль (/api/me)
    this.job = null;         // текущая задача с сервера
    this.sel = new Set();    // номера отмеченных клипов
    this.subs = true;        // накладывать субтитры
    this.vert = false;       // формат 9:16
    this.tab = 'home';       // 'home' | 'profile'
    this.up = null;          // идёт загрузка файла: { pct, abort }
    this.seq = 0;            // «поколение» задачи: ответы поллинга со старым seq выбрасываются
  }

  get renders() {
    return (this.job && this.job.renders) || {};
  }

  /** Что-то ещё считается на сервере: скан, превью или рендер. */
  get busy() {
    const j = this.job;
    if (!j) return false;
    return (
      j.status === 'scanning' ||
      j.previews_status === 'pending' ||
      Object.values(this.renders).some((r) => r.status === 'pending')
    );
  }

  /** «Клип «Название стрима» #3» — номер = номер момента в списке. */
  clipName(i) {
    return this.job && this.job.title ? `Клип «${this.job.title}» #${i + 1}` : `Клип #${i + 1}`;
  }

  selectedSorted() {
    return [...this.sel].sort((a, b) => a - b);
  }

  /** Отметить/снять клип. false — лимит выбора исчерпан. */
  toggleSelection(i) {
    if (this.sel.has(i)) {
      this.sel.delete(i);
      return true;
    }
    if (this.sel.size >= MAX_SELECTED_CLIPS) return false;
    this.sel.add(i);
    return true;
  }
}

export const state = new AppState();
