# CNINFO 茅台 MT-ZH-007–009 根因修复记录

日期：2026-09-27
范围：冻结的贵州茅台 2025 年年度报告测试集 MT-ZH-007、008、009。仅使用隔离 QA 栈和本地 Ollama/Qwen；未调用 DeepSeek 或其他远程 Provider。

## 确认的根因

| 案例 | 根因 | 修复 |
|---|---|---|
| MT-ZH-007 | 必需事实规划把“分地区主营业务收入”归为公司整体 `main_business_revenue`，而表格事实是 `revenue + region + category`。即使区域行已检索到，事实规划仍显示目标缺失。 | 按问题中明确提及的维度和类别扩展事实计划；地区问题只计划被点名的 region 类别，并将这些表格行映射为 revenue。同比事实也沿用相同类别边界。 |
| MT-ZH-007 | Qwen 原始回答为无引用的证据不足拒答。初次 citation grounding 因无引用而得到空 trusted evidence，随后提前拒答，Fact Ledger 的确定性事实补全没有机会执行。 | 若且仅若计划中的每一项要求均有证据，且确定性投影经过同一 citation sanitizer 验证，允许以已验证的投影替代模型拒答。任何要求缺失时仍 fail closed。 |
| MT-ZH-007 | 数字 sanitizer 将问题中的 `main_business_revenue` 与区域表格的 `revenue` 视为不同指标，拒绝了正确区域金额。 | 仅在问题明确要求地区拆分、答案行明确标出地区、所引证据也包含匹配的 `region/category` 行时，允许此处的局部指标等价。错误地区或产品行不能支撑该 claim。 |
| MT-ZH-008 | 中文任务关键词漏掉“收入、直销、批发代理、同比”等销售渠道表达；未识别的任务落入 CHAT/Direct LLM。 | 将财报/审计领域术语纳入文档问答路由；销售渠道问题按 `sales_mode/category` 分别计划收入与同比。 |
| MT-ZH-008 | API 传入的公司上下文未提供给旧 Intent Analyzer；没有在原始问句中写公司名的财务问题可能被判为 DIRECT_CHAT。 | 运行时先解析公司上下文，再传给 Intent Analyzer。一般概念定义仍保持 DIRECT_CHAT，不会因设置了公司而强制检索。 |
| MT-ZH-009 | “会计师事务所、审计意见、财务报表”等中文术语不在财报任务分类规则中，问题被送入直接聊天，造成无证据的事务所幻觉。 | 把审计披露词加入财报文档任务分类；此次真实链路检索到审计报告原文后再生成答案。 |

本轮没有调 BM25/vector 权重、RRF、Top-K、period reranker，也没有改冻结 Benchmark 的题目或标准。

## 验证

### 隔离 QA 的真实 HTTP 链路

仅重建并重启 `moutai-qa-v21-20260926` 的 API 和 worker，复用其隔离数据库、Redis、uploads、Chroma volumes；生产 Compose 栈未重建、未重启。QA 环境确认 `LLM_PROVIDER=ollama`、模型 `srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`、`ALLOW_REAL_PROVIDER=false`。

- MT-ZH-007：最终修复后单题 HTTP 200，2 条 citation 均来自年报第 10 页。Fact Plan 中 `region/国内` 和 `region/国外` 均 `available=true`、`answer_present=true`。最终答案为国内 1639.24 亿元人民币、国外 48.5 亿元人民币。
- MT-ZH-008：HTTP 200，2 条 citation 来自第 10 页。直销 845.43 亿元、同比 +12.96%；批发代理 842.32 亿元、同比 -12.05%，渠道和方向对应正确。
- MT-ZH-009：HTTP 200，citation 来自第 53 页审计报告。答案正确指向天健，并引用其审计意见原文；本次检索没有召回冻结标准所列的第 2 页，但第 53 页包含事务所签章编号和审计意见正文。

Qwen 的一次早期 MT-ZH-007 回答曾拒答；这是定位到确定性拒答路径后修复前的结果。最终仅在代码修复后又运行 MT-ZH-007 一次确认，未循环重试，也未重跑整套 10Q。

原始结果：

- 三题首轮：[moutai_qa_007_009_root_fix_20260927.json](../evaluation/results/cninfo_guizhou_moutai_2025_zh_10/moutai_qa_007_009_root_fix_20260927.json)
- MT-ZH-007 修复后：[moutai_qa_007_final_fix_20260927.json](../evaluation/results/cninfo_guizhou_moutai_2025_zh_10/moutai_qa_007_final_fix_20260927.json)

### 离线回归

- 最终全套离线 backend gate：2692 passed, 2 skipped, 40 deselected（命令排除了 e2e/perf/slow 标记）。
- 007–009 路由、事实规划、grounding、答案策略聚焦回归：297 passed。
- Ruff 和 `git diff --check` 在最终核对中执行。

## 数据来源与边界

事实核对来源是 CNINFO 冻结的贵州茅台 2025 年年度报告；冻结数据集记录的来源 PDF SHA-256 为 `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`。报告页面：[CNINFO PDF](https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF)。分地区和分销售模式事实来自报告第 10 页；审计意见正文来自第 53 页。

本记录不表示完整 10Q Benchmark 已通过，也不改变事实缺失时的拒答策略。所有 live QA 请求均发给本地 Qwen；DeepSeek/远程 Provider 调用数为 0。
