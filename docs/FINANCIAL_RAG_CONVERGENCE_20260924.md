# Financial RAG 收敛记录（2026-09-24）

## 操作目的

停止对同一批历史语义结果的重复重跑，冻结当前已验证实现，并将剩余问题按“代码缺陷 / 评测标准或数据问题 / Provider 生成质量”分层。

本次收敛操作不调用 DeepSeek 或其他付费 Provider，不修改冻结 expected criteria，不增加 question-specific hardcode。

## 已关闭的代码问题

| 问题 | 处理 | 验证 |
| --- | --- | --- |
| 财报表格 `current period / prior-year period / YoY` 的同比归属错误 | 按最新标记季度绑定增长率；命名指标在性能问题中允许确定性同比推导 | Apple Services 回归测试通过；Q2 FY2026 服务收入 30.976B、同比 16.25% |
| 中文“业务做得怎么样”无法保留可验证增长 | 增加中英文性能意图识别，并限制在命名指标范围内推导 | 中英文 segment-growth 回归测试通过 |
| Grounding-safe projection 与来源证据不一致 | 保持 production policy 的证据约束，不放宽错误引用 | source audit 318/318；final unsupported numeric/qualitative 0/0 |

## 当前验证基线

- Offline pytest: `2603 passed, 23 skipped`
- Ruff: `PASS`
- `git diff --check`: `PASS`
- Docker 六服务：`frontend/backend/agent-worker/postgres/redis/chromadb` healthy
- `/api/v1/health`: `200`
- `/api/v1/ready`: `200`
- DeepSeek / paid Provider calls: `0`

## 未宣称已修复的问题

| 案例/现象 | 分类 | 收敛结论 |
| --- | --- | --- |
| EN-019 | 题目未指定期间，冻结标准与上传财报期间存在歧义 | 保留为 benchmark policy decision，不改答案标准或硬编码题目 |
| EN-017、EN-026、EN-047、ZH-022、ZH-026 | Provider 叙述质量或冻结标准覆盖范围问题，当前未证明为确定性检索/解析缺陷 | 不继续重复跑；若要处理，另开 Provider generation / benchmark policy 专项 |
| 5 条本地 Qwen reviewer JSON 无效 | 评测工具输出格式问题 | 不作为应用代码修复结果，不据此宣称通过 |

## 收敛规则

1. 不再重复运行同一批历史语义评测。
2. 只有发现新的、可最小复现的代码根因，并能新增回归测试时，才允许继续改代码。
3. 不通过降低 Numeric/Citation 标准、修改 expected answer、放宽公司/期间约束来消除失败。
4. 在新的 Provider 质量专项或 benchmark policy 决策完成前，不运行 DeepSeek 100Q 或付费真实 Provider 评测。
5. 后续任何真实 Provider 测试必须单独申请、冻结题集、记录成本，并在失败时停止而不是自动循环重跑。

## 最终状态

当前实现进入 **CONVERGED / FROZEN FOR THIS SPRINT**：代码缺陷修复已收敛，剩余问题已转交到明确的评测标准或 Provider 质量边界，不再作为同一 Sprint 的循环修复项。

## 收敛后追加的确定性修复

随后的一次聚焦审计发现并关闭了一个新的通用根因：显式业务驱动问题
只保留前两段证据，且多公司驱动问题没有按公司 fan-out 检索。修复后，
Apple Services、Tesla 以及多公司驱动证据均有回归测试保护；来源约束
（“只用 Apple 财报回答 NVIDIA”）仍然安全拒答。

验证：`2608 passed, 23 skipped`，Ruff 通过，DeepSeek/付费 Provider 调用为 0。

## 最终收口验证

- Frontend contract tests: `41 passed, 0 failed`
- Frontend production build: `vite build PASS`
- Docker 重建范围：仅 `backend`、`agent-worker`；未执行 `down`，未删除 Volume
- 六服务状态：`frontend/backend/agent-worker/postgres/redis/chromadb` 均 `running/healthy`
- `/api/v1/health`: `200`；`/api/v1/ready`: `200`
- `ALLOW_REAL_PROVIDER`: `FALSE`；本轮 Provider calls: `0`
- 变更边界：未 commit、未 push；保留工作区已有修改

## 本轮最终收口（2026-09-24）

收敛审计又发现一个可最小复现的通用缺陷，因此按收敛规则只做了一次
有回归保护的修复，没有重跑 100Q、没有启用 DeepSeek：

