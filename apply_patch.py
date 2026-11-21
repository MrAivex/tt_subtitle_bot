"""Накатывает правки (длина клипов + вид субтитров) на файлы репозитория.
Запуск из корня проекта:  python apply_patch.py
Каждый файл правится атомарно: если хоть одно место не совпало — файл не трогается."""
import re, pathlib, sys

ROOT = pathlib.Path('.')
MAP = {
    'ass_builder.py': 'subtitles/ass_builder.py', 'renderer.py': 'subtitles/renderer.py',
    'picker.py': 'highlights/picker.py', 'analyzer.py': 'highlights/analyzer.py',
    'scan_service.py': 'miniapp/scan_service.py', 'jobs.py': 'miniapp/jobs.py',
    'clips_handlers.py': 'miniapp/clips_handlers.py', 'render_service.py': 'miniapp/render_service.py',
    'index.html': 'miniapp/index.html',
}
failed = []


def write_new(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    print('создан', path)


def patch(name, pairs):
    path = ROOT / MAP[name]
    if not path.exists():
        failed.append((MAP[name], 'файл не найден')); return
    t = path.read_text(encoding='utf-8')
    if 'clip_sec' in t or 'subtitles.style' in t or 'subStyle' in t:
        print('уже применено, пропускаю', MAP[name]); return
    for kind, a, b in pairs:
        if kind == 's':
            n = t.count(a)
            if n != 1:
                failed.append((MAP[name], f'не нашёл/неоднозначно ({n}): {a[:60]!r}')); return
            t = t.replace(a, b)
        else:
            t, n = re.subn(a, (b if callable(b) else (lambda m, b=b: b)), t, flags=re.S)
            if n != 1:
                failed.append((MAP[name], f'regex совпал {n} раз: {a[:60]!r}')); return
    path.write_text(t, encoding='utf-8')
    print('исправлен', MAP[name])


# ------------------------------------------------------------------ style.py (новый)
write_new('subtitles/style.py', r'''# subtitles/style.py
"""Настройки вида субтитров, которые выбирает пользователь (положение, цвет, анимация)."""
from dataclasses import dataclass, asdict

POSITIONS = ("bottom", "middle", "top")
ANIMS = ("fly", "drop", "fade", "none")
# id -> (цвет текста RRGGBB, цвет плашки активного слова RRGGBB или None, если плашки нет)
COLORS = {
    "violet": ("FFFFFF", "9D4EDD"),
    "pink":   ("FFFFFF", "FF5FA2"),
    "red":    ("FFFFFF", "E5384F"),
    "green":  ("FFFFFF", "1FA971"),
    "yellow": ("FFD23F", None),
    "white":  ("FFFFFF", None),
}
_RISE = {"fly": 1.0, "drop": -1.0, "fade": 0.0, "none": 0.0}


def _ass_color(rgb: str) -> str:
    """RRGGBB -> &H00BBGGRR (порядок байт в ASS обратный)."""
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


@dataclass(frozen=True)
class SubStyle:
    pos: str = "bottom"
    color: str = "violet"
    anim: str = "fly"

    @classmethod
    def from_dict(cls, d) -> "SubStyle":
        """Берём только известные значения: всё остальное — по умолчанию."""
        d = d if isinstance(d, dict) else {}
        pos, color, anim = d.get("pos"), d.get("color"), d.get("anim")
        return cls(pos if pos in POSITIONS else "bottom",
                   color if color in COLORS else "violet",
                   anim if anim in ANIMS else "fly")

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def text_ass(self) -> str:
        return _ass_color(COLORS[self.color][0])

    @property
    def plate_ass(self):
        p = COLORS[self.color][1]
        return _ass_color(p) if p else None

    @property
    def rise_dir(self) -> float:
        """+1: слово вылетает снизу, -1: падает сверху, 0: появляется на месте."""
        return _RISE[self.anim]
''')

# ------------------------------------------------------------------ ass_builder.py
patch('ass_builder.py', [
    ('s', 'from typing import Callable, List\n',
          'from typing import Callable, List\n\nfrom subtitles.style import SubStyle\n'),
    ('r', r'(    off: tuple[^\n]*\n)', lambda m: m.group(1) +
          '    text_c: str         # цвет текста (ASS)\n'
          '    plate_c: str        # цвет плашки (ASS)\n'
          '    plate: bool         # есть ли плашка под активным словом\n'
          '    anim_sec: float     # длительность появления слова, 0 = сразу\n'),
    ('r', r'watermark: bool\) -> str:\n        lay = self\._layout\(video_w, video_h\)',
          'watermark: bool, style: SubStyle = None) -> str:\n'
          '        lay = self._layout(video_w, video_h, style or SubStyle())'),
    ('s', '    def _layout(self, w: int, h: int) -> _Layout:',
          '    def _layout(self, w: int, h: int, st: SubStyle) -> _Layout:'),
    ('s', 'rise = fs * RISE_K', 'rise = fs * RISE_K * st.rise_dir'),
    ('r', r'            cx=w / 2, cy=h - margin_v,[^\n]*\n'
          r'            off=tuple\(rise \* \(1 - _ease_out\(p\)\) for p in self\._nodes\),\n        \)\n',
          '            cx=w / 2, cy=self._anchor_y(h, fs, margin_v, st.pos),   # якорь строки: низ по центру\n'
          '            off=tuple(rise * (1 - _ease_out(p)) for p in self._nodes),\n'
          '            text_c=st.text_ass, plate_c=st.plate_ass or "&H00000000",\n'
          '            plate=st.plate_ass is not None,\n'
          '            anim_sec=0.0 if st.anim == "none" else ANIM_SEC,\n'
          '        )\n\n'
          '    @staticmethod\n'
          '    def _anchor_y(h: int, fs: int, margin_v: int, pos: str) -> float:\n'
          '        """Y нижней точки строки: снизу, по центру кадра или сверху."""\n'
          '        if pos == "top":\n'
          '            return round(h * 0.08) + fs * 1.25\n'
          '        if pos == "middle":\n'
          '            return h / 2 + fs * 0.6\n'
          '        return h - margin_v\n'),
    ('s', '&H00DD4E9D', '{L.plate_c}'),
    ('s', 'Style: Text,{L.family},{L.fs},&H00FFFFFF,&H00FFFFFF,&H00000000',
          'Style: Text,{L.family},{L.fs},{L.text_c},{L.text_c},&H00000000'),
    ('s', '    def _timing(line, next_line):', '    def _timing(line, next_line, anim_sec):'),
    ('s', 'an = [ANIM_SEC] * n', 'an = [anim_sec] * n'),
    ('s', 'min(ANIM_SEC, max(0.12', 'min(anim_sec, max(0.12'),
    ('s', 'self._timing(line, next_line)', 'self._timing(line, next_line, L.anim_sec)'),
    ('r', r'\n(\s*)# 3\) плашка', lambda m: '\n' + m.group(1) + 'if not L.plate:\n' +
          m.group(1) + '    continue\n\n' + m.group(1) + '# 3) плашка'),
])

# ------------------------------------------------------------------ renderer.py
patch('renderer.py', [
    ('s', 'def render(self, src, *, premium: bool, vertical: bool) -> RenderResult:',
          'def render(self, src, *, premium: bool, vertical: bool, style=None) -> RenderResult:'),
    ('s', 'watermark=not premium)', 'watermark=not premium, style=style)'),
])

# ------------------------------------------------------------------ picker.py
patch('picker.py', [
    ('s', 'def pick(S, dur, count):', 'def pick(S, dur, count, clip_sec=0):'),
    ('s', '        lo = max(0, int(start / 0.5) - 4)',
          '        if clip_sec:                      # длина задана: пик в первой трети клипа\n'
          '            start = max(0.0, i * 0.5 - 0.35 * clip_sec)\n'
          '            end = min(dur, start + clip_sec)\n'
          '            start = max(0.0, end - clip_sec)\n'
          '        lo = max(0, int(start / 0.5) - 4)'),
])

# ------------------------------------------------------------------ analyzer.py
patch('analyzer.py', [
    ('s', 'def analyze(self, wav_path: str, max_moments: int = 5) -> dict:',
          'def analyze(self, wav_path: str, max_moments: int = 5, clip_sec: float = 0) -> dict:'),
    ('s', 'cands = pick(S, dur, max_moments + 3 if use_asr else max_moments)',
          'cands = pick(S, dur, max_moments + 3 if use_asr else max_moments, clip_sec)'),
])

# ------------------------------------------------------------------ scan_service.py
patch('scan_service.py', [
    ('s', 'self._analyzer.analyze, wav, self._max)', 'self._analyzer.analyze, wav, self._max, job.clip_sec)'),
])

# ------------------------------------------------------------------ jobs.py
patch('jobs.py', [
    ('r', r'(    renders: dict = field\(default_factory=dict\)[^\n]*\n)',
          lambda m: m.group(1) + '    clip_sec: int = 0                 # желаемая длина клипов, 0 = авто\n'),
])

# ------------------------------------------------------------------ clips_handlers.py
patch('clips_handlers.py', [
    ('s', 'from .errors import ApiError', 'from subtitles.style import SubStyle\nfrom .errors import ApiError'),
    ('s', 'VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")',
          'VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")\n'
          'CLIP_CHOICES = (0, 15, 30, 60, 90)      # секунды, 0 = авто\n\n\n'
          'def _clip_sec(v) -> int:\n'
          '    try:\n'
          '        v = int(v)\n'
          '    except (TypeError, ValueError):\n'
          '        return 0\n'
          '    return v if v in CLIP_CHOICES else 0'),
    ('s', '        url = ((await request.json()).get("url") or "").strip()',
          '        body = await request.json()\n        url = (body.get("url") or "").strip()'),
    ('s', 'Job(uid, user.chat_id, LinkSource(url))',
          'Job(uid, user.chat_id, LinkSource(url), clip_sec=_clip_sec(body.get("clip_sec")))'),
    ('s', 'Job(uid, user.chat_id, FileSource(path, stem, self._ffmpeg))',
          'Job(uid, user.chat_id, FileSource(path, stem, self._ffmpeg),\n'
          '                                clip_sec=_clip_sec(request.query.get("clip")))'),
    ('r', r'        cur = job\.renders\.get\(idx\).*?bool\(body\.get\("vertical", False\)\)\)\)\n',
          '        subs = bool(body.get("subtitles", True))\n'
          '        vertical = bool(body.get("vertical", False))\n'
          '        style = SubStyle.from_dict(body.get("style")) if subs else SubStyle()\n'
          '        opts = {"subs": subs, "vert": vertical, **style.as_dict()}\n'
          '        cur = job.renders.get(idx)\n'
          '        if cur and cur["status"] in ("pending", "ready") and cur.get("opts") == opts:\n'
          '            return web.json_response(self._pub(job))\n'
          '        if cur and cur["status"] == "pending":\n'
          '            raise ApiError("Клип ещё готовится с другими настройками — подожди", 409)\n'
          '        if cur:                            # настройки сменились — рендерим заново\n'
          '            rm(cur.get("path"), *cur.get("extra", []))\n'
          '        job.renders[idx] = {"status": "pending", "opts": opts}\n'
          '        spawn(self._render.run(job, idx, subs, vertical, style, opts))\n'),
])

# ------------------------------------------------------------------ render_service.py
patch('render_service.py', [
    ('s', 'async def run(self, job, idx: int, subs: bool, vertical: bool):',
          'async def run(self, job, idx: int, subs: bool, vertical: bool, style=None, opts=None):'),
    ('s', 'job.renders[idx] = await self._full(job, vertical, extra)',
          'res = await self._full(job, vertical, extra, style)'),
    ('s', 'job.renders[idx] = await self._clip(job, idx, subs, vertical, extra)',
          'res = await self._clip(job, idx, subs, vertical, extra, style)'),
    ('s', '            job.progress = ""',
          '            job.renders[idx] = {**res, "opts": opts}\n            job.progress = ""'),
    ('s', '{"status": "error", "error": e.msg}', '{"status": "error", "error": e.msg, "opts": opts}'),
    ('s', '{str(e)[:120]}"}', '{str(e)[:120]}", "opts": opts}'),
    ('s', 'async def _clip(self, job, idx, subs, vertical, extra) -> dict:',
          'async def _clip(self, job, idx, subs, vertical, extra, style=None) -> dict:'),
    ('s', 'async def _full(self, job, vertical, extra) -> dict:',
          'async def _full(self, job, vertical, extra, style=None) -> dict:'),
    ('s', 'self._renderer.render, clip, premium=job.premium, vertical=vertical)',
          'self._renderer.render, clip, premium=job.premium, vertical=vertical, style=style)'),
    ('s', 'self._renderer.render, src, premium=job.premium, vertical=vertical)',
          'self._renderer.render, src, premium=job.premium, vertical=vertical, style=style)'),
])

# ------------------------------------------------------------------ index.html
CSS = r'''.chips{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 12px}
.chips button{margin:0;padding:8px 6px;flex:1 1 17%;font-size:13px;box-shadow:0 3px 0 var(--sh)}
.chips button.on{background:var(--lav);color:#fff;text-shadow:0 2px 0 rgba(42,31,69,.35)}
.chips .sw{flex:0 0 40px;width:40px;height:40px;padding:0;border-radius:50%;font-size:13px}
.chips .sw.on{outline:3px solid var(--sun);outline-offset:2px}
.lbl{font:800 13px var(--h);color:var(--mute);margin:10px 2px 0}
.card .chips{margin-bottom:4px}
.subpv{position:absolute;left:6%;right:6%;text-align:center;pointer-events:none;font:900 18px/1.25 var(--h);color:#fff;
  -webkit-text-stroke:4px #000;paint-order:stroke fill}
.subpv[hidden]{display:none}
.subpv.bottom{bottom:26%}.subpv.top{top:14%}.subpv.middle{top:50%;margin-top:-12px}
.subpv i{font-style:normal;padding:0 6px;border-radius:7px}
@keyframes sfly{from{transform:translateY(70%);opacity:0}}
@keyframes sdrop{from{transform:translateY(-70%);opacity:0}}
@keyframes sfade{from{opacity:0}}
.subpv.a-fly{animation:sfly .4s ease-out}.subpv.a-drop{animation:sdrop .4s ease-out}.subpv.a-fade{animation:sfade .5s}
'''

JS_TOP = r'''const POS={bottom:'Снизу',middle:'По центру',top:'Сверху'};
const COL={violet:['#fff','#9D4EDD'],pink:['#fff','#FF5FA2'],red:['#fff','#E5384F'],green:['#fff','#1FA971'],yellow:['#FFD23F',null],white:['#fff',null]};
const ANI={fly:'Снизу вверх',drop:'Сверху вниз',fade:'Проявление',none:'Без анимации'};
const CLIPS=[[0,'Авто'],[15,'15 с'],[30,'30 с'],[60,'60 с'],[90,'90 с']];
try{const sv=JSON.parse(localStorage.getItem('opts')||'{}'),z=sv.style||{};
  if(CLIPS.some(c=>c[0]===sv.clip))S.clip=sv.clip;
  if(POS[z.pos]&&COL[z.color]&&ANI[z.anim])S.style={pos:z.pos,color:z.color,anim:z.anim}}catch(e){}
const saveOpts=()=>{try{localStorage.setItem('opts',JSON.stringify({clip:S.clip,style:S.style}))}catch(e){}};
const chips=(a,items,cur)=>items.map(([v,t])=>`<button data-a="${a}" data-v="${v}" class="${String(v)===String(cur)?'on':''}">${t}</button>`).join('');
const swatches=cur=>Object.entries(COL).map(([k,[t,p]])=>`<button class="sw ${k===cur?'on':''}" data-a="scol" data-v="${k}" aria-label="${k}" style="background:${p||'#2a1f45'};color:${t}">Aa</button>`).join('');
// клип уже отрисован, но с другими настройками — его надо готовить заново
const stale=r=>{const o=r&&r.opts,st=S.style;
  return !!o&&(o.subs!==S.subs||o.vert!==S.vert||(S.subs&&(o.pos!==st.pos||o.color!==st.color||o.anim!==st.anim)))};
const esc=s=>String(s)'''

JS_FUNCS = r'''/* ---------- вид субтитров ---------- */
function subPv(replay){
  const e=$('#subpv');if(!e)return;
  if(!S.subs){e.hidden=true;return}
  const st=S.style,c=COL[st.color];
  e.hidden=false;
  e.className='subpv '+st.pos+' a-'+st.anim;
  e.style.color=c[0];
  e.innerHTML=`пример <i style="${c[1]?'background:'+c[1]+';color:#fff':''}">субтитров</i>`;
  if(replay){e.style.animation='none';void e.offsetWidth;e.style.animation=''}
}
function updateSty(replay){
  const el=$('#sty');if(!el)return;
  if(!S.subs){el.innerHTML='';subPv(false);return}
  const st=S.style;
  el.innerHTML=`<div class="card"><b>Вид субтитров</b>
    <div class="lbl">Положение</div><div class="chips">${chips('spos',Object.entries(POS),st.pos)}</div>
    <div class="lbl">Цвет</div><div class="chips">${swatches(st.color)}</div>
    <div class="lbl">Анимация</div><div class="chips">${chips('sanim',Object.entries(ANI),st.anim)}</div></div>`;
  subPv(replay);
}
const refreshSel=()=>{updateGallery();updateAct()};
function badge(){'''

CLICKS = r'''else if(a==='clip'){S.clip=+b.dataset.v;saveOpts();$('#clipch').innerHTML=chips('clip',CLIPS,S.clip)}
  else if(a==='spos'||a==='scol'||a==='sanim'){
    S.style[{spos:'pos',scol:'color',sanim:'anim'}[a]]=b.dataset.v;saveOpts();updateSty(true);refreshSel()}
  else if(a==='reset'){resetSay();'''

patch('index.html', [
    ('s', '@media(prefers-reduced-motion:reduce)', CSS + '@media(prefers-reduced-motion:reduce)'),
    ('s', "up:null,seq:0};", "up:null,seq:0,clip:0,style:{pos:'bottom',color:'violet',anim:'fly'}};"),
    ('s', 'const esc=s=>String(s)', JS_TOP),
    ('s', '<video id="pv" playsinline preload="metadata"></video>',
          '<video id="pv" playsinline preload="metadata"></video>\n      <div class="subpv" id="subpv" hidden></div>'),
    ('s', 'bindPlayer();', 'bindPlayer();subPv(true);'),
    ('s', 'Object.entries(renders()).map(([k,v])=>k+v.status),[...S.sel]',
          "Object.entries(renders()).map(([k,v])=>k+v.status+(stale(v)?'s':'')),[...S.sel]"),
    ('s', "${r&&r.status==='ready'?", "${r&&r.status==='ready'&&!stale(r)?"),
    ('s', "const st=idxs.map(i=>(rs[String(i)]||{}).status);",
          "const st=idxs.map(i=>{const r=rs[String(i)]||{};return r.status==='ready'&&stale(r)?'stale':r.status});"),
    ('s', '<div class="grid" id="grid"></div><div class="opts" id="opts"></div>',
          '<div class="grid" id="grid"></div><div id="sty"></div><div class="opts" id="opts"></div>'),
    ('s', "${full&&full.status==='ready'?", "${full&&full.status==='ready'&&!stale(full)?"),
    ('s', '<button data-a="reset">Новое видео</button>`;', '<button data-a="reset">Новое видео</button>`;\n  updateSty();'),
    ('s', 'function badge(){', JS_FUNCS),
    ('s', "else if(a==='subs'){S.subs=!S.subs;updateOpts()}", "else if(a==='subs'){S.subs=!S.subs;updateOpts();refreshSel()}"),
    ('s', "else if(a==='fmt'){S.vert=!S.vert;updateOpts()}", "else if(a==='fmt'){S.vert=!S.vert;updateOpts();refreshSel()}"),
    ('s', "else if(a==='reset'){resetSay();", CLICKS),
    ('s', "start('/scan',{url:u})", "start('/scan',{url:u,clip_sec:S.clip})"),
    ('s', "x.open('POST','/api/upload');", "x.open('POST','/api/upload?clip='+S.clip);"),
    ('s', '{idx,subtitles:S.subs,vertical:S.vert}', '{idx,subtitles:S.subs,vertical:S.vert,style:S.style}'),
    ('s', '{idx:i,subtitles:S.subs,vertical:S.vert}', '{idx:i,subtitles:S.subs,vertical:S.vert,style:S.style}'),
    ('s', '<input id="url" type="url" placeholder=',
          '<div class="lbl">Длина клипов</div>\n  <div class="chips" id="clipch">${chips(\'clip\',CLIPS,S.clip)}</div>\n'
          '  <input id="url" type="url" placeholder='),
])

if failed:
    print('\nНЕ ПРИМЕНЕНО:')
    for f, why in failed:
        print(' -', f, '→', why)
    sys.exit(1)
print('\nГотово')
