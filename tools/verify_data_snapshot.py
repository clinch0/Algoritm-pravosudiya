"""Read-only comparison of bundled JSON with bundled official XLS snapshots."""
import json
from pathlib import Path
from build_official_stats import parse_year, DATA, COLUMNS


def verify_law_history():
    """Проверка структуры data/law_history.json (частичная история редакций)."""
    import re as _re
    path = DATA / 'law_history.json'
    if not path.exists():
        return {'error': 'law_history.json отсутствует'}
    data = json.loads(path.read_text(encoding='utf-8'))
    articles = data.get('articles', {})
    problems = []
    date_re = _re.compile(r'^[0-9]{2}[.][0-9]{2}[.][0-9]{4}$')
    for article, entry in articles.items():
        if not isinstance(entry.get('amendments'), list):
            problems.append(article + ': нет списка amendments')
            continue
        for am in entry['amendments']:
            if not date_re.match(str(am.get('date', ''))):
                problems.append(article + ': неверная дата ' + str(am.get('date')))
            for ch in am.get('changes', []):
                if 'was' not in ch or 'became' not in ch:
                    problems.append(article + ': изменение без was/became')
    return {'articles': len(articles), 'problems': problems}


def verify():
    original = json.loads((DATA/'official_stats.json').read_text(encoding='utf-8'))
    report = {}
    for year in ('2023','2024'):
        rebuilt = parse_year(year)
        stored = original['years'][year]
        differences = []
        comparisons = 0
        for key, row in stored.items():
            for column in COLUMNS:
                comparisons += 1
                if key not in rebuilt or row.get(column) != rebuilt[key].get(column):
                    differences.append({'key':key, 'column':column, 'stored':row.get(column), 'rebuilt':rebuilt.get(key,{}).get(column)})
        report[year] = {'stored_rows':len(stored), 'parsed_rows':len(rebuilt), 'compared_values':comparisons,
                        'mismatches':differences, 'new_keys':sorted(set(rebuilt)-set(stored))}
    report['law_history'] = verify_law_history()
    return report


if __name__ == '__main__':
    report = verify()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    bad = any((isinstance(v, dict) and (v.get('error') or v.get('mismatches') or v.get('new_keys') or v.get('problems')))
              for v in report.values())
    raise SystemExit(1 if bad else 0)
