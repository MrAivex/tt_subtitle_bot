// static/js/player.js — плеер превью: свой трек, звук, запоминание позиции по клипам.
import { $, esc, fmt } from './utils.js';

const TEMPLATE = `<div class="player">
  <video id="pv" playsinline preload="metadata"></video>
  <span class="ptag" id="ptag"></span>
  <button class="roundtr" id="mute" aria-label="Звук">🔊</button>
  <button class="center" id="bigplay" aria-label="Смотреть">▶</button>
  <div class="pload" id="pload"><span class="spin"></span> Превью готовится…</div>
  <div class="pbar">
    <div class="ptime" id="ptime">0:00 / 0:00</div>
    <div class="track" id="track"><i class="line"></i><i class="fill" id="fill"></i><b class="knob" id="knob"></b></div>
  </div>
</div>
<div class="meta" id="curmeta"></div>`;

const LOADING = '<span class="spin"></span> Превью готовится…';

export class Player {
  /**
   * @param {object}   deps
   * @param {AppState} deps.state
   * @param {Api}      deps.api
   * @param {Function} deps.onNewJob     — плеер увидел другую задачу (галерее пора сбросить кэш)
   * @param {Function} deps.onClipChange — в плеере открыт другой клип (галерее пора подсветить плитку)
   */
  constructor({ state, api, onNewJob, onClipChange }) {
    this._state = state;
    this._api = api;
    this._onNewJob = onNewJob;
    this._onClipChange = onClipChange;
    this.jobId = null;          // для какой задачи собран плеер
    this.cur = -1;              // номер клипа, открытого сейчас
    this._times = new Map();    // клип → позиция, на которой остановились
    this._drag = false;
  }

  /** Забыть задачу: следующий ensure() соберёт плеер заново. */
  reset() {
    this.jobId = null;
    this.cur = -1;
  }

  /** Собрать плеер (если ещё не собран) и открыть первый готовый клип. */
  ensure() {
    const j = this._state.job;
    const fresh = this.jobId !== j.id;
    if (fresh || !$('#pv')) {
      if (fresh) {
        this._times.clear();
        this._onNewJob();
      }
      this.jobId = j.id;
      this.cur = -1;
      $('#pbox').innerHTML = TEMPLATE;
      this._bind();
    }
    if (this.cur !== -1) return;

    const first = (j.previews || []).find((p) => p.status === 'ready');
    if (first) {
      this.load(first.idx);
    } else if (!j.moments.length) {
      $('#pbox').hidden = true;
    } else {
      const pl = $('#pload');
      pl.hidden = false;
      pl.innerHTML = j.previews_status === 'error' ? 'Превью не удалось' : LOADING;
    }
  }

  /** Открыть клип idx. */
  load(idx) {
    const j = this._state.job;
    this.cur = idx;
    const v = $('#pv');
    v.pause();
    $('#pload').hidden = false;
    $('#pload').innerHTML = LOADING;
    v.src = this._api.mediaUrl(j, 'preview', idx);
    v.load();

    const resumeAt = this._times.get(idx) || 0;
    v.onloadedmetadata = () => {
      $('#pload').hidden = true;
      if (resumeAt > 0 && v.duration) v.currentTime = Math.min(resumeAt, Math.max(0, v.duration - 0.3));
      this._refreshTime();
    };

    const m = j.moments[idx];
    $('#curmeta').innerHTML =
      `<b>${esc(this._state.clipName(idx))}</b><small>${esc(m.label || 'Яркий момент')}</small>` +
      (m.snippet ? `<small>«${esc(m.snippet)}»</small>` : '');
    $('#ptag').textContent = `${idx + 1} / ${j.moments.length}`;
    $('#bigplay').style.display = 'flex';
    this._refreshTime();
    this._onClipChange();
  }

  // ---------- внутреннее ----------

  _bind() {
    const v = $('#pv');
    v.addEventListener('timeupdate', () => {
      if (this.cur >= 0) this._times.set(this.cur, v.currentTime);
      this._refreshTime();
    });
    v.addEventListener('loadedmetadata', () => this._refreshTime());
    v.addEventListener('play', () => { $('#bigplay').style.display = 'none'; });
    v.addEventListener('pause', () => { $('#bigplay').style.display = 'flex'; });
    v.addEventListener('ended', () => { $('#bigplay').style.display = 'flex'; });
    v.addEventListener('error', () => {
      const pl = $('#pload');
      if (pl) {
        pl.hidden = false;
        pl.innerHTML = 'Не удалось загрузить превью';
      }
    });

    const toggle = () => (v.paused ? v.play() : v.pause());
    $('#bigplay').onclick = (e) => { e.stopPropagation(); toggle(); };
    v.onclick = toggle;
    $('#mute').onclick = (e) => {
      e.stopPropagation();
      v.muted = !v.muted;
      $('#mute').textContent = v.muted ? '🔇' : '🔊';
    };

    this._bindTrack(v);
  }

  _bindTrack(v) {
    const tr = $('#track');
    const seek = (e) => {
      const r = tr.getBoundingClientRect();
      const f = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      if (v.duration) v.currentTime = f * v.duration;
      this._refreshTime();
    };
    tr.addEventListener('pointerdown', (e) => { this._drag = true; tr.setPointerCapture(e.pointerId); seek(e); });
    tr.addEventListener('pointermove', (e) => { if (this._drag) seek(e); });
    tr.addEventListener('pointerup', () => { this._drag = false; });
    tr.addEventListener('pointercancel', () => { this._drag = false; });
  }

  _refreshTime() {
    const v = $('#pv');
    if (!v) return;
    const pt = $('#ptime');
    if (!pt) return;
    const d = v.duration || 0;
    const c = v.currentTime || 0;
    pt.textContent = `${fmt(c)} / ${fmt(d)}`;
    const f = d ? Math.min(100, (c / d) * 100) : 0;
    $('#fill').style.width = f + '%';
    $('#knob').style.left = f + '%';
  }
}
