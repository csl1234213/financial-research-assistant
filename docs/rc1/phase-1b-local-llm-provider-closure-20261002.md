# RC1 Phase 1B — Local Provider runtime contract closure

RC1_PHASE_1B_STATUS = PASS
LOCAL_LLM_PROVIDER_CONTRACT = PASS
Actual clean Commit C and Commit D history replays both passed.

## AUDIT_BASELINE / ANSWER_BASELINE_AUDIT

Authoritative source: <repository>.
Phase 1A d0a5d93 and c971997 remain unchanged ancestors.
No broad staging, reset, clean, stash, push, Docker deployment or real Provider call.

ANSWER_BASELINE_DEPENDENCY_GRAPH and COMMIT_C_MANIFEST:
answer-baseline-c-manifest-20261002.json contains each file's symbols, role,
required/used-by dependencies, origin estimate and commit target.
PRE_PHASE_1B is a reconstruction estimate, not a fabricated historical commit.
UNKNOWN ownership entries = 0.

C contains 23 source modules, 19 baseline test files, three necessary tracked
compatibility hunks and the manifest. Tracked hunks are ChatRequest.thinking_enabled,
Evidence.section, existing DeepSeek thinking/attempt bookkeeping only.
The shadow synthesis-input bridge satisfies the existing planner dependency;
Tree Retrieval Engine is excluded. Hidden dependencies discovered in initial
TEMP_C were explicitly added before validation, not read from the dirty worktree.
C deliberately retains historical Qwen checks, usage gates, per-call timeout
ceiling and timeout retry defects which belong to D.

ANSWER_BASELINE_COMMIT_SEPARABLE = true
COMMIT_C_SELF_CONTAINED = true
BASELINE_UNTRACKED_HIDDEN_DEPENDENCIES = 0
STAGED_C_EQUALS_VALIDATED_C = true
COMMIT_C_SHA = b07ceccd6310d1c3222df73f4577ed3793b44195
COMMIT_C_CREATED = true

Validated C tree: f380892bfbfe3cb3db765f4b6336faecbcb6566c.
Actual detached C worktree: <private-acceptance-artifacts>/phase1b-actual-c.
COMMIT_C_VALIDATION: 364 passed, 0 failed, 0 skipped; imports and Ruff passed.
Receipt: <private-acceptance-artifacts>/b2-actual-c-tests.xml.

## PROVIDER_BATCH_1_OWNERSHIP

Generation/Usage separation, optional token counts, OpenAI deadline, timeout
no-retry and truthful cancellation flags are all D. They were excluded from C
and verified still uncommitted after C was created.
ALL_BATCH_1_CHANGES_TARGET = COMMIT_D
PROVIDER_BATCH_1_CHANGES_STILL_UNCOMMITTED_AFTER_C = true

## PROVIDER_ARCHITECTURE / GENERATION_RESULT_CONTRACT / USAGE_CONTRACT

Existing BaseProvider, Registry, Factory, ProviderConfig, ChatRequest and
ChatResponse are reused; no parallel result framework.
ChatResponse adds generation_status, usage_status, finish_reason, optional
prompt/completion/total tokens, optional provider_request_id and failure_class.
ProviderError and specialized errors normalize failure/status classification.

Generation: SUCCESS, TIMEOUT, CANCELLED, PROVIDER_ERROR, INVALID_RESPONSE,
STRUCTURED_OUTPUT_ERROR. Usage: KNOWN, PARTIAL, UNKNOWN, UNSUPPORTED, UNAVAILABLE.
No audited adapter claims remote inference has been cancelled.
Missing counts remain None, not invented zero usage. Provider-reported zero
remains reported telemetry. Generation success is not financial verification.

GENERATION_AND_USAGE_STATUS_SEPARATED = true
USAGE_OPTIONAL = true
SUCCESS_WITHOUT_USAGE_END_TO_END = PASS

## ANSWER_PORT_DI / ANSWER_PORT_DECOUPLING

Draft, Narrative and Semantic Review accept injected BaseProvider or
ProviderConfig through the official Factory/Registry. No concrete Adapter
constructor/import or qwen3.8 tag check remains in these ports.
Legacy LocalQwen class names remain for source/API compatibility; names do not
control model selection. Legacy DeepSeek Answer ports use the generic contract.
Ports require the real system-prompt capability rather than a model label.
supports_json_mode=false truthfully describes missing native vendor JSON mode;
the Answer parser can still validate generated JSON text independently.