1. 财报表格被扁平化后，地理/分部小计或年度历史行可能与合并季度总收入
   共享期间元数据。规划器现在优先明确标注的 total net sales/revenue，
   并使用有限的重复值簇作为辅助信号。
2. 多公司“谁的增长最强”问题现在由已验证的同比事实或当前/上年同期
   两个 operand 确定性计算；最终答案说明期间不一致时仅作方向性比较。
   排名句和期间免责声明都必须通过 issuer-complete grounding，不能靠
   无关 citation 或放宽 gate。

真实样本复现结果：Apple `111.184B`、Tesla `24.901B`、NVIDIA `81.615B`；
同比分别为 `16.6%`、`-3%`、`85%`，最终保留 NVIDIA 排名且
`unsupported_claim_count = 0`。此前错误的 Apple `92.963B` 地理小计和
Tesla `53.823B` 年度历史值不再被选中。

本轮验证：`2611 passed, 23 skipped, 1 warning`；Ruff PASS；前端 41 项
contract tests PASS；Vite build PASS；`git diff --check` PASS（仅已有
CRLF 提示）；Docker 六服务均 running/healthy；`/api/v1/health` 与
`/api/v1/ready` 均为 200；启动/登录相关日志未发现 secret/JWT 泄露。

随后针对 EN-022/ZH-022 的实际证据缺口增加了通用 company/observed-period
收入与增长探针。新的来源审计 artifact：
`evaluation/results/current_source_retrieval_audit_20260924_v74_growth_fact_probes/`
显示 `330/330` 必需事实检索、`330/330` 投影，双语来源事实差异 `0`，
unsupported numeric/fact projection `0`，且 Provider/evaluator 调用仍为 `0/0`。

本轮仍明确不宣称：EN-019 的冻结标准期间歧义、Provider 自由生成质量、
以及未经人工/真实 Provider 复核的历史语义等级已被“自动修好”。这些属于
独立的 benchmark policy 或 Provider 质量边界，不能通过循环重跑收敛。

## 最终边界修复与 v95 重放（2026-09-24）

在上述检索修复后，重放发现旧 Provider 草稿中的“Apple 营收无法评估/证据
不存在”句子可能在最后合并阶段重新出现，与当前可信事实矛盾。修复了最终
回答边界的 stale-growth-absence 清理，并加入 `not assessable`、`contains no
... revenue`、`revenue ... absent` 等英文变体回归保护；仅在所有命名公司的
营收同比事实完整且确定性排名已通过 grounding 时启用，不改变普通证据不足的
拒答策略。

v95 历史回答重放（仍不调用 Provider）结果：

```text
source facts projected: 330/330
final unsupported numeric claims: 0
final unsupported qualitative claims: 0
EN-022/ZH-022 deterministic ranking: present
EN-022/ZH-022 stale revenue-absence claim: absent
historical semantic labels: unchanged (PARTIAL 37 / CORRECT 29 / INCORRECT 33 / FAILED 1)
provider/evaluator calls: 0/0
```

这里的 historical semantic labels 是冻结历史答案标签，不是本轮重新生成的
准确率；本轮只证明生产 grounding/finalizer 不再输出已知的矛盾性数字/缺证据
声明。

最终验证更新为：`2612 passed, 23 skipped, 1 warning`；前端 41 项 contract
tests、Vite build、Ruff、`git diff --check` 均通过。仅重建 backend 与
agent-worker，未执行 `down`、未删除任何 Volume。六服务均 healthy，health/ready
均返回 200，启动与登录相关日志未发现 secret/JWT 泄露。

## 本地 Qwen 低成本语义探针（非 DeepSeek 发布门禁）

使用当前 v74 来源审计和生产 prompt/grounding/finalizer，对固定高风险案例
`EN-007`、`EN-019`、`ZH-008`、`ZH-013`、`ZH-044` 调用本机 Ollama
`srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`。结果保存在：
`evaluation/results/local_ollama_quality_probe_20260924_v76_convergence/`。

```text
cases: 5
application_success: 5/5
empty_output: 0
output_truncated: 0
final_unsupported_numeric_claims: 0
paid_provider_calls: 0
```

`ZH-044` 保持 direct-chat、无财报引用；其余问题经过当前 evidence-first
grounding。该探针是本地模型语义诊断，不等价于 HTTP/DeepSeek 实时发布门禁，
因此不会把它包装成真实 Provider PASS，也不会据此开启 100Q。

