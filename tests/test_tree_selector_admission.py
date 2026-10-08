"""Offline admission and reversible navigation tests; not live selection quality."""

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.tools.retrieval_contract import RetrievalRequest as ScopedRequest
from llm.providers.provider_models import ChatResponse
from retrieval.adaptive_contract import RetrievalRequest
from retrieval.ready_tree_decision import ReadyTreeModelDecision
from retrieval.tree_locator_codec import compact_tree_locators, restore_tree_locators
from tests.test_tree_materialization_baseline import retained_tree  # noqa: F401

FROZEN = Path(__file__).parent / 'fixtures/rc1/tree_selector_pre_b1.py.txt'
FROZEN_SHA = '16e56088e178eaa830fcb6cf1c6da518ed4151f60dfed99c5f3562f625763da3'
QUERY = '说明贵州茅台的主要业务'


def request(query=QUERY):
    return RetrievalRequest(ScopedRequest(query=query, tenant_id=1, top_k=5))


def forbidden_provider():
    def chat(_):
        pytest.fail('Preflight must never invoke a Provider')
    return SimpleNamespace(chat=chat)


def frozen_selector():
    # Git's Windows checkout can use CRLF; fingerprint the archived LF bytes.
    content = FROZEN.read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(content).hexdigest() == FROZEN_SHA
    namespace = {'__name__': 'frozen_pre_b1_selector'}
    exec(compile(content, str(FROZEN), 'exec'), namespace)
    return namespace


def test_real_frozen_admission_three_repeats(retained_tree, record_property):  # noqa: F811
    baseline = frozen_selector()
    captured = []
    original_pack = baseline['pack_tree_locators']

    def capture(query, rows):
        captured.append((query, rows))
        return original_pack(query, rows)

    baseline['pack_tree_locators'] = capture
    old = baseline['ReadyTreeModelDecision'](forbidden_provider(), retained_tree)
    with pytest.raises(ValueError, match='TREE_MODEL_INPUT_BUDGET'):
        old.build_prompt(request(), retained_tree.nodes)
    assert old.receipts[-1]['request_bytes'] == 22919
    query, rows = captured[0]
    wires = []
    for _ in range(3):
        chooser = ReadyTreeModelDecision(forbidden_provider(), retained_tree)
        instruction, payload, handles, originals, size = chooser.build_prompt(request(), retained_tree.nodes)
        assert size == len((instruction + payload).encode('utf-8')) <= 16000
        assert restore_tree_locators(payload) == (query, rows)
        assert len(handles) == len(rows) == 143
        assert list(handles) == [row['id'] for row in rows]
        assert tuple(handles.values()) == tuple(n.node_id for n in retained_tree.nodes if n.parent_id)
        assert len(set(handles.values())) == 143
        assert originals == {n.node_id: n for n in retained_tree.nodes}
        assert chooser.calls == 0 and chooser.receipts == []
        wires.append((instruction, payload, handles, size))
    assert wires[0] == wires[1] == wires[2]
    business = next(row for row in rows if row['id'] == 'n8')
    assert '一、报告期内公司从事的业务情况' in business['sections']
    for word in ('风险', '审计'):
        assert any(word in label for row in rows for label in row['sections'])
    wire = json.loads(wires[0][1])
    record_property('BEFORE_BYTES', 22919)
    record_property('AFTER_BYTES', wires[0][-1])
    record_property('PAYLOAD_BYTES', len(wires[0][1].encode('utf-8')))
    record_property('INSTRUCTION_BYTES', len(wires[0][0].encode('utf-8')))
    record_property('LABEL_COUNT', len(wire['h']))
    record_property('PHRASE_COUNT', len(wire['d']))
    record_property('REAL_PROVIDER_ATTEMPTS', 0)
    record_property('ALL_NAVIGATION_FIELDS_ROUNDTRIP', True)


@pytest.mark.parametrize('sections', [
    [], ['现金流量表'], ['$A', '$$', '$', 'Revenue 😀'],
    ['abcdef中文重复段abcdef', 'abcdef中文重复段abc', 'abcdef中文重复段abcd'],
    ['Risk management', 'Risk management', '风险管理'],
])
def test_lossless_labels_order_and_literal_markers(sections):
    rows = [{'id': 'opaque', 'title': 'Custom title', 'pages': [8, 10], 'sections': sections},
            {'id': 'other', 'title': 'Page 35', 'pages': [35, 35], 'sections': list(reversed(sections))}]
    serialized = compact_tree_locators('Unicode 问题 😀 $A', rows)
    assert restore_tree_locators(serialized) == ('Unicode 问题 😀 $A', rows)
    assert serialized == compact_tree_locators('Unicode 问题 😀 $A', rows)


