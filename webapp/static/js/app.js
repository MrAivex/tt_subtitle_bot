// static/js/app.js — контроллер: собирает компоненты, решает, какой экран показать,
// и управляет жизнью задачи (старт → поллинг → результат → сброс).
import { MAX_SELECTED_CLIPS, PALETTE } from './config.js';
import { UploadAborted } from './api.js';
import { etaText, $ } from './utils.js';
import { Toast } from './toast.js';
import { Mascot } from './mascot.js';
import { NavBar } from './nav.js';
import { Poller } from './poller.js';
import { Player } from './player.js';
import { ThumbnailCache } from './thumbs.js';
import { Gallery } from './gallery.js';
import { Downloader } from './downloader.js';
import { ActionBar } from './actionbar.js';
import { HomeView, BusyView, ErrorView, ResultsView, ProfileView } from './views/index.js';
import { KINDS_KEY } from './views/home_view.js';

export class App {
  /** @param {{ state: AppState, api: Api, platform: string }} deps */
  constructor({ state, api, platform = 'max' }) {
    this.state = state;
    this.api = api;
    this.platform = platform;

    this.toast = new Toast($('#toast'));
    this.mascot = new Mascot();
    this.nav = new NavBar();
    this.poller = new Poller(() => this.tick());

    // ---- компоненты результата (связаны друг с другом только через колбэки) ----
    const downloader = new Downloader({ state, api, toast: this.toast, platform });
    this.thumbs = new ThumbnailCache({ state, api, onUpdate: () => this.gallery.update() });
    this.player = new Player({
      state, api,
      onNewJob: () => this.gallery.reset(),
      onClipChange: () => this.gallery.update(),
    });
    this.gallery = new Gallery({
      state, thumbs: this.thumbs, toast: this.toast,
      getCurrent: () => this.player.cur,
      onOpen: (i) => { if (this.player.cur !== i) this.player.load(i); },
      onToggle: (i) => this.toggleSelection(i),
    });
    this.actionBar = new ActionBar({ state, downloader, platform, onPrepare: (idxs) => this.prepare(idxs) });

    // ---- экраны ----
    const ctx = {
      state, api, platform, mascot: this.mascot, toast: this.toast,
      showError: (text) => this.errorView.render(text),
    };
    this.homeView = new HomeView(ctx);
    this.busyView = new BusyView(ctx);
    this.errorView = new ErrorView(ctx);
    this.profileView = new ProfileView(ctx);
    this.resultsView = new ResultsView(ctx, {
      player: this.player, gallery: this.gallery, actionBar: this.actionBar,
    });

    // ---- кнопки с data-a="..." ----
    this.actions = {
      scan: () => this.onScanClick(),
      subs: () => {
        state.subs = !state.subs;
        state.saveStyle();
        this.resultsView.renderOptions();
      },
      fmt: () => {
        const order = ['source', 'vert', 'tiktok'];   // исходный → 9:16 → TikTok (вебка сверху)
        state.fmt = order[(order.indexOf(state.fmt) + 1) % order.length];
        state.vert = state.fmt === 'vert';
        state.saveStyle();
        this.resultsView.renderOptions();
      },
      pos: () => {                                   // расположение субтитров: низ → центр → верх
        const order = ['bottom', 'middle', 'top'];
        state.pos = order[(order.indexOf(state.pos) + 1) % order.length];
        state.saveStyle();
        this.resultsView.renderOptions();
      },
      color: () => {                                  // цвет плашки — по кругу из палитры
        const i = PALETTE.indexOf(state.color);
        state.color = PALETTE[(i + 1) % PALETTE.length] || PALETTE[0];
        state.saveStyle();
        this.resultsView.renderOptions();
      },
      anim: () => {
        state.anim = !state.anim;
        state.saveStyle();
        this.resultsView.renderOptions();
      },
      reset: () => this.resetJob(),
      cancel: (button) => this.cancelJob(button),
      cancelup: () => { if (state.up && state.up.abort) state.up.abort(); },
    };
  }

