# highlights/kinds.py
"""Типы моментов и словарик ключевых слов для ASR."""
import re

KINDS = {
    "fight":  ("Бой, серия убийств", "🔫", 1.00),
    "funny":  ("Смешной момент", "😂", 0.95),
    "shock":  ("Шок, неожиданность", "😱", 0.90),
    "win":    ("Победа, овации", "🏆", 0.90),
    "absurd": ("Абсурд, баг", "🤡", 0.90),
    "hype":   ("Эмоциональный всплеск", "🔥", 0.70),
}

LEXICON = {
    "fight": r"убил|убит|убью|килл|кильн|снёс|снес[лу]|вынес|выпилил|хедш|хэдш|хэд|дабл|трипл|квадр|"
             r"пентакилл|эйс|\bace\b|зачист|перестрел|файт|замес|тимфайт|разнёс|разнес",
    "funny": r"ха-?ха|ахах|хах|ржу|ржал|ржач|смешн|угар|\bлол|кринж|прикол|шутк|умор|\bору\b|ржак|рофл|хихик",
    "shock": r"не может быть|ничего себе|офигеть|охренеть|\bого+\b|нифига|капец|кошмар|\bвау|ужас|жесть|"
             r"что происходит|не понял|как это|\b(?:а-?){3,}|\b(?:о-?){3,}",
    "win":   r"клатч|победа|победил|выиграл|чемпион|топ[\s-]?1|\bgg\b|\bгг\b|\bвин\b|красав|выжил",
    "absurd": r"\bбаг|глюк|лагает|\bлаг\b|застрял|сломал|что за|странн|абсурд|как так|сам себя|"
              r"телепорт|невозможн|текстур|вылет|зачем он|почему он",
}
_LEX_RE = {k: re.compile(v, re.IGNORECASE) for k, v in LEXICON.items()}


def apply_text(cats, text, seg_sec):
    """Подмешивает слова из расшифровки к оценкам типов."""
    cats = dict(cats)
    for kind, rx in _LEX_RE.items():
        hits = len(rx.findall(text))
        if hits:
            cats[kind] = min(1.0, cats[kind] + 0.5 * min(hits, 3) / 3)
    words = len(text.split())
    if seg_sec > 0 and words / seg_sec > 3.2:
        cats["hype"] = min(1.0, cats["hype"] + 0.15)
    return cats


def label(cats):
    """Определить тип и подпись момента."""
    ranked = sorted(((KINDS[k][2] * cats[k], k) for k in KINDS), reverse=True)
    top_v, top_k = ranked[0]
    if top_v < 0.08:
        return "hype", ["hype"], "🔊", "Громкий момент 🔊"
    tags, emoji = [top_k], KINDS[top_k][1]
    for v, k in ranked[1:]:
        if len(tags) < 2 and v >= 0.6 * top_v and v >= 0.2:
            tags.append(k)
            emoji += KINDS[k][1]
    return top_k, tags, emoji, f"{KINDS[top_k][0]} {emoji}"
