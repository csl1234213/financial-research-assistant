"""Reversible selector wire representation; never modifies canonical Tree data."""

import json
import re
import string
from collections import Counter
from functools import lru_cache

FORMAT_DESCRIPTION = (
    'q=query,d=phrases,h=labels,n=[handle,label refs]. In h,$c expands d[c]; $$ is literal $. '
    'Refs use comma-separated integers or inclusive a:b ranges. '
    'p integer means pages p+row index; otherwise p lists page ranges. '
    'Titles default to Page/page range; t overrides titles by handle.'
)
_KEYS = string.ascii_uppercase + string.ascii_lowercase + string.digits + ':;!%&()*+,-./<=>?@[]^_`{|}~'
_REFERENCE = re.compile(r'(\$(?:\$|.))')


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _plain_parts(label):
    return _REFERENCE.split(label)[::2]


def _replace_plain(label, phrase, reference):
    parts = _REFERENCE.split(label)
    return ''.join(part.replace(phrase, reference) if i % 2 == 0 else part for i, part in enumerate(parts))


@lru_cache(maxsize=8)
def _encode_labels(original):
    # Cache only immutable content transforms, never tenant/node identities.
    labels = tuple(label.replace('$', '$$') for label in original)
    if sum(len(label) for label in labels) > 65536:
        return (), labels  # Bounded preprocessing; the unchanged byte gate rejects oversized output.
    phrases = []
    for key in _KEYS:
        counts = Counter()
        plain = [part for label in labels for part in _plain_parts(label)]
        for segment in plain:
            for length in range(2, min(24, len(segment)) + 1):
                counts.update(segment[i:i + length] for i in range(len(segment) - length + 1))
        ranked = []
        for phrase, count in counts.items():
            if count < 2 or '$' in phrase:
                continue
            overhead = len(_json({key: phrase}).encode('utf-8')) - 1
            gain = len(phrase.encode('utf-8')) - 2
            upper = count * gain - overhead
            if upper > 0:
                ranked.append((upper, phrase, gain, overhead))
        best = None
        for upper, phrase, gain, overhead in sorted(ranked, reverse=True):
            # Overlapping substring counts are an upper bound. Only evaluate
            # contenders that can beat the best actual non-overlapping saving.
            if best is not None and (upper, phrase) <= best:
                break
            occurrences = sum(part.count(phrase) for part in plain)
            saving = occurrences * gain - overhead
            candidate = saving, phrase
            if best is None or candidate > best:
                best = candidate
        if best is None or best[0] <= 0:
            break
        phrase = best[1]
        phrases.append((key, phrase))
        labels = tuple(_replace_plain(label, phrase, '$' + key) for label in labels)
    return tuple(phrases), labels


def _encode_refs(values):
    pieces, index = [], 0
    while index < len(values):
        end = index + 1
        while end < len(values) and values[end] == values[end - 1] + 1:
            end += 1
        pieces.append(str(values[index]) if end == index + 1 else f'{values[index]}:{values[end - 1]}')
        index = end
    return ','.join(pieces)


def compact_tree_locators(query, rows):
    labels = tuple(dict.fromkeys(label for row in rows for label in row['sections']))
    indexes = {label: index for index, label in enumerate(labels)}
    phrases, encoded = _encode_labels(labels)
    pages = [row['pages'][0] if row['pages'][0] == row['pages'][1] else row['pages'] for row in rows]
    consecutive = bool(pages) and all(type(page) is int and page == pages[0] + i for i, page in enumerate(pages))
    payload = {'q': query, 'd': dict(phrases), 'h': encoded, 'p': pages[0] if consecutive else pages,
               'n': [[row['id'], _encode_refs([indexes[label] for label in row['sections']])] for row in rows]}
    titles = {row['id']: row['title'] for row in rows
              if row['pages'][0] != row['pages'][1] or row['title'] != f"Page {row['pages'][0]}"}
    if titles:
        payload['t'] = titles
    return _json(payload)


def restore_tree_locators(serialized):
    """Deterministic audit decoder, not model output parsing or evidence generation."""
    payload = json.loads(serialized)
    decoded = []
    for label in payload['h']:
        text, index = [], 0
        while index < len(label):
            if label[index] != '$':
                text.append(label[index])
                index += 1
            else:
                key = label[index + 1]
                text.append('$' if key == '$' else payload['d'][key])
                index += 2
        decoded.append(''.join(text))
    rows = []
    for index, (handle, references) in enumerate(payload['n']):
        page = payload['p'] + index if type(payload['p']) is int else payload['p'][index]
        pages = [page, page] if type(page) is int else page
        refs = []
        for piece in references.split(',') if references else ():
            if ':' in piece:
                first, last = map(int, piece.split(':'))
                refs.extend(range(first, last + 1))
            else:
                refs.append(int(piece))
        rows.append({'id': handle, 'title': payload.get('t', {}).get(handle, f'Page {pages[0]}'),
                     'pages': pages, 'sections': [decoded[i] for i in refs]})
    return payload['q'], rows
