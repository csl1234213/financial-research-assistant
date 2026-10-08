# P1.6.2 实现检查点

状态：`IN_PROGRESS`，不是阶段验收 PASS。日期：2026-09-29。

正式源码目录为 D 盘仓库。本阶段新增独立离线层，没有修改生产 worker、数据库、Chroma、Answer Prompt 或 retrieval Top-K，也没有调用 Provider。

## 已实现

`document_compatibility/` 复用现有 `parse_pdf` 和 P1.3 重建结果，增加以下链路：

```text
Existing parser + native span inventory
 → fingerprint / composable format families / page features
 → canonical blocks with source IDs
 → completeness detection
 → validated native/header recovery or quarantine
 → serialization and chunk provenance guards
 → offline quality report / corpus comparison / promotion decision
```

- `models.py`：指纹、格式族、页面特征、span/block、恢复来源、失败签名、质量报告与状态。
- `adapters.py`：原生 PDF、OCR、表格和既有布局算法的最小适配器；按页/区域保存原始来源。
- `policy.py`：已安装 parser 能力、版本化策略、失败签名记录、恢复注册表与质量契约。
- `engine.py`：关键别名覆盖检查、孤立 span 检测、区域覆盖、原生数字优先、跨页表头继承、序列化与 chunk 完整性验证。
- `promotion.py`：完整 corpus、策略非回归、结构化行/事实数量和 P1.7 回归结果共同约束离线 promotion。
- `scripts/document_compatibility_audit.py`：独立 JSON 审计入口和真实 OCR 探针，不访问数据库或 Provider。
- `tests/fixtures/compatibility/manifest.json`：按失败能力组织的 16 个 fixture 定义。
- `tests/test_document_compatibility.py`：模拟故障、真实 PDF 适配、两个不同文档的同类恢复、未知格式隔离与策略比较。

`financial-pdf-v1-observe` 与 `financial-pdf-v2` 都是本阶段新引入的可执行策略；v1 不是历史生产策略的复现。既有 DocumentLoader 的解析阶段先执行，当前策略控制离线审计、恢复和输出；生产 parser 调度仍未接入。

## 本轮修正

1. 原先来源追踪用字符串子串匹配，独立数字 `1` 会错误关联包含该数字的长金额。改为完整数字 token 检查，不再误报 595 条结构化行中的列错位，同时保留金额篡改负向测试。
2. 跨页表格续表标题不一定被旧 parser 标为 heading。改用表格上方的短标题及显式 continuation 标记识别，仍要求相邻页、同一章节及列坐标一致。
3. 缺失、跨页或错误文档的 source ID 不得通过 provenance 校验。
4. chunk 保留来源 ID 不等于内容可信；校验其文本属于引用的 canonical block，阻止夹带无来源的新结论。
5. 尚无验证实现的表格修复不再标记为可自动执行的 `TABLE_REGION_REPARSE`，明确路由人工复核。

## 真实贵州茅台 fixture 观察

该 fixture 是 71 页摘录，其中 16 页有文字、55 页为空白占位；不是完整 143 页年报。

| 项目 | 结果 |
|---|---:|
| 页面 PASS / WARNING / FAIL | 71 / 0 / 0 |
| 非空原生 spans | 1563 |
| Canonical blocks | 905 |
| 离线 traced chunks | 924 |
| chunk 输入 / 消费 blocks | 905 / 905 |
| 孤立 spans / 关键孤立 spans | 0 / 0 |
| 未解释 block 丢失 / 序列化丢失 | 0 / 0 |
| VERIFIED rows | 595 |
| FinancialFacts（显式 2025 财年上下文） | 98 |
| 原生数字被 OCR 覆盖 | 0 |

一次本机观察耗时：原生解析约 1.95 秒，指纹与库存约 1.13 秒，初次审计约 0.37 秒。该结果只是单次测量，不是性能基准；审计时间尚未覆盖报告组装的全部耗时。

生产 chunker 未改变。905 个 block 包括既有重建结果和保留的候选表格，因此不能把离线 chunk 数量与生产去重后的数量直接比较。

## 验证记录

- 初始兼容层回归：26 passed、1 skipped。
- 来源校验与完整策略比较加入后，兼容层 + P1.7：49 passed、1 skipped。
- 真实 OCR：使用已有 runtime 镜像、只读源码挂载、禁用网络、2 CPU / 2 GB 内存的临时容器。扫描版及混合版都 READY，金额保留、各处理 1 页，原生数字覆盖数为 0。没有进入现有生产容器。
- 全仓 Ruff：PASS。
- `git diff --check`：PASS，既有历史文件存在换行提醒。
- 本轮全量离线：2861 passed、3 skipped、21 live tests deselected，393.16 秒。该运行在最后一轮来源校验加固前启动，不代表最终冻结版本已完成全量验收。
- 最后一轮加固后的兼容层：32 passed、1 skipped；包括 16 个 corpus case、新旧策略比较、来源引用与 chunk 额外内容负向校验。
- 上述测试不能替代以下尚缺验收。

