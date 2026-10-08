# Financial RAG Assistant — 综合质量门禁

日期：2026-09-16  
范围：100Q 已保存真实回答 + 离线检查 + Mock 故障注入 + 前端契约/构建 + Docker 健康检查

## 成本与安全

```text
新增 DeepSeek 主请求：0
新增 Evaluator 请求：100
新增 API 成本（按记录价估算）：约 $0.662883
ALLOW_REAL_PROVIDER：false
P1_3_SMOKE_AUDIT_PATH：unset
```

没有读取、写入或输出任何凭据、JWT、Authorization header 或 API key。

## 1. 100Q 运行与离线质量预检

来源：`evaluation/results/formal_20260916/evaluation_100_results.jsonl`

```text
总题数：100（英文 50 / 中文 50）
HTTP 200：100/100
Application Success：100/100
业务错误：0
空回答：0
结构化引用：341
结构化有效引用：341/341
Direct Chat：8/8 无引用
Unsupported：16 题，其中 4 题保留证据说明引用
Multi-turn：8/8 非空
中文回答语言信号：50/50
期望数字存在的题目：72
至少有一个期望数字出现在回答中：72/72（仅为确定性预检，不等价于语义正确率）
```

重要限制：本轮没有运行 LLM evaluator，也没有逐题人工金标准裁决。因此不能把结构化引用有效率或数字字符串重合率包装成 100Q 准确率。

## 2. 引用蕴含检查

已完成 source/chunk/page 的确定性存在性校验：341/341 PASS。

已使用独立 evaluator 完成 341 条引用的内容检查：

```text
VALID_SUPPORTED：118
VALID_BUT_NOT_SUPPORTED：223
INVALID_SOURCE：0
```

这说明引用对象都存在，但只有 118/341 条被 evaluator 判定为直接支持回答中的材料性主张；其余引用需要后续减少、替换或修复证据绑定。该 evaluator 与回答使用同一 Provider，结果应继续通过人工抽样复核。

评测器用量（Provider 返回值）：

```text
evaluator calls：100
input tokens：2,028,070
output tokens：61,065
cached tokens：64,000
按当前记录价估算：约 $0.662883
```

## 3. 中英文一致性

已完成：

- EN50/ZH50 均有非空回答；
- 50 条中文回答均有中文文本信号；
- 结构化引用均可定位到冻结证据库；
- 未发现 Provider 错误或运行时 fallback。

本轮新增逐对检查：

```text
EN/ZH 配对：50
expected criteria 完全一致：50/50
两侧都命中期望数字：36/50
evaluator grade 相同：31/50
grade 不一致：19/50
```

逐事实人工金标准仍需针对 19 个不一致配对继续裁决；当前不能宣称中英文答案等价。

## 4. 多轮对话与隔离

已完成：8 条冻结 multi-turn 样本均返回非空回答；租户隔离、知识库隔离相关测试包含在本轮后端测试中并通过。

隔离 In-app Browser E2E 已完成：

- 注册临时测试账户并进入已认证应用；
- 知识库页面可访问，显示多文件选择提示；
- 刷新后认证状态和路由恢复；
- 聊天输入框可编辑，填入文本后发送按钮正确启用；
- 清理测试输入和临时文档。

首次浏览器注册返回 502，定位为 frontend Nginx 缓存旧 backend 容器 IP；仅重启 frontend 后重试通过。该问题应在部署流程中通过 frontend/backend DNS 重新解析策略解决。

## 5. 异常注入（无真实 Provider）

结果文件：`evaluation/results/combined_quality_gate_20260916/failure_injection.json`

```text
Provider 429：3 次有界尝试，最终 RateLimitError，PASS
Provider 503：3 次有界尝试，最终 ProviderError，PASS
Provider timeout：3 次有界尝试，最终 ProviderConnectionError，PASS
Chroma 不可用：不生成虚假证据，异常传播，PASS
Redis 不可用：缓存安全 miss，恢复后可读，PASS
Redis broker：回退 DB polling，PASS
真实 Provider 调用：0
```

说明：故障注入覆盖 SDK/adapter/retriever/cache seam；完整 HTTP 错误页面和浏览器状态恢复不在该脚本的覆盖范围内。

## 6. 前端测试

```text
frontend npm test：31 passed / 0 failed
frontend npm run build：PASS
```

已覆盖聊天契约、长回答滚动、生成耗时、知识库上传/删除契约、文件校验、设置契约和刷新后的会话元数据恢复。

隔离浏览器已完成认证、知识库导航、刷新恢复和聊天输入交互验证。由于浏览器自动化环境未安装 Playwright 文件选择器运行时，无法在浏览器层直接提交 PDF 文件；批量上传已通过后端真实 HTTP 压力测试覆盖。

## 7. 性能

### 真实 100Q 延迟参考

沿用已完成的 100Q 真实请求延迟数据，未新增 Provider 请求：

```text
样本：100
p50：10507.89 ms
p95：27126.07 ms
p99：43097.75 ms
最大：43123.66 ms
```

该数据代表串行真实请求延迟，不代表并发压测或正式 SLA。

### 并发聊天（Mock Provider）

```text
请求数：20
并发数：20
HTTP 200：20/20
非空回答：20/20
错误：0
总墙钟时间：289.52 ms
p50：229.96 ms
最大：251.96 ms
真实 Provider 调用：0
```

### 批量上传（真实公开 Demo PDF）

使用隔离临时租户并发上传 Tesla、Apple、NVIDIA 三份公开 PDF；不调用 DeepSeek。任务结束后删除本次临时租户的 3 份文档。

```text
上传请求：3/3 HTTP 200
单请求耗时：69.80 ms / 2138.25 ms / 2204.02 ms
批处理墙钟时间：79094.71 ms
任务成功：3/3
任务失败：0
临时文档清理：3/3
真实 Provider 调用：0
```

## 后端与运行环境回归

```text
相关后端/评测/安全/租户/上传/运行时测试：307 passed, 7 skipped
Ruff：PASS
git diff --check：PASS
frontend：healthy
backend：healthy
agent-worker：healthy
postgres：healthy
redis：healthy
chromadb：healthy
/api/v1/health：200
/api/v1/ready：200
```

## 综合结论

```text
运行可靠性：PASS
离线结构与契约检查：PASS
异常处理 seam：PASS
100Q evaluator 语义准确率：29 CORRECT / 37 PARTIAL / 33 INCORRECT / 1 FAILED
引用语义蕴含：118/341 VALID_SUPPORTED
中英文逐事实等价性：19/50 配对 grade 不一致
隔离浏览器前端 E2E：PASS（文件选择器除外）
并发聊天压力测试：PASS（Mock Provider，20/20）
批量上传压力测试：PASS（3/3）
综合状态：PARTIAL
```

当前必须处理的质量问题：

1. evaluator 判定的 33 条 INCORRECT 和 1 条 FAILED；
2. 223 条结构有效但未被判定为内容支持的引用；
3. 19 个中英文配对事实/等级不一致；
4. frontend Nginx 启动时缓存 backend IP 的部署问题；
5. 浏览器文件选择器级上传和生成中继续输入仍需安装 Playwright 或完成人工验收。

本轮没有修改业务代码、没有提交、没有推送，也没有删除历史 artifacts。
