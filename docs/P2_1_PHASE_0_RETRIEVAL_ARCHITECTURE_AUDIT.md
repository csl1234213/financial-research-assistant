# P2.1 Phase 0：检索架构审计

日期：2026-09-30。状态：PHASE_0_COMPLETE / IMPLEMENTATION_NOT_STARTED。

本记录为源码审计，不代表本阶段 regression、benchmark 或生产验收已通过。Provider 调用数为 0；未改变当前 Docker 配置或生产 route。

## 当前真实调用链

`core/core_engine.py` 创建 `AgentRuntime`，注入 IntentAnalyzer、QueryPlanner、HybridRetriever、context builder 和 `lookup_persisted_financial_fact`。

`agent/agent_runtime.py` 在 intent 为 FINANCIAL_FACT_QUERY 时调用 structured lookup。其 terminal result 可直接返回 structured answer/evidence；`core_engine.py` 对 strategy=structured_financial_fact 分支直接构造响应。

普通查询经 QueryPlanner 生成执行计划，由 `core_engine._retrieve_handler` 调用 TenantRetrievalToolExecutor → ToolEngine → RuntimeRetrievalAdapter → HybridRetriever.retrieve_evidence → retrieve。后续使用 citation gate、evidence-first context、financial grounding、final answer policy，最后投影答案实际使用的引用。

## 14 项检查

1. IntentAnalyzer 返回 dict，包含 intent、companies、document_ids；结构化请求增加 canonical metric、fiscal year、period semantics 等信息。其结果尚不是完整 P2.1 request。
2. P1.7 插入点是 AgentRuntime 的 structured_fact_lookup，早于普通 hybrid 执行；必须保持。
3. Hybrid.retrieve 输入 RetrievalContext 与 EmbeddingStore，输出 list[SearchResult]；retrieve_evidence 输出 list[agent.reasoning_models.Evidence]。
4. Vector candidates 来自 embedding query 与 tenant-scoped similarity_search；lexical corpus 独立加载并由 BM25Retriever.search 排序，已有 targeted lexical 补充。
5. HybridRetriever 中现有 weighted reciprocal-rank fusion 使用 rrf_k，输出 rrf_score、vector_rank、bm25_rank 等 metadata；本阶段不修改其评分或 Top-K。
6. build_context_from_evidence 使用 content/source/company/confidence/metadata 协议，并根据 evidence 顺序构造引用序号。
7. agent Evidence 是宽松 dataclass；tool RetrievalEvidence 是冻结、验证后的 contract；FinancialFact 在 core/fact_ledger.py，持久化 repository 在 core/persistent_financial_facts.py。不能再创建平行的事实身份。
8. Citation metadata 包含 page、section、source_locator、document_id、版本及结构化 metric/period/scope，最终由答案引用投影进一步筛选。
9. 主生成路径消费 agent Evidence，但 legacy build_context 仍直接依赖 old RetrievalResult，且 context_builder 导入 hybrid 的 extract_local_context。因此下游完全解耦目前不成立。
10. 已存在 agent.tools.retrieval_contract.RetrievalAdapter Protocol，以及 core.retrieval_tool_adapter.EvidenceRetriever Protocol；需要适配而非替换安全边界。
11. QueryPlanner 已存在 TaskAnalyzer、ComplexityAnalyzer、ExecutionPlan，comparison 按公司建计划；不重写。
12. 已有 intent、task type、complexity、query scope、period filters；完整 query_precision/query_breadth 分类仍需统一一次构造。
13. 当前 document_ids、company、tenant_id/include_public 通过 RetrievalContext 过滤；多公司通过 planner 及 coverage-aware retrieval 处理。Tree 必须再次验证 document/tenant 边界。
14. 现有 observability 分布在 execution、intent trace、retrieval rank metadata 与 answer grounding diagnostics。候选数、tree tokens/cost/coverage 尚未统一为单一 RETRIEVAL_TRACE。

## 关键缺口与前提修正