## 生产 Provider 成本门禁修复（2026-09-24）

一次隔离 HTTP 本地模型链路试验暴露了新的确定性安全缺陷：数据库持久化的
默认路由仍可选择 DeepSeek，而 `ALLOW_REAL_PROVIDER=false` 只在 pytest
环境被检查，生产进程可能继续构造真实 DeepSeek 客户端。试验在发现响应
路由为 `deepseek` 后立即停止并删除临时容器；由于旧实现的保护范围不足，
不能排除该临时试验已产生最多两次真实 Provider 请求，不能将本次试验记为
零调用。没有继续发送请求，也没有把这次结果作为质量门禁。

修复内容：

- DeepSeek 客户端构造在所有运行环境都要求显式
  `ALLOW_REAL_PROVIDER=true`；默认值或 `false` 直接 fail closed。
- pytest 中仅允许注入的 SDK test double，不放宽真实网络调用。
- 新增生产式 guard regression，覆盖没有 `PYTEST_CURRENT_TEST` 的场景。

验证：`tests/test_deepseek_provider_v4.py` 与 retry 套件 9 passed；全量
pytest 更新为 `2613 passed, 23 skipped, 1 warning`。重建 backend/agent-worker
后，运行容器内直接构造 DeepSeek 客户端返回预期 `ProviderError`，不触网；
六服务 healthy，health/ready 200，日志未发现 secret/JWT 泄露。

随后将同一规则提升为共享 `provider_guard`：外部 OpenAI、Gemini、Anthropic
和 Doubao 也必须显式 opt-in；本机 Ollama-compatible 地址保持可用。新增
外部/本地端点回归测试后，全量 pytest 为 `2622 passed, 23 skipped, 1 warning`。
backend 与 agent-worker 容器内逐一验证五个外部 Provider 均返回
`ProviderError`，Ollama 地址标记为本地允许；六服务、health/ready 和日志
检查均再次通过。

## Provider guard wiring regression（2026-09-24）

为避免只测共享 helper 而遗漏适配器接线，新增了五个生产适配器的 lazy-client
边界回归：DeepSeek、OpenAI、Gemini、Anthropic、Doubao 在
`ALLOW_REAL_PROVIDER=false` 时都必须在 SDK client 构造前 fail closed。该测试
不发起网络请求，也不读取或打印任何 credential；目标是防止未来新增/重构适配器
绕过统一成本护栏。新增测试文件中的 14 项断言全部通过（其中包含既有端点
helper 与新增 adapter wiring cases）。这仍然是离线安全门禁，不等价于当前版本
真实 Provider 发布 Smoke；`ALLOW_REAL_PROVIDER` 继续保持 `false`。

追加后的完整离线回归：`2627 passed, 23 skipped, 1 warning`（253.44s）。

## 当前版本真实 Provider Canary（2026-09-25）

在用户明确授权后，仅执行冻结的 `EN-007` 一次真实 HTTP 请求；没有启动
5Q、10Q、100Q，也没有 evaluator 或自动重试。结果为客户端 `read=45s`
读取超时：HTTP `599`，总耗时约 `45005.79ms`，未收到可评估的 raw/final
答案，因此 token、Provider 调用次数与费用均保守记为 `UNKNOWN`，不能推断为
零成本或成功。结果 artifact：
`evaluation/results/p1_3_2_real_provider_canary_20260925/`。

Canary 结束后立即将 backend/worker 恢复为 `ALLOW_REAL_PROVIDER=false`，审计路径
清空；六服务、health/ready 均恢复正常。该失败被分类为真实 Provider/runtime
timeout，而不是语义答案失败；在离线复现或明确调整超时契约并补测试前，不得
再次发起真实请求。聚焦离线 timeout/guard 回归为 `25 passed`，没有产生新的
Provider 调用。

随后用户明确授权在同一固定范围内重试一次。第二次 `EN-007` Canary 成功：
HTTP/application `1/1`，延迟 `23422.62ms`，真实 Provider 调用 `1`，
EN-007 `CORRECT`，Evidence Utilization `FULL`，最终 unsupported numeric、
wrong-company、wrong-period 均为 `0`；raw claims `30`，其中 `13` 条不支持
claim 被 sanitizer 移除，未调用 evaluator，主查询成本 `$0.00352584`。
这只证明当前单题 Canary 通过，不代表 5Q/10Q/100Q 已通过；同样在结束后
恢复 `ALLOW_REAL_PROVIDER=false`，未自动扩展测试范围。
