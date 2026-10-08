# 茅台 10Q 超时问题：离线修复记录（2026-09-27）

## 结论

本次 `MT-ZH-005` 失败于 Provider timeout，不是 429，也不是知识库限额。该请求在 45.5 秒返回 HTTP 504；QA trace 标记 `provider_timeout`，`rag_execution` 阶段耗时约 45.3 秒。隔离容器实际使用 Ollama；代码默认值为总请求 deadline 120 秒、连接超时 10 秒、读取超时 45 秒。Ollama adapter 将有效读取超时限制在该 45 秒值，因此本地推理尚未完成时会先于 API 总 deadline 失败。

## 修复

- 新增 provider-specific timeout budget：仅对 Ollama 将 socket/读取超时扩展至 `LLM_TOTAL_DEADLINE`，同时仍受每个请求的绝对 deadline 限制。
- connect timeout 保持 10 秒；DeepSeek 等远程 Provider 仍使用原 `LLM_TIMEOUT` / `LLM_READ_TIMEOUT`，没有扩大远程调用预算。
- Router 与 legacy provider builder 都使用同一规则，避免不同入口行为不一致。
- 未增加 retry，也未调整检索、Top-K 或 benchmark 题目。

## 验证与边界

- 离线定向测试：Ollama timeout、Router/legacy config、P1.3.1 timeout recovery、final-answer policy。
- QA 容器内已确认有效值为 connect 10 秒、read/overall 120 秒、hard deadline 120 秒；QA `/api/v1/ready` 返回 HTTP 200。
- 本轮未再次调用 Qwen/DeepSeek，也未重跑 `MT-ZH-005`；生产 Docker 六服务未重建。
- 这修复了 45 秒 socket timeout 与 120 秒 API deadline 不一致的问题，但不能证明复杂问题一定能在 120 秒内完成。此前另一轮 `MT-ZH-005` 也曾到达约 120 秒 deadline；因此下一次单题请求仍可能触发硬 deadline，必须先完成要求的离线门禁再另行验证。

## 10Q 状态

`local_qwen38_10q_ui_zh_20260927_r2.json`：MT-ZH-001～004 HTTP 200、各有引用，但语义评分仍待审核；MT-ZH-005 HTTP 504；MT-ZH-006～010 未运行。整个 10Q 仍为 `PARTIAL / FAIL`，不得据此宣称通过。