## 剩余验收与明确限制

1. 复杂合并单元格：已补齐真实 PDF 几何检测与正反例，详见下方 v3 更新。
2. 多栏阅读顺序：已补齐真实 PDF、canonical 顺序及 chunk 顺序的检测，详见下方 v3 更新。
3. `PERIOD_CONTEXT_LOSS`、`UNIT_CONTEXT_LOSS`、`SCOPE_CONTEXT_LOSS`：已补齐来源绑定检测；P1.3 的既有验证没有被更改。
4. 还需扩展 trace：完整 critical raw/canonical/chunk 三阶段清单、所有请求的 silent-loss 指标、准确的全阶段计时。
5. 无法打开的损坏 PDF 仍需统一转为结构化失败报告，而不只是 CLI 异常。
6. 最终代码冻结后，需再次确认 targeted/full offline suite 与 diff review，再按任务书单独提交。历史脏路径不得混入。

因此 `P1_6_2_STATUS = IN_PROGRESS`，`COMMIT = NOT_CREATED`。没有自动进入 P1.6.3，没有部署或推送。

## v3：真实结构与上下文检测补齐

本次范围：上述第 1–3 项。策略为 `financial-pdf-v3`，保留 v1/v2 的策略开关，不将新的检测规则伪装成旧策略。

### 合并单元格

- 从实际 `find_tables` 返回的 cell bbox 计算跨行／跨列范围，保存在 `TableCellGeometry`。
- 合法的层级表头、跨列分类标题、跨行标签保留原始几何，不复制金额填充空格。
- 金额跨越多个行／列且没有 P1.3 已验证的显式 cell binding 时，返回 `MERGED_CELL_AMBIGUITY` 并隔离。
- 两个不同文档名分别运行合法、横向金额合并、纵向金额合并测试；规则不依赖公司名。

### 多栏阅读顺序

- 原生 PDF 页面经已有布局算法形成有来源 ID 的顺序约束。
- 验证实际 canonical 输出顺序，不只检查一个预设 confidence。
- chunk 出口再次验证顺序。人为将输出改成左一／右一／左二／右二，或将 chunks 反转，均不得 READY。
- 页面 reading_order_status 与最终失败保持一致。

### 上下文丢失

- 从表格表头和相邻上方源区域捕获期间、单位、合并／母公司口径，保留对应 source ID。
- 按 table block 绑定，不以整页或整份文档出现过关键词作为成功证据。
- 删除或错配绑定后，返回相应 `*_CONTEXT_LOSS`；另一个表格仍保留相同年份也不能掩盖丢失。
- 中英文双表测试区分万元／元及 millions／thousands、合并／母公司。
- 相邻页、同一章节和列坐标匹配的续表可继承有来源的上下文；继承内容随序列化、chunk 和恢复 provenance 保留。
- 原文没有单位／口径不被错误归类为“解析丢失”。此时 completeness READY 不等于 FinancialFact 有资格入库；原有 P1.3/P1.5 eligibility 仍独立生效。

### 测试与发布边界

- 新增真实 PDF 结构测试 21 项全部通过。测试会创建 PDF 后通过实际 PyMuPDF 读取，不直接伪造 FailureClass。金额格式还覆盖货币符号、USD 前缀、括号负数和全角数字。
- 完整兼容性 corpus 从 16 项扩展到 24 项；本轮最终兼容层测试共 61 passed、1 skipped。
- P1.3–P1.7 联合 targeted 回归：134 passed、1 skipped。
- 新策略下贵州茅台 fixture 仍为 READY、595 VERIFIED rows；孤立 span、关键孤立、未解释 chunk 丢失和原生数字覆盖均为 0。
- 6 个新负向案例在旧策略下曾 READY，在 v3 下正确隔离；策略比较明确报告该差异并阻止自动 promotion，未偷偷放宽发布门禁。
- 本轮 Docker OCR 复验未执行成功：Docker Desktop Linux Engine pipe 不存在。没有启动或重建生产 Docker，之前的 OCR 结果不作为本轮最新镜像验收。
- 本轮全量离线结果：2892 passed、3 skipped、21 deselected，495.49 秒。该运行在最后的页面状态字段修正与金额格式边界加固前启动；这些最后差异已由随后完成的 61 passed、1 skipped 兼容层测试覆盖。正式整阶段提交前仍要求冻结版本的全量验收。
- 本轮不扩大为 P1.6.3 生产接线，不自动提交未完成整阶段的工作树。

支持边界：几何检测针对现有原生有线表格候选，不能由此宣称任意无框线、旋转表格、OCR 表格或所有排版均已覆盖。上下文规则针对明确的中英文标记；不能凭来源中没有的信息推断期间、单位或口径。

本轮三项子门禁：`REAL_MERGED_CELL_DETECTION = PASS`、`REAL_MULTICOLUMN_ORDER = PASS`、`SOURCE_CONTEXT_LOSS_DETECTION = PASS`。此结论针对上述明确的测试能力，不等于整个 P1.6.2 已完成生产发布验收。