def test_default_titles_consecutive_pages_and_reference_ranges():
    rows = [{'id': f'n{i}', 'title': f'Page {i + 8}', 'pages': [i + 8, i + 8],
             'sections': ['资产', '负债', '权益']} for i in range(6)]
    payload = compact_tree_locators('资产', rows)
    wire = json.loads(payload)
    assert wire['p'] == 8 and 't' not in wire
    assert wire['n'][0][1] == '0:2'
    assert restore_tree_locators(payload) == ('资产', rows)


def test_utf8_query_overflow_rejected_without_pruning(retained_tree):  # noqa: F811
    chooser = ReadyTreeModelDecision(forbidden_provider(), retained_tree)
    with pytest.raises(ValueError, match='TREE_MODEL_INPUT_BUDGET'):
        chooser.build_prompt(request('中' * 16000), retained_tree.nodes)
    assert chooser.receipts[-1]['provider_attempts'] == 0
    assert chooser.calls == 0
    assert chooser.receipts[-1]['request_bytes'] > 48000


def test_candidate_limit_unchanged(retained_tree):  # noqa: F811
    chooser = ReadyTreeModelDecision(forbidden_provider(), retained_tree)
    nodes = (next(n for n in retained_tree.nodes if n.parent_id),) * 257
    with pytest.raises(ValueError, match='TREE_MODEL_CANDIDATE_BUDGET'):
        chooser.build_prompt(request(), nodes)
    assert chooser.calls == 0


def test_exact_byte_boundary_and_policy_text(retained_tree):  # noqa: F811
    chooser = ReadyTreeModelDecision(forbidden_provider(), retained_tree)
    instruction, _, _, _, size = chooser.build_prompt(request(), retained_tree.nodes)
    old_ast = ast.parse(FROZEN.read_text(encoding='utf-8'))
    old_instruction = next(n.value for n in ast.walk(old_ast) if isinstance(n, ast.Constant)
                           and isinstance(n.value, str) and n.value.startswith('Nodes and section labels'))
    policy = old_instruction.split('Each nodes array follows columns;')[0]
    assert instruction.startswith(policy)
    boundary = request(QUERY + 'x' * (16000 - size))
    assert chooser.build_prompt(boundary, retained_tree.nodes)[-1] == 16000
    with pytest.raises(ValueError, match='TREE_MODEL_INPUT_BUDGET'):
        chooser.build_prompt(request(boundary.scoped.query + 'x'), retained_tree.nodes)


def test_same_titles_distinct_navigation_preserved():
    rows = [{'id': 'A', 'title': 'Notes', 'pages': [20, 20], 'sections': ['Risk', 'Credit risk']},
            {'id': 'B', 'title': 'Notes', 'pages': [21, 22], 'sections': ['Risk', 'Liquidity risk']}]
    assert restore_tree_locators(compact_tree_locators('Risk', rows)) == ('Risk', rows)


def test_projection_and_owner_checks_unchanged(retained_tree):  # noqa: F811
    chooser = ReadyTreeModelDecision(forbidden_provider(), retained_tree)
    with pytest.raises(PermissionError, match='OWNER_MISMATCH'):
        chooser.build_prompt(RetrievalRequest(ScopedRequest(query=QUERY, tenant_id=2)), retained_tree.nodes)
    node = next(n for n in retained_tree.nodes if n.parent_id)
    with pytest.raises(ValueError, match='PROJECTION_CHANGED'):
        chooser.build_prompt(request(), (replace(node, title='changed'),))


@pytest.mark.parametrize('symbol', ['source_heading_labels', '__init__', '__call__'])
def test_selection_policy_and_transport_ast_frozen(symbol):
    before = ast.parse(FROZEN.read_text(encoding='utf-8'))
    import retrieval.ready_tree_decision as current
    after = ast.parse(Path(current.__file__).read_text(encoding='utf-8'))
    def extract(tree):
        return ast.dump(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == symbol))
    assert extract(before) == extract(after)


@pytest.mark.parametrize('selected', [['n8'], ['n1', 'n8'], [], ['n1', 'n8', 'n9']])
def test_fake_provider_output_mapping_no_live_quality_claim(retained_tree, selected):  # noqa: F811
    calls = []
    def chat(value):
        calls.append(value)
        return ChatResponse(json.dumps({'selected_node_ids': selected, 'reason': 'fixture'}),
                            'fixture', 'arbitrary-model', 100, 20, 120, {'finish_reason': 'stop'})
    provider = SimpleNamespace(provider_name='fixture', model='arbitrary-model', chat=chat)
    chooser = ReadyTreeModelDecision(provider, retained_tree)
    if len(selected) > 2:
        with pytest.raises(ValueError, match='TREE_MODEL_SELECTION_INVALID'):
            chooser(request(), retained_tree.nodes)
    else:
        result = chooser(request(), retained_tree.nodes)
        assert result.selected_node_ids == tuple(f'{retained_tree.document_id}:page:{int(i[1:])}' for i in selected)
    assert len(calls) == 1 and calls[0].temperature == 0
    assert calls[0].max_tokens == 512 and calls[0].thinking_enabled is False