  start() {
    document.addEventListener('click', (e) => this.onClick(e));
    document.addEventListener('change', (e) => {
      if (e.target.id === 'file' && e.target.files[0]) this.uploadFile(e.target.files[0]);
      if (e.target.closest('.cats')) this._saveKinds();     // выбор типов моментов — в localStorage
    });
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && this.poller.active) this.tick();
    });
    return this.restore();
  }

  // ================= навигация и отрисовка =================

  setTab(tab) {
    this.state.tab = tab;
    this.nav.setTab(tab);
  }

  showHome() {
    this.setTab('home');
    if (this.state.up || this.state.job) return this.paint();
    return this.homeView.render();
  }

  showProfile() {
    this.setTab('profile');
    return this.profileView.render();
  }

  refreshBadge() {
    this.nav.setBusy(!!(this.state.up || this.state.busy));
  }

  /** Нарисовать то, что соответствует состоянию: загрузка, скан, ошибка или результат. */
  paint() {
    const s = this.state;
    this.refreshBadge();
    if (s.tab !== 'home') return;
    const j = s.job;

    if (s.up) {
      return this.busyView.render({
        text: 'Загружаю файл — не закрывай приложение', pct: s.up.pct, kind: 'up',
      });
    }
    if (!j) return this.homeView.render();
    if (j.status === 'scanning') {
      return this.busyView.render({
        text: j.progress || 'Сканирую', pct: null, kind: 'scan',
        eta: j.eta_over ? 'дольше обычного, не закрывай приложение' : (j.eta_left > 0 ? etaText(j.eta_left) : ''),
      });
    }
    if (j.status === 'error') return this.errorView.render(j.error);
    return this.resultsView.render();
  }

  // ================= клики =================

  async onClick(e) {
    const tab = this.nav.tabFromClick(e);
    if (tab) return tab === 'home' ? this.showHome() : this.showProfile();

    if (this.gallery.handleClick(e)) return;

    const button = e.target.closest('[data-a]');
    if (!button) return;
    const action = button.dataset.a;
    const handler = this.actions[action];
    if (handler) return handler(button);
    return this.profileView.handleAction(action, button);
  }

  toggleSelection(i) {
    if (!this.state.toggleSelection(i)) {
      return this.toast.show(`Не больше ${MAX_SELECTED_CLIPS} клипов за раз`);
    }
    this.gallery.update();
    this.actionBar.update();
  }

  // ================= жизнь задачи =================

  /** Принять новую задачу с сервера: сбросить выбор, плеер и реплики маскота. */
  adoptJob(job) {
    const s = this.state;
    s.seq++;
    s.job = job;
    s.sel.clear();
    this.player.reset();
    this.mascot.reset();
  }

  /** «Новое видео»: забыть всё про текущую задачу и вернуться на стартовый экран. */
  resetJob() {
    const s = this.state;
    s.seq++;
    this.mascot.reset();
    s.job = null;
    s.sel.clear();
    this.poller.stop();
    this.player.reset();
    this.gallery.reset();
    this.actionBar.hide();
    return this.showHome();
  }

  onScanClick() {
    const url = $('#url').value.trim();
    if (!url) return this.toast.show('Вставь ссылку');
    // пустой выбор категорий — не ошибка: ищем «как раньше» (авто-режим)
    return this.startScan(url, this._readKinds());
  }

  /** Выбранные типы моментов на стартовом экране (чекбоксы). */
  _readKinds() {
    return [...document.querySelectorAll('.cats input:checked')].map((c) => c.dataset.kind);
  }

  /** Выбор типов моментов не должен слетать при перезагрузке страницы. */
  _saveKinds() {
    try { localStorage.setItem(KINDS_KEY, JSON.stringify(this._readKinds())); } catch (_) { /* приватный режим */ }
  }

  async startScan(url, kinds) {
    try {
      this.adoptJob(await this.api.scan(url, kinds));
      this.paint();
      this.poller.start();
    } catch (e) {
      this.toast.show(e.message);
      if (e.status === 409) this.restore();   // у пользователя уже есть активная задача — подхватываем её
    }
  }

  async uploadFile(file) {
    const s = this.state;
    const kinds = this._readKinds();      // пусто — тоже нормально: авто-режим
    s.up = { pct: 0, abort: null };
    this.mascot.reset();
    this.paint();

    const { promise, abort } = this.api.upload(file, (pct) => {
      if (!s.up) return;
      s.up.pct = pct;
      this.busyView.setProgress(pct);
    }, kinds);
    s.up.abort = abort;

    let job;
    try {
      job = await promise;
    } catch (err) {
      s.up = null;
      this.refreshBadge();
      if (err instanceof UploadAborted) return this.showHome();
      return this.errorView.render(err.message || 'Не удалось загрузить файл');
    }
    s.up = null;
    this.adoptJob(job);
    this.paint();
    this.poller.start();
  }

  async cancelJob(button) {
    button.disabled = true;
    try {
      await this.api.cancel(this.state.job.id);
    } catch (x) {
      if (x.status !== 404) {            // 404 — задачи уже нет на сервере, значит, всё равно сбрасываем
        this.toast.show(x.message);
        return this.tick();
      }
    }
    return this.resetJob();
  }

  /** Запустить рендер выбранных клипов (по одному запросу на клип). */
  async prepare(idxs) {
    const s = this.state;
    for (const i of idxs) {
      try {
        s.job = await this.api.prepare(s.job.id, i, s.subs, s.fmt === 'vert', s.color, s.anim,
          s.pos, s.fmt);
      } catch (e) {
        this.toast.show(e.message);
        break;
      }
    }
    s.seq++;
    this.paint();
    this.poller.start();
  }

  // ================= поллинг =================

  async tick() {
    const s = this.state;
    if (!s.job) return this.poller.stop();
    const seq = s.seq;
    try {
      const j = await this.api.job(s.job.id);
      if (seq !== s.seq) return;       // пока ждали ответ, задачу сменили
      s.job = j;
      if (!s.busy) this.poller.stop();
      this.paint();
    } catch (e) {
      if (e.status === 404 || e.status === 401) {
        this.poller.stop();
        s.job = null;
        this.paint();
      }
    }
  }

  /** При открытии приложения подхватить задачу, которая уже идёт на сервере. */
  async restore() {
    try {
      const d = await this.api.active();
      if (d.job) {
        this.adoptJob(d.job);
        if (this.state.busy) this.poller.start();
      }
    } catch (_) { /* нет активной задачи или сети — просто покажем стартовый экран */ }
    return this.paint();
  }
}
