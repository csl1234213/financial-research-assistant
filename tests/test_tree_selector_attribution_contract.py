"""Attribution diagnostics only: an unqualified representation is never promoted."""

import json
from types import SimpleNamespace

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from llm.providers.provider_models import ChatResponse
from retrieval.adaptive_contract import RetrievalRequest
from retrieval.ready_tree_decision import ReadyTreeModelDecision
from retrieval.tree_locator_codec import compact_tree_locators, restore_tree_locators
from tests.test_tree_materialization_baseline import retained_tree  # noqa: F401


def inline_experiment(payload):
    """Test-only B layout; the production codec remains unchanged."""
    source = json.loads(payload)
    query, rows = restore_tree_locators(payload)
    encoded = dict(zip(dict.fromkeys(s for row in rows for s in row['sections']), source['h'], strict=True))
    result = {'q': query, 'd': source['d'], 'n': {
        row['id']: [row['pages'][0] if row['pages'][0] == row['pages'][1] else row['pages']]
                   + [encoded[label] for label in row['sections']] for row in rows}}
    if 't' in source:
        result['t'] = source['t']
    return result


def restore_experiment(source):
    labels, references, pages = [], [], []
    for handle, values in source['n'].items():
        indexes = list(range(len(labels), len(labels) + len(values[1:])))
        labels.extend(values[1:])
        references.append([handle, ','.join(map(str, indexes))])
        pages.append(values[0])
    original_shape = {'q': source['q'], 'd': source['d'], 'h': labels, 'p': pages, 'n': references}
    if 't' in source:
        original_shape['t'] = source['t']
    return restore_tree_locators(json.dumps(original_shape, ensure_ascii=False))


def test_real_alternative_retains_all_navigation_without_promoting(retained_tree):  # noqa: F811
    request = RetrievalRequest(ScopedRequest(query='说明贵州茅台的主要业务', tenant_id=1, top_k=5))
    _, payload, handles, _, size = ReadyTreeModelDecision(None, retained_tree).build_prompt(request, retained_tree.nodes)
    before = restore_tree_locators(payload)
    candidate = inline_experiment(payload)
    assert restore_experiment(candidate) == before
    assert list(candidate['n']) == list(handles)
    assert len(candidate['n']) == len(set(handles.values())) == 143
    assert candidate['d'] == json.loads(payload)['d']
    assert size == 15717
    assert len(json.dumps(candidate, ensure_ascii=False, separators=(',', ':')).encode()) == 15317


@pytest.mark.parametrize('labels', [[], ['$A', '$$', '$', '含换行\n及引号"'],
                                   ['相似标题', '相似标题', '相似 标题', '😀']])
def test_test_only_layout_preserves_order_duplicates_and_custom_titles(labels):
    rows = [{'id': 'opaque-A', 'title': 'Notes', 'pages': [5, 7], 'sections': labels},
            {'id': 'opaque-B', 'title': 'Page 15', 'pages': [15, 15], 'sections': list(reversed(labels))}]
    payload = compact_tree_locators('lookup', rows)
    assert restore_experiment(inline_experiment(payload)) == ('lookup', rows)


@pytest.mark.parametrize('selected', [['unknown'], ['n144'], ['n1', 'n1'], [True]])
def test_selector_rejects_invalid_or_duplicate_handles(retained_tree, selected):  # noqa: F811
    response = ChatResponse(json.dumps({'selected_node_ids': selected, 'reason': 'fixture'}),
                            'fixture', 'fixture', 100, 20, 120, {'finish_reason': 'stop'})
    provider = SimpleNamespace(provider_name='fixture', model='fixture', chat=lambda _: response)
    chooser = ReadyTreeModelDecision(provider, retained_tree)
    request = RetrievalRequest(ScopedRequest(query='说明业务', tenant_id=1, top_k=5))
    with pytest.raises(ValueError, match='TREE_MODEL_SELECTION_INVALID'):
        chooser(request, retained_tree.nodes)