Two registry fixtures change provider/model/endpoint configuration only.
All three ports retain identical prompt payloads and business outcomes.
Explicit injection tests also prohibit replacing the injected provider.

PROVIDER_CONFIG_DRIVEN = true
PROVIDER_MODEL_CONFIGURABLE = true
PROVIDER_ENDPOINT_CONFIGURABLE = true
PROVIDER_SWITCH_WITH_CONFIG_ONLY = PASS
MODEL_SWITCH_WITH_CONFIG_ONLY = PASS
ENDPOINT_SWITCH_WITH_CONFIG_ONLY = PASS
QWEN_SPECIFIC_ANSWER_PORT_PATHS = 0
ANSWER_PORTS_USE_PROVIDER_CONTRACT = true

## USAGE_RELEASE_DECOUPLING

Original structured validity, verification/review, evidence binding and complete
buffered output determine release. Unknown/partial/unsupported usage no longer
rejects a valid verified fact draft or narrative. Batched review aggregate counts
remain None if any batch lacks full telemetry. Known counts support existing
bounded cost accounting; no unknown aggregate is invented.
Invalid schema and failed review remain rejected. Missing cost telemetry does
not authorize an unbounded revision loop or unverified answer.

## TIMEOUT_POLICY / NARRATIVE_TIMEOUT_UNIFICATION / TOTAL_DEADLINE

effective_timeout = min(configured generation timeout, remaining request deadline).
Shorter deployment total deadline also wins. Legacy Ollama config wiring no longer
silently expands configured timeout. Provider default stays 60 seconds; no Qwen 240.
Narrative retains a configurable request-wide deadline (default 120), but removes
its separate default/hardcoded 120-second per-call ceiling. An optional explicitly
configured server allowance is still supported.
OpenAI/DeepSeek/Ollama share deadline arithmetic. Minimal synchronous containment
bounds caller waiting even if transport ignores socket timeout. Late results are
discarded; no guaranteed remote cancellation is implied.

GENERATION_TIMEOUT_CONFIGURABLE = true
TOTAL_DEADLINE_ENFORCED = true
NARRATIVE_HARDCODED_PER_CALL_TIMEOUT = 0
NARRATIVE_HARDCODED_TIMEOUT = 0 (per-call policy; configurable total deadline retained)
OPENAI_REQUEST_DEADLINE_RESPECTED = true
OPENAI_TIMEOUT_NO_RETRY = PASS
DEEPSEEK_TIMEOUT_NO_RETRY = PASS
GENERATION_TIMEOUT_NO_AUTO_RETRY = PASS
ALL_RETRIES_BOUNDED = true

| Adapter | SDK retry count | Application retries | Maximum attempts |
| --- | --- | --- | --- |
| Ollama | N/A (HTTPX) | 0 | 1 |
| OpenAI | 0 | up to 2 transient retries | 3; timeout 1 |
| DeepSeek | 0 | up to 2 including existing recovery | 3; explicit timeout 1 |

Auth/invalid requests do not retry. Connection, 429 and selected 5xx retries are
bounded where supported. Answer structured parsing does not cause Provider retry.
DeepSeek's preexisting empty/truncated thinking-response recovery shares the
3-attempt budget; it is preserved rather than rewriting Answer quality policy.

## CANCELLATION_CAPABILITY / STREAMING_CAPABILITY

Audited adapters declare supports_cancellation=false. Timed-out daemon transport
may continue until its socket timeout/completion; result is discarded.
Ollama HTTP context closes when transport finishes/fails; hung transport can
defer cleanup past caller timeout. Tests distinguish cleanup from cancellation.
No CANCELLED_SUCCESSFULLY is emitted.
CANCELLATION_CAPABILITY_TRUTHFUL = true
NATIVE_PROVIDER_STREAMING = NOT_IMPLEMENTED
STREAMING_CAPABILITY_TRUTHFUL = true
Frontend SSE = POST_VALIDATION_RESPONSE_STREAMING.
Existing verified chunk release tests pass; no native token streaming was added.

## STRUCTURED_OUTPUT_BOUNDARY / STRUCTURED_FAILURE_CLASSIFICATION

Parser remains in Answer. Invalid JSON/schema is STRUCTURED_OUTPUT_ERROR with or
without usage; accounted failures preserve known usage.
Narrative still rejects fenced JSON. Semantic Review preserves its preexisting
single complete fenced-JSON allowance from C; no new leniency.
AST comparisons against C confirm unchanged build_narrative_prompt,
parse_narrative_json, build_semantic_review_prompt, parse_local_review, and Draft
instruction/payload expressions. Planner, renderer, contracts, narrative assembly,
and verification source diffs are empty.
STRUCTURED_OUTPUT_FAILURE_CLASSIFICATION = PASS
PROMPT_AND_SCHEMA_POLICY_CHANGED = false