- P1.6.2 已有 canonical_blocks、SourceSpan、TracedChunk.source_block_ids 和质量报告，但尚未接入生产上传 worker。Tree 原型只接已验证离线 inventory；不把生产 PDF 的存在等同于通过 quality gate。
- Hybrid.retrieve_evidence 当前白名单没有完整 bbox/source_block_ids/provenance/tenant_id。需要新增适配层保留原 SearchResult metadata，并显式验证 scope；不能声称当前 Evidence 全量无损。
- Structured `_source_evidence` 提供精确 metric/value/period/scope/source locator，但没有独立的统一 provenance 类型。adapter 必须保留 fact identity 以及源字段。
- Tree quality 的 overlapping_ranges 必须区分合法祖先/子节点嵌套和不合法 sibling overlap，否则真实树会被误判。
- 当前真实 Moutai fixture 是裁剪后的已验证页面集；benchmark 必须记录物理 fixture page 与原报告页码的映射，不能将样本页面覆盖率报告成完整 143 页年报覆盖率。
- Retrieval-only benchmark 的 ANSWER_ACCURACY 应为 NOT_EVALUATED，不能用召回率代替语义答案准确率。未人工审核的 evidence gold 也不能宣称金标准。

## PageIndex 集成评估

来源：官方 https://github.com/VectifyAI/PageIndex 、LICENSE 与 https://docs.pageindex.ai/getting-started 。官方提供 local mode，local 调用仍需要自己的 LLM key；扫描文档官方建议 Cloud OCR。仓库 LICENSE 为 MIT。

决定：ARCHITECTURE_REFERENCE。采用项目内 adapter + tree projection；不安装包，不增加 requirements，不访问 Cloud。其 node/page 结构可参考，但不能替代本项目 canonical source blocks、细粒度 bbox、tenant scope、quality gate 或 FinancialFact。依赖大小、Python 版本约束、package conflict 尚未固定版本核查，均标记 UNVERIFIED；由于不引入 dependency，不构成本阶段安装阻断。未来如设 benchmark competitor，先在隔离环境固定版本评估。

## MINIMAL_P2_1_IMPLEMENTATION_PLAN

1. 新建隔离的 retrieval architecture contract，复用现有 validated tool request 边界及 agent Evidence bridge。增加 immutable semantics、status、coverage、cost、trace。禁止每个 adapter 再重新解析整条问题。
2. FinancialFact adapter 接收既有 structured result；Hybrid adapter 接收既有 retriever 与 server-owned store。统一 evidence 保留 metadata 与原身份。所有转换测试覆盖 financial fields/provenance 不丢失。
3. Tree builder 接收通过最低 quality gate 的 ExtractionInventory。利用 section/heading 构树；不足时 FALLBACK_PAGE_TREE=LOW。node 只引用 canonical block ids，summary 不输出为最终 evidence。
4. 本地 JSON/test repository 使用 tenant/document/version/hash/policy 联合 cache key，保存 schema/builder/policy/summary-model version。校验完整页范围、节点唯一性、parent/child 一致性及 cycle。
5. TreeReasoningRetriever 采用可注入 deterministic decision provider。校验节点、页、文档和 tenant，读取实际 blocks，记录 traversal/tokens/cost。真实 Provider 默认关闭。
6. Shadow wrapper 接收 primary result；执行失败隔离，Tree output 仅进入 diagnostics。structured query 默认不调用 tree。生产 composition root 暂不启用。
7. 建立 A/B 框架、C manual/oracle 标签以及十类 query。Moutai 六类 hard cases 增加页/section/span gold；空 gold、未审核 gold 与无答案评测分别标记。winner 依据 correctness、coverage、citation，再结合实际成本/延迟，允许 Hybrid/Fact 胜出。
8. 执行 contract、adapter、tree safety/cache/shadow tests，真实 fixture integration、P1.7 regression、offline suite、Ruff 与 diff review。先输出计数和未通过 gate，才决定阶段状态。

可复用：现有 registry、SQL repository、query intent/planner、HybridRetriever/BM25/RRF、tenant tool contract、canonical inventory、citation projection、offline retrieval dataset/gate。

不必要重构：重写 AgentRuntime/Answer Generator、统一替换全部 Evidence 类型、改 scorer、改 metric identity、建立第二套解析真相、加入生产 tree persistence/migration。

## 当前状态

P2_1_STATUS=PHASE_0_COMPLETE；P2.1 implementation、benchmark 和提交尚未完成。

当前历史脏文件及 P1.6.2 untracked 文件保持原样。后续 P2.1 只纳入独立新增文件及经过逐 hunk 审核的必要修改。
