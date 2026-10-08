# P2.1 benchmark checkpoint — 2026-09-30

状态：PARTIAL；禁止据此 production promote。

执行：本地缓存真实 embedding + 现有 HybridRetriever(BM25/vector/RRF) + 隔离内存 cosine store；Tree 使用章节标题 embedding orientation，不是 LLM traversal。真实 Provider 调用为 0。

fixture SHA256：8686042552a7f9c6e3481aa9a8376b49d7e6ec4c2ff1a107dd8439734708d82c。

重要修正：fixture 71 个物理页中只有 16 页含有 source blocks，其余为空白占位。树的 100% page inventory coverage 不代表完整 143 页年报的正文覆盖。完整 risk/channel/industry/causal benchmark 需要另补真实、质量通过的正文语料。

## 已审核 source rows

- block 9356d5a65ff21a66d374272c0a4226b6，fixture page 57，合并资产负债表：资产总计，2025-12-31，303,834,844,021.44 CNY。
- block c3bb6340c0ee056629db33ca8b26008c，fixture page 56，合并资产负债表：货币资金，2025-12-31，51,690,610,946.50 CNY。

以上审核是原文行语义/period/scope 审核，不是最终 LLM answer accuracy。母公司和 2024 comparative rows 不作为上述 FY2025 合并事实命中。

## 运行结果

总资产题：Hybrid recall=0，Tree recall=0，TIE（双方失败）。

货币资金 source-row lookup：Hybrid recall=1，Tree recall=0，HYBRID evidence win。

其余八类问题未输出胜负：缺少 reviewed gold、语义歧义或缺少多年度/多公司 corpus。关键词候选不能冒充完整风险证据。

总资产是独立 A/B route 实验，未调用 P1.7 FinancialFact primary；它的失败不等于生产 structured route regression，但证明当前 Hybrid/Tree 原型不能替代 Fact。

## 待完成

- 精确短语题需要 occurrence gold；不能把无 period/scope 的“哪里提到”问题只绑定单一 FY2025 合并行。本轮货币资金结果仅是该 source-row lookup。
- 加入 P1.7 Fact 的真实 repository integration 和独立 Fact win 规则。
- 补齐正文 corpus、逐题审核语义 gold 与 span equivalence。
- Tree hierarchy/traversal 仍需完善；当前深度 1、MEDIUM 质量不代表成熟 semantic hierarchy。
- 尚未 full offline suite、正式提交或部署；P2.1 未 PASS。

## 后续验证更新

真实 FinancialFact adapter 已验证 total_assets、cash_and_bank_balances、net_income、attributable_net_income、operating_cash_flow 五项，使用已有 P1.3 rows → SQLite repository → P1.7 lookup；未触碰生产 DB。

Tree JSON artifact 支持跨 repository 重启缓存、tenant/hash/policy 分离和缓存污染检测。新增 targeted contract/tree/benchmark tests 34 passed。

完整巨潮原报告已下载到 D 盘隔离目录，SHA256 474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288，143/143 页有原生文本。当前兼容性审计输出 QUARANTINED（4170 canonical blocks），包含 page 25/49 等 merged-cell ambiguity。不能把它作为 READY 文档整份送入 Tree；下步需证明可按通过质量检查的非财务正文 excerpt 构建受限 benchmark corpus，或记录 upstream compatibility defect。不得直接改状态绕过 quality gate。

全量离线测试正在执行，当前进程 handle 10531；未获得终态前，不宣称 full suite PASS。

## 正文摘录 A/B 实测

正文 excerpt 原页码 8/9/21/22/23，79 source blocks，经同一兼容性检查 READY、failures=0；全报告仍为 QUARANTINED。摘录不是完整年报替代品。

真实本地 embedding、现有 HybridRetriever 与 section-title orientation Tree：53 nodes、depth=1、MEDIUM。10 题 gold 使用已审核原文锚点绑定 source blocks，未读取 gold 来选择 Tree 节点。

| ID | Class | Hybrid recall | Tree recall | Evidence winner |
|---|---|---:|---:|---|
| 001 | EXACT_PHRASE | 1 | 0 | HYBRID |
| 002 | EXACT_PHRASE | 0 | 1 | TREE |
| 003 | SECTION_LOOKUP | 1 | 1 | TIE |
| 004 | SECTION_LOOKUP | 1 | 0 | HYBRID |
| 005 | LOCAL_SEMANTIC | 1 | 0 | HYBRID |
| 006 | LOCAL_SEMANTIC | 1 | 0 | HYBRID |
| 007 | EXHAUSTIVE | 0 | 0 | TIE, both fail |
| 008 | EXHAUSTIVE | 0 | 0 | TIE, both fail |
| 009 | CAUSAL | 0 | 0 | TIE, both fail |
| 010 | CAUSAL | 1 | 0 | HYBRID |

Hybrid 5 evidence wins、Tree 1、tie 4，其中 3 为双方未召回。所有返回证据 citation mismatch=0，但存在 coverage miss。不是 answer accuracy，不支持生产 promote；cost 不完整时不做成本优劣结论。

未完成：完整 trace/report export、iterative tree traversal 边界验证、跨语言 corpus 分类、full suite 终态、最终 requirement audit 和独立提交。P2.1 未 PASS。

## 报告导出与 observability 更新

CLI 已支持 `--fixture --narrative --output`，真实正文报告输出到 <private-acceptance-artifacts>/p2_1-corpus/narrative-ab-report.json，并复现 Hybrid=5、Tree=1、Tie=4。estimated provider cost 与 embedding compute cost 分开记录。

统一 RetrievalTrace schema 和全部 14 类 failure taxonomy 已实现；route hypotheses 仅是 metadata，不用于 production routing。未知候选数和未知成本保留 null，不伪造为零。

最新 targeted tests：36 passed。全仓 Ruff PASS。全量离线 suite（10531）尚未结束，不能判 PASS。

提交依赖风险：P2.1 导入的 document_compatibility 包目前仍为 P1.6.2 untracked 文件。只提交 P2.1 会产生缺失 upstream module 的 checkout；不得混入已有 P1.6.2 工作树以掩盖这个依赖。最终提交前需要先解决 upstream commit 边界，或显式将交付状态标为 blocked commit，而非宣称已提交。

## 财务维度拒绝与 provenance 验证

Fact adapter 增加 metric、fiscal_year、scope、period_type 的 request/evidence 一致性检查；错误维度直接拒绝。tenant metadata 拒绝 float/bool/string 类型。Tree evidence 增加 source_locator、schema/builder/policy/document version，node provenance 绑定 source ids。

最新 P2.1 targeted suite：46 passed（包括真实 SQLite Fact integration、全部 cache/shadow/benchmark contract tests）。Ruff 全仓通过。全量 suite 10531 仍在运行，不能给出终态数字。
