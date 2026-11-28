"""tg/index_patch.py — превращает miniapp/index.html (MAX) в версию для Telegram на лету.

Так фронт остаётся в одном экземпляре: правишь miniapp/index.html — меняется и MAX, и TG.
Что меняется:
  1) window.WebApp = Telegram.WebApp — SDK Telegram уже подгружен локально
     (/static/vendor/miniapp-sdk.js читает tgWebAppData из hash так же, как официальный SDK;
     внешний https://telegram.org/js/telegram-web-app.js больше НЕ подключаем —
     в РФ он недоступен с ряда провайдеров, и страница висела до ERR_TIMED_OUT);
  2) на весь экран и без закрытия свайпом вниз (иначе перемотка плеера сворачивает апп);
  3) скачивание: <a download> внутри Telegram-WebView не работает → WebApp.downloadFile
     (Bot API 8.0+), на старых клиентах — открытие ссылки во внешнем браузере.
"""

MAX_SDK = '<script src="https://st.max.ru/js/max-web-app.js"></script>'

TG_HEAD = """<script>
/* Telegram: SDK уже есть локально (vendor/miniapp-sdk.js), внешний скрипт не нужен. */
window.WebApp=window.Telegram&&window.Telegram.WebApp;
try{var _w=window.WebApp;_w.ready();_w.expand();if(_w.disableVerticalSwipes)_w.disableVerticalSwipes()}catch(e){}
</script>"""

TG_TAIL = """<script>
/* Telegram: переопределяем скачивание (функции из основного скрипта глобальные) */
(function(){
  var W=window.Telegram&&window.Telegram.WebApp;
  var abs=function(u){return new URL(u,location.href).href};
  var canDl=!!(W&&W.downloadFile&&W.isVersionAtLeast&&W.isVersionAtLeast('8.0'));
  function dl(i){
    return new Promise(function(res){
      var r=renders()[String(i)];
      if(!r||r.status!=='ready')return res(false);
      var url=abs(mediaUrl('download',i)),name=r.name||('clip_'+(i+1)+'.mp4');
      if(canDl){
        try{W.downloadFile({url:url,file_name:name},function(ok){res(!!ok)});return}catch(e){}
      }
      try{W.openLink(url)}catch(e){window.open(url,'_blank')}
      res(true);
    });
  }
  window.downloadOne=function(i){dl(i)};
  window.downloadSelected=async function(idxs){
    toast(canDl?'Подтверди сохранение каждого файла':'Открываю файлы по очереди');
    for(var k=0;k<idxs.length;k++){await dl(idxs[k]);await new Promise(function(r){setTimeout(r,400)})}
  };
})();
</script>"""


def patch_for_telegram(html: str) -> str:
    if MAX_SDK in html:
        html = html.replace(MAX_SDK, "", 1)          # старый index с внешним SDK — убираем
    return html.replace("</body>", TG_TAIL + "\n</body>", 1).replace(
        "</head>", TG_HEAD + "\n</head>", 1)
