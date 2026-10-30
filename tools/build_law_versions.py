# -*- coding: utf-8 -*-
"""Сборка data/law_versions.json: реконструкция старых пределов санкций.

Источник: data/law_history.json (частичная история правок с «было/стало») +
текущие тексты статей (data/ukrf_articles_text.json).
Логика: строка-изменение, чей «стало»-текст содержится в текущем тексте части,
а «было» содержит санкцию лишения свободы, отличную от текущей, — это изменение
санкции этой части до даты правки. История частичная: реконструкция неполна.
"""
import json, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
BASE = str(Path(__file__).resolve().parents[1] / 'data')

NUM = {'одного':1,'одной':1,'двух':2,'трех':3,'трёх':3,'четырех':4,'четырёх':4,'пяти':5,'шести':6,
       'семи':7,'восьми':8,'девяти':9,'десяти':10,'одиннадцати':11,'двенадцати':12,'тринадцати':13,
       'четырнадцати':14,'пятнадцати':15,'шестнадцати':16,'семнадцати':17,'восемнадцати':18,
       'девятнадцати':19,'двадцати':20}

def num_of(s):
    s = (s or '').strip()
    if s.isdigit():
        return float(s)
    return NUM.get(s)

def parse_ls_limits(text):
    """(min|None, max|None) лишения свободы из фрагмента санкции."""
    m = re.search(r'лишен\S*?\s*свободы[^.]{0,120}?срок\s*от\s*(\S+?)\s+до\s+(\S+?)\s*(?:лет|года|год)', text)
    if m:
        lo, hi = num_of(m.group(1)), num_of(m.group(2))
        return (lo, hi) if (lo is not None and hi is not None) else (None, None)
    m = re.search(r'лишен\S*?\s*свободы[^.]{0,120}?срок\s*до\s*(\S+?)\s*(?:лет|года|год)', text)
    if m:
        return None, num_of(m.group(1))
    return None, None

def split_parts(text):
    text = re.sub(r'\s+', ' ', text)
    marks = [(m.start(), int(m.group(1))) for m in re.finditer(r'(?<![\d.])(\d{1,2})\.\s', text)]
    parts = {}
    for i, (pos, pnum) in enumerate(marks):
        end = marks[i+1][0] if i+1 < len(marks) else len(text)
        if pnum not in parts:
            parts[pnum] = text[pos:end]
    return parts

def norm(s):
    return re.sub(r'\s+', ' ', (s or '').lower().replace('ё', 'е')).strip()

history = json.load(open(BASE + r'\law_history.json', encoding='utf-8'))
texts = json.load(open(BASE + r'\ukrf_articles_text.json', encoding='utf-8'))
sanc = json.load(open(BASE + r'\ukrf_sanctions.json', encoding='utf-8'))
current = {}
for a in sanc['articles']:
    current[(a['article'], a['part'])] = (a['imprisonment_min_years'], a['imprisonment_max_years'])

versions = []
for article, entry in history['articles'].items():
    if article not in texts:
        continue
    parts = split_parts(texts[article]['text'])
    part_texts = {str(p): norm(t) for p, t in parts.items()}
    for am in entry.get('amendments', []):
        for c in am.get('changes', []):
            old = parse_ls_limits(c.get('was', ''))
            if old == (None, None):
                continue
            frag = norm(c.get('became', ''))[:90]
            if not frag:
                continue
            matched_part = None
            for part, ptext in part_texts.items():
                if frag in ptext:
                    matched_part = part
                    break
            if matched_part is None:
                continue
            cur = current.get((article, matched_part))
            if cur is None:
                continue
            lo_old, hi_old = old
            lo_cur, hi_cur = cur
            same = (abs(lo_old - lo_cur) < 0.01 if lo_old is not None and lo_cur is not None
                    else lo_old is None and lo_cur is None) and abs(hi_old - hi_cur) < 0.01
            if same:
                continue  # санкция не менялась — строка сдвинулась из-за нового пункта
            versions.append({'article': article, 'part': matched_part,
                             'changed_after': am['date'],
                             'limits_before': {'min': lo_old, 'max': hi_old},
                             'limits_after': {'min': lo_cur, 'max': hi_cur},
                             'evidence_was': c.get('was', '')[:300],
                             'evidence_became': c.get('became', '')[:300]})
versions.sort(key=lambda v: (v['article'], v['part'], v['changed_after']))
out = {'_source': 'Реконструкция из law_history.json + ukrf_articles_text.json',
       '_note': 'Частичная история: учтены только правки, отданные источником; реконструкция требует юридической проверки.',
       '_built_at': '2026-10-29',
       'changes': versions}
json.dump(out, open(BASE + r'\law_versions.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for v in versions:
    print(v['article'], 'ч.' + v['part'], 'после', v['changed_after'], '-> было', v['limits_before'])
print('всего изменений санкций:', len(versions))