## INGESTION_ISOLATION

An injected Answer Provider is made unavailable. Independently composed formal
ingestion app starts and receives the real tracked statements PDF. Five real
operators reach READY with isolated SQLite/local vector test data.
Tree build and offline embedding do not depend on the failed Answer Provider.
This is offline functional isolation, not live customer or production acceptance.
No Phase 1A ingestion implementation or fixtures were changed for this proof.
ANSWER_PROVIDER_FAILURE_DOES_NOT_BREAK_INGESTION = true

## PHASE_1B_TESTS / PROVIDER_REGRESSIONS

TEMP_CD = archive(C) + explicit D manifest only. No dirty worktree conftest,
mixed API, frontend, Tree or unrelated untracked dependencies are copied.
Final independent run: 455 passed, 0 failed, 0 skipped; Ruff and diff check pass.

| Group | Passed | Failed | Skipped |
| --- | --- | --- | --- |
| PROVIDER_CONTRACT_TESTS | 31 | 0 | 0 |
| ANSWER_PORT_TESTS including DI/release/error | 23 | 0 | 0 |
| TIMEOUT_TESTS | 17 | 0 | 0 |
| RETRY_TESTS runtime subset | 10 | 0 | 0 |
| USAGE_TESTS / USAGE_RELEASE | 19 | 0 | 0 |
| STRUCTURED_OUTPUT_TESTS new targeted subset | 6 | 0 | 0 |
| CANCELLATION_TESTS | 3 | 0 | 0 |
| EXISTING_PROVIDER_REGRESSION | 50 | 0 | 0 |
| OFFLINE_ANSWER_REGRESSION | 340 | 0 | 0 |
| INGESTION_ISOLATION_TESTS | 1 | 0 | 0 |
| QWEN_REFERENCE_FORENSICS | 10 | 0 | 0 |

Subset rows overlap; do not sum them. Unique total = 455.
Old expectations for mandatory usage or enlarged local timeout were explicitly
updated for the requested contract, not skipped. Unrelated historical untracked
Answer tests are not silently incorporated into D.
PROVIDER_REGRESSION = 0
OFFLINE_ANSWER_REGRESSION = 0

TEMP_CD receipt: <private-acceptance-artifacts>/b2-cd-final-455.xml.
Actual D history receipt: <private-acceptance-artifacts>/b2-actual-d-tests.xml.
Actual D history replay: 455 passed, 0 failed, 0 skipped; clean imports and Ruff passed.
Existing Starlette/httpx deprecation warning is recorded, not counted as failure.

## COMMIT_D_MANIFEST / COMMIT_D_VALIDATION / FILES_CHANGED

Explicit files and purposes: phase-1b-commit-d-manifest-20261002.json.
COMMIT_D_SELF_CONTAINED = true
D_UNTRACKED_DEPENDENCIES = 0
STAGED_D_EQUALS_VALIDATED_D = true
COMMIT_D_CREATED = true
RUFF_STATUS = PASS
DIFF_CHECK = PASS
COMMIT_D_SHA = resolve via git log -1 --format=%H -- llm/providers/timeout_policy.py.
The immutable SHA is also recorded in the final handoff; no self-referential hash.
Only C and D are created. Actual history checks use clean detached worktrees.

## KNOWN_LIMITATIONS / CUSTOMER_LOCAL_MODEL_QUALIFICATION

QWEN_REFERENCE_ROOT_CAUSE = TIMEOUT
QWEN_REFERENCE_CASE = NON_BLOCKING_REFERENCE
QWEN_LIVE_ACCEPTANCE = NOT_REQUIRED
VLLM_DEDICATED_COMPATIBILITY = NOT_VALIDATED
Only OpenAI-compatible custom endpoint support is claimed, not universal vLLM
parameter compatibility. Existing Claude/Gemini/Doubao regressions pass; newly
complete timeout/cancellation contracts for every vendor are not claimed.
Unknown usage cannot provide full cost telemetry.
Customer qualification separately checks provider, model, endpoint, hardware,
VRAM, context size, structured output, latency, concurrency, tokens/sec, resource
consumption, answer quality and actual deployed timeout policy.
Fixture success and this core contract acceptance cannot substitute for that.

## NEXT_PHASE

Stop after Phase 1B. Await explicit authorization for Phase 1C.
