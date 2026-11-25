// static/js/nav.js — нижняя навигация «Видео / Профиль».

export class NavBar {
  setTab(tab) {
    document.querySelectorAll('nav button')
      .forEach((b) => b.classList.toggle('on', b.dataset.t === tab));
  }

  /** Звёздочка на вкладке «Видео», пока что-то считается. */
  setBusy(on) {
    document.querySelector('nav [data-t=home]').classList.toggle('busy', on);
  }

  /** Имя вкладки, если клик пришёлся на навигацию, иначе null. */
  tabFromClick(e) {
    const b = e.target.closest('nav button');
    return b ? b.dataset.t : null;
  }
}
