# CNINFO 贵州茅台中文问答测试（本地 Qwen）

日期：2026-09-26
数据集：`evaluation/datasets/cninfo_guizhou_moutai_2025_zh_10.json`（10 题，运行前冻结）
运行记录：`evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_run.json`

## 范围与来源

- 使用隔离 QA Compose project `moutai-qa-20260926`；其 SQLite、Chroma、uploads、logs 均为新建 QA 卷。正式服务及其卷未参与恢复或重建。
- 自动发现来源为巨潮资讯网；文档：贵州茅台 2025 年度报告（审计），报告期 FY2025。
- 官方 PDF：<https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF>
- 冻结数据集记录的 PDF SHA-256：`474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`。
- QA 索引任务成功；数据库文档状态为 `indexed`，Chroma 中有 584 个该文档 chunk，元数据 company 为“贵州茅台”。独立调用应用 HybridRetriever 的只读查询命中 8 条证据。
- 后续同租户发现接口返回 `already_present`，但该响应没有回填 `source_report_year` / `source_audited`（值为空）；首次下载响应和冻结数据集分别确认了 2025 / audited=true。建议后续单独检查 `already_present` 响应是否应复用已存来源 metadata。
- QA API 与 Worker 的 `LLM_PROVIDER` 均为 Ollama，allowlist 仅含 `ollama`，模型为 `srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`。本轮 DeepSeek 调用 0，外部 evaluator 调用 0，LLM API 费用 $0。

## 结果

10 题中仅发出首题 `MT-ZH-001`，其余 9 题未执行。首题 HTTP 200，运行 62.84 秒；API 返回 provider `ollama`，用量为输入 1,860 tokens、输出 71 tokens，缓存 token 未提供。

首题最终用户可见答案为空（报告模板标题存在，但回答段落为空），最终引用数为 0，API 最终 `evidence_count` 为 0。因此首题闸门 FAIL，按预设规则停止，不重试、不继续剩余题目。不能将这一结果判为回答正确，也不能由此推断 2025 年报没有相应内容。

独立 HybridRetriever 查询在同一隔离 QA 环境命中 8 条证据，说明“文档完全未索引”不是当前证据支持的解释；但单题结果尚未保存原始模型文本或完整逐阶段 planning/context 诊断，故目前不能断言损失发生在 LLM 空输出、grounding/sanitizer、引用投影或其他生产链路环节。运行 artifact 保存了公开问题、最终 API 答复、来源引用和 API 用量，不含账号密码或 JWT。

## 结论与下一步

`MOUTAI_10Q_STATUS: BLOCKED_AFTER_MT-ZH-001`。目前不满足开始剩余 9 题的门槛。后续一次本地 Qwen 诊断调用（不计入正式集、不用于评分）通过受控审计钩子捕获了原始回答和 grounding 各阶段数据：

- 生产链路提供给模型的上下文只有 1 个证据块（报告第 54 页），不是预期的第 6 页比较表；它足以支持 2025 营业收入，但不含 2024 营业收入，因此无法据此验证同比。文档已索引不等于当前问题所需证据已进入最终上下文。
- 原始模型回答正确复述了第 54 页的 2025 营业收入，并对缺少的 2024 数据拒绝计算；它不是空回答。
- 代码级根因：中文“2025年度”未在金额 grounding 的行期间解析中识别为 `FY2025`，逻辑转而采用文档日期 `2025-12-31`，和账本的 `FY2025` 不等价，导致有证据的金额被误判 unsupported 并清空。另一个独立问题是宽泛“收入”别名把“主营业务收入”重复记为总营收。
- 已实施 provider-free 修复：grounding 优先解析中文年度期间；账本将“主营业务收入”设为独立指标，避免污染总营业收入；增加贵州茅台/茅台/Moutai 公司别名，确保公司过滤生效。使用冻结诊断回答和公开来源片段新增回归测试。
- 只读 Chroma SQLite 与已记录的原始 PDF 解析块进一步确认：第 6 页的营业收入行确实被索引，但被标为 `unverified_table`，因此按安全策略从检索/grounding 排除。根因不是免费 embedding 的排序错误，而是解析器未将分散在相邻 PDF 文本块中的中文年度列标题（2025/2024/2023）与“本期比上年同期增减（%）”绑定到该行。
- 新增严格的 CNINFO 年度摘要解析：仅当相邻块同时含“主要会计数据/主要财务指标”、连续三个年度、明确同比列头及 `%`，且目标行精确为“营业收入”并有四个数值单元格时，才按已核实的列顺序重排年度金额；同比数值不作为年度金额。无完整映射的行仍保持 `unverified_table`。输出数值移除千分位逗号并显式标注 CNY，避免通用历史规则把逗号数误缩放为“百万”。Parser version 已提升为 v17，以便下游识别解析逻辑变更。
- 新增回归既验证 FY2025/FY2024/FY2023 值与列位正确，也验证缺少同比列头时不提升为可信表格。相关 document-loader、ledger、grounding、P1.1/P1.4 和 period-aware retrieval 测试共 `241 passed`；Ruff 与 `git diff --check` 通过。没有调用模型，也没有运行剩余 9 题。

这次离线修复覆盖了已确认的解析/列映射问题，但尚未将新 parser 版本应用到隔离 QA 索引，也没有通过真实 HTTP → 检索 → 最终上下文 → 本地 Qwen 生产链路复核。因此第 6 页证据能否重新进入最终上下文、最终答案能否正确保留营业收入及引用，仍未验证；不得判定 MT-ZH-001 PASS。隔离 QA API/Redis 容器已停止；四个隔离 QA 卷（SQLite、Chroma、uploads、logs）保留，正式六服务未修改。下一步应在隔离 QA 项目中使用新 parser 版本重建/重索引该公开年报，核对页面 6 的 chunk metadata 与 FY2025/FY2024 账本事实，再只执行固定首题一次受限本地 Qwen 验证。只有 MT-ZH-001 通过后，才考虑其余 9 题；本次未授权 DeepSeek，也未调用任何 Provider。

## 安全与运行状态

- 没有输出或保存临时账户密码、JWT、API key 或 AUTH secret。
- 正式六服务运行实例未重建；现有数据库和 Chroma/uploads 数据未删除。
- QA 运行容器之后停止时使用 `docker compose down`（无 `-v`）；新建 QA 卷保留用于后续诊断。
- `ENCRYPTION` / provider fallback 未被用作答复替代；没有针对失败结果自动重跑。

## 2026-09-26 后续诊断与当前闸门

**思路校正：**此前把这类答案失败归因于 embedding 分割/排序并不符合当前证据。新 parser 将表格行正确写入隔离 Chroma，HTTP 请求也取回了正确的第 6 页引用；当前已观察到的剩余缺口在事实计划：问题明确要求与 2024 年比较，但计划只要求 FY2025 单期营收，未将 FY2024 对照值列为必答事实。不能据一次正确的 FY2025 数字就把整题判为通过。

- 先前 v17 的直接上传诊断未设置公司元数据（落为 `Unknown`），按公司过滤后没有候选证据；它不是本题正式结果。正式验证改用产品的 CNINFO 自动发现/下载入口，获取 audited FY2025 报告并成功索引，避免用诊断路径代替真实业务路径。
- 在隔离 v18 栈中，仅通过真实 `POST /api/v1/chat` 发出一次固定 `MT-ZH-001` 本地 Qwen 请求；HTTP 200、应用成功、1 条第 6 页引用，最终答案正确给出 FY2025 收入，但漏答 FY2024 数值以及同比下降 1.21%。因此本题仍为 **PARTIAL / GATE FAIL**；未重试，也未运行后续 9 题。该调用结果保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v18_mt_zh_001_run.json`。
- 离线修复：年度 FY 标签现在可绑定结构化 YoY 单元格到最新明确年度；annual comparison FACT 规划要求问题点名的前期年度作为对照 operand；同比计划只针对主报告期，不会把 FY2024 的对照项再扩张成 FY2024 同比要求。
- 新增回归覆盖 FY2025 YoY 绑定到 FY2025（不误绑 FY2024），以及该固定中文问题需要 FY2025 营收、FY2024 对照值、FY2025 YoY，且三项都可由 ledger 找到。还以真实 Qwen 首答作为离线 fixture，验证 `finalize_grounded_answer` 会通过确定性事实补齐保留三项核心答案、负值 `同比变化 -1.21%`（负号表示下降）及证据引用，并且最终 unsupported count 为 0。运行的聚焦测试为 243 passed（含 document loader、事实账本、grounding、P1.1/P1.4 与期间检索）；答案策略联测 154 passed。Ruff 通过；`git diff --check` 无空白错误（Git 仅报告既有行尾转换提示）。
- 验证完成后只停止了 v18 隔离容器，v17 也保持停止；没有删除任何卷或运行 `down -v`。正式 Docker 六服务仍为 healthy。临时 Ollama QA compose override 已移除；结果 artifact 与隔离卷保留。未调用 DeepSeek、远程 evaluator 或其他计费 Provider。

**当前决定：**离线年度比较与确定性补充 contract 回归通过，但 MT-ZH-001 的原始一次 Qwen 答案仍为 PARTIAL；离线 fixture 证明的是账本 completion contract，不替代完整 API sanitizer/citation 最终路径验证。禁止把 10 题状态写成 PASS；剩余 9 题未运行。下一步最多对冻结首题做一次新的单题本地 Qwen 验证，并检查最终 API 输出是否保留三项数值、同比方向与有效引用；不是立即开始完整 10Q。

## v19 单题复测与冻结集续测（最新）

- 在代码更新后新建 `moutai-qa-v19-20260926` QA Compose 项目和隔离卷，重建 API/worker 镜像；没有触碰正式 PostgreSQL/Redis/Chroma/uploads 卷。使用 CNINFO 产品发现入口后命中已存在的同租户年报（`already_present`），因此没有重复下载；原接口该分支未返回审计/年份字段，已按历史首次下载的公开来源信息核对。
- `MT-ZH-001` 只发出一次新请求：HTTP 200，Ollama Qwen 本地模型，37.42 秒，无 fallback，引用为同一份年报第 6 页，semantic support 为 supported。最终内容含 2025 营收 168,838,102,514.79 元、2024 等值金额 170.89915227634 billion CNY、同比变化 -1.21%（负值表示下降）。单题 **PASS**；该结论只针对这一题。
- 随后按固定顺序请求 002–009。002–008 HTTP 200；009 在 45.27 秒 HTTP 504，立即停止，不重试。010 未运行。没有 DeepSeek/外部 evaluator 请求；本地 Qwen 总请求 9 次（001–009，009 usage 未返回）；8 条调用 usage 已记录，合计输入 19,225、输出 725 tokens，cached usage 未提供，外部 API 成本 $0。

逐题人工核对冻结 expected answer 与引用：

| Case | 观察结果 | 判定 |
|---|---|---|
| MT-ZH-001 | 当前营收、前期等值金额、负同比及第 6 页引用均在最终答复中 | PASS |
| MT-ZH-002 | 2025 净利润和第 33 页引用正确；没有回答 2024 净利润及同比 -4.53% | PARTIAL |
| MT-ZH-003 | 拒答数值/变化；引用第 6 页只涵盖原因文字，未给出要求的数值 | FAIL |
| MT-ZH-004 | 回答“证据不足”，没有给年报已披露的现金流下降原因，也无引用 | FAIL |
| MT-ZH-005 | 回答证据不足；第 18 页引用只有标题/列信息，无目标收入与毛利率值 | FAIL |
| MT-ZH-006 | 回答证据不足；第 10 页引用只有表题/列名，未比较两个毛利率 | FAIL |
| MT-ZH-007 | HTTP 200 但报告模板内回答段为空，属于空答案 | FAIL |
| MT-ZH-008 | 没有利用请求中的贵州茅台公司上下文，反问用户公司名；无引用 | FAIL |
| MT-ZH-009 | HTTP 504，45.27 秒后超时；未重试 | FAIL / RUNTIME |
| MT-ZH-010 | 未运行（遵守超时即停） | NOT RUN |

批处理脚本曾把“整份 report 模板非空”误当“回答非空”，因此在发现 MT-ZH-007 空答后又发出了 008/009；这是本轮测试 harness 的缺陷，已在本报告披露。之后以“回答段实际文本”人工重新解析已保存结果，不对 007、008、009 重试。MT-ZH-010 属于允许无引用的证据不足用例，所以也修正了先前“每题强制至少一个引用”的过严假设。

**结论：**`MOUTAI_ZH_10Q_STATUS: PARTIAL / FAIL`，不能宣称贵州茅台 10Q 通过。结果表明收入摘要行解析修复可支撑 MT-ZH-001，但其他表格/期间/公司上下文、多题证据覆盖与响应超时仍有明显缺口。v19 的 API、worker、Redis 容器已停止，隔离 QA volumes 和运行 artifacts 保留；生产六服务在复核时均 healthy。测试期间未开启真实远程 Provider，未请求或输出任何 API key、密码或 JWT。

## 2026-09-26 离线收敛（无 Provider 请求）

依照 v19 的真实失败定位，在不重跑 Qwen/DeepSeek、不启动 Docker、不删除隔离卷或历史 artifacts 的前提下完成：

- `core/core_engine.py` 将 API 的公司字段传入检索之后，也补进 grounding、required-fact plan 与 generation prompt；只有原问题和已解析对话都没有公司实体时才补入，不覆盖显式问题公司，也不改变 Direct Chat。最终 sanitizer 若移除全部内容，API 现在回退到安全的“证据不足”答案，不再返回空回答。
- `core/required_fact_plan.py` 将无季度标签的中文 `2025年` 解析为 `FY2025`；现金流同义别名归一后去重，避免同一问题同时要求 `cash_flow` 和 `operating_cash_flow`。
- `document_loader.py` parser v18 对年度摘要仅结构化核实过的营业收入、归母净利润、经营活动现金流净额；对分产品/地区/销售模式表，仅在分区名、完整财务列头、允许的行标签和六个完整数值列都对齐时结构化收入/毛利率/同比。处理了 PDF 将“百分点”末尾“分点”拆到相邻块的情况；不会合并任意相邻段落。其他行继续保持未核验状态。
- 用临时下载的同一份 CNINFO 官方 PDF 实跑 PyMuPDF/parser/FactLedger（没有把 PDF 加入仓库）：第 6 页解析出 FY2025/FY2024/FY2023 收入、归母净利润、经营现金流及已披露 YoY；第 10 页 6 个产品/地区/渠道行全部生成 FY2025 Revenue、Gross Margin 与 Revenue YoY ledger facts。关键实际事实与[巨潮年度报告原文](https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF)一致。
- 新增回归覆盖白名单摘要行、分区表行完整性、缺少分区标题时拒绝结构化、公司字段贯穿生产 prompt 与 grounding、FY2025/FY2024 账本、最终答案空值兜底。
- 验证：`pytest -q tests/test_document_loader.py tests/evaluation/test_final_answer_policy.py tests/evaluation/test_fact_ledger_row_grounding.py tests/evaluation/test_p1_4_evidence_first.py` → **280 passed**；Ruff → **PASS**；`git diff --check` → **PASS**（仅有既有文件行尾转换提示）。

**当前闸门：**本次只证明离线解析和 API 代码契约，尚未在新 parser 版本下重建隔离 QA 镜像/索引，也未通过 HTTP → Chroma 检索 → final context → 本地 Qwen 复验。v19 的失败题目前不能改判 PASS，10Q 仍是 `PARTIAL / FAIL`。下个验证阶段应使用新的隔离 QA project（保留 v17/v19 volumes），重建并重新索引同一官方 PDF，然后做有限本地 Qwen HTTP smoke；任何超时立即停止，不重试替换。

## v20 单题链路复测（HTTP 504）

- 使用新的隔离项目 `moutai-qa-v20-20260926`，重新构建当前 API/worker；重新通过产品 CNINFO 自动发现并索引公开审计年报。QA 用户、文档和向量均属于隔离 QA tenant/volumes；没有触碰正式 PostgreSQL、Redis、Chroma 或 uploads 数据。
- QA API 与 worker 配置为 Ollama-only，`ALLOW_REAL_PROVIDER=false`；本地模型仍为 `srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`。只经真实 `POST /api/v1/chat` 发出一次 `MT-ZH-002`：`2025年归属于上市公司股东的净利润是多少？同比变化多少？`。HTTP 返回 **504**，按规则立即停止；没有重试，也没有发出其余 9 题。
- 该 HTTP 失败没有返回可审阅的原始/最终答案、引用、usage 或可靠逐阶段耗时；不得对本题打分或声称答案正确。安全运行记录保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v20_mt_zh_002_run.json`，只含非敏感状态字段。
- 隔离 QA `/api/v1/ready` 返回 200，API、数据库、Redis 为 `ok`；该 Compose 使用嵌入式 Chroma，ready 的 `chroma` 项为 `unknown`。独立只读检查确认 Qwen 标签仍存在，`ollama ps` 显示模型驻留、上下文 8192。生产六服务复核均 healthy。
- API 将 `ProviderTimeoutError` 映射为 504；当前 Ollama adapter 的配置将 read timeout 限制到不超过 `LLM_READ_TIMEOUT=45s`，而总请求 deadline 为 120s。由于请求级日志没有记录阶段时间/异常来源，这只能说明候选超时边界，不能证明此次 504 精确由 45 秒 read timeout 触发。没有再发模型请求来探测。
- 仅为隔离 QA 将 Ollama `LLM_TIMEOUT` 调为 110s、`LLM_READ_TIMEOUT` 调为 95s（连接 10s、总 deadline 仍 120s），并只重建隔离 API/worker；已核对两者仍是 Ollama-only 且 `ALLOW_REAL_PROVIDER=false`。Compose config 与健康检查通过。这个调整是新的受限验证配置，不是通过放宽 10Q 质量标准；MT-ZH-002 尚未再次请求。

**结论：**`MT-ZH-002: NOT GRADED / RUNTIME TIMEOUT`，`MOUTAI_ZH_10Q_STATUS: PARTIAL / FAIL`，10Q 不通过；已完成的解析器离线回归仍为 280 passed，但真实 HTTP→本地模型→grounding/citation 输出链路未通过。本轮未调用 DeepSeek、远程 evaluator 或其他计费 Provider。v20 API/worker/Redis 与隔离卷暂保留；下一次请求必须作为修正超时配置后的单题新验证单独记档，若再超时即停止，不再进行同题重试。

## MT-ZH-002 超时调整后单题结果

- 机器重启后确认 v20 API/worker/Redis 容器已退出，但四个隔离 volumes 仍存在；使用原 v20 项目与 volumes 恢复 QA 服务，未触碰生产 volumes。QA `/api/v1/ready` 为 200；provider 为 Ollama、`ALLOW_REAL_PROVIDER=false`；超时为 connect 10s / read 95s / request 120s。
- 调整后仅对冻结题 `MT-ZH-002` 发出一次独立请求：HTTP 200，耗时 43.51 秒（API `execution_time` 43.455 秒），Ollama 用量 input 2,426 / output 82 / cached unknown。旧的 504 记录没有覆盖；本次记录为 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v20_mt_zh_002_timeoutfix_run.json`。
- **质量仍 FAIL/PARTIAL**：回答只给出 2025 归母净利润 82,320,067,101.68 元，漏掉 expected 的 2024 对照数 86,228,146,421.62 元及同比下降 4.53%。API 返回 1 条引用，但引用预览展示利润分配/分红内容，没有证明净利润或同比；该 citation 不能认证为有效。
- 因为该题的事实覆盖和引用支撑仍未达标，暂不继续 003–010；先离线检查 required-fact plan、最终 context 与 citation projection 是否保留第 6 页证据，避免用更多本地模型请求掩盖 grounding/retrieval 问题。未调用 DeepSeek 或远程 evaluator。

**当前状态仍为 `MOUTAI_ZH_10Q_STATUS: PARTIAL / FAIL`。** 95 秒 read cap 下此次 HTTP 成功，但单个结果不能证明先前 504 的精确根因；MT-ZH-002 的质量闸门仍失败。

## v21 隔离修复验证（parser v19）

- 根因复核：v20 Chroma page 6 的净利润结构化文本确实存在，但 `content_type=unverified_table`。解析块本身是 `table`，其相邻 chunk 被 `_merge_tiny_page_chunks` 合并后，保守地整块标成 unverified；检索和 citation gate 因而排除正确年报行，最终误命中第 33 页利润分配内容。
- 修复：chunker 与短块合并器现在都阻止 `table` 和 `unverified_table` 跨信任边界合并；不会跨边界复制 overlap。parser version 升为 `pymupdf-blocks-ocr-v19-table-trust-boundaries`。真实官方 PDF 重跑解析，page 6 归母净利润行现在是单独的 `table` chunk；QA 新索引也核实同一行 `content_type=table`、`metrics=net_income`、FY2025/FY2024/FY2023/YoY=-4.53%。
- 回归：新增 chunk boundary、实际 Moutai 问题的 required growth plan 与确定性补全测试；相关 4 项 pytest **PASS**，Ruff **PASS**，`git diff --check` **PASS**。使用全新隔离 `moutai-qa-v21-20260926` 卷，通过官方 CNINFO discovery 下载并索引 2025 审计报告（589 chunks）。v20 仅停止容器，原四个 QA volume 保留；正式卷未触碰。
- timeout 受限验证：QA-only Ollama timeout 为 connect 10s / read 95s / total 120s，远程 Provider 仍禁用。MT-ZH-002 在这套经修复索引上 HTTP 200 / 43.51s；回答数值 82.32006710168 billion CNY 和 YoY -4.53%，引用为报告第 6 页净利润行。MT-ZH-003 HTTP 200 / 16.35s；回答 61.52220498935 billion CNY 和 YoY -33.46%，引用为第 6 页经营现金流行。两条数值及同比均与冻结 key 一致，证明原来正确行被过滤的问题已修复。
- **严格评分仍为 PARTIAL**：两题冻结 `expected_answer` 均包含前期比较金额；production answer completion 只输出本期金额和 YoY，省略 FY2024 operand，且报告句式含英文别名 `moutai FY2025`。所以不把两题记为全项 PASS，也不继续 004–010；先离线修复同比题的比较 operand 补全与中文 issuer label，再进入后续验证。
- 本次 v21 两个本地 Qwen 请求 usage：MT-ZH-002 input/output 3,333/50 tokens；MT-ZH-003 4,535/62；cached usage 未提供。没有 DeepSeek、远程 evaluator 或计费 API 调用。结构化结果保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v21_mt_zh_002_003_run.json`。另有 QA 容器网络初始未挂接，重建隔离 API 容器后 readiness 恢复 200；没有影响生产服务或数据。

**结论：**504 的 QA timeout mitigation 有两次 HTTP 200 证据，且主要根因（正确行被 `unverified_table` 信任标记污染）已离线修复并在新隔离索引验证；原始 504 仍保留历史失败记录，不能声称其精确触发阶段已经证明。贵州茅台 10Q 仍 `PARTIAL / FAIL`，因为 002/003 的前期比较金额和中文表达尚未完全符合冻结预期；其余 7 题未在 v21 运行。

## v22 同比前期金额与发行人标签修复验证

- 离线修改 `core/required_fact_plan.py`：用户明确询问同比时，如果账本确有同指标上一年度事实，就把前期金额列为 required fact；没有前期数据时不新增硬性要求。确定性补全同时将规范公司键 `moutai` 显示为“贵州茅台”（英文显示名为 Kweichow Moutai）。
- 扩展 `test_moutai_annual_net_income_answer_completes_requested_yoy_from_verified_row`，并更新公司上下文合同测试，明确计划中包含 FY2024 与 FY2025。首轮回归有一项旧断言仍假设只计划 FY2025；更新为新合同后复跑通过。
- 复用 `moutai-qa-v21-20260926` 的隔离 QA 数据卷，以新镜像重建 API/worker；配置仍为 Ollama-only、`ALLOW_REAL_PROVIDER=false`，未删除或覆盖任何卷。`/api/v1/health`、`/api/v1/ready` 均为 HTTP 200，worker 与 API healthy。
- 只通过真实 `POST /api/v1/chat` 单独执行 MT-ZH-002、MT-ZH-003，各一次，没有自动重试：

| Case | HTTP / 耗时 | 最终答案关键事实 | 引用 | 判定 |
|---|---:|---|---|---|
| MT-ZH-002 | 200 / 43.034s | FY2025 净利润 82.32006710168 billion CNY；FY2024 86.22814642162 billion CNY；同比 -4.53%；发行人显示“贵州茅台” | 同一审计年报第 6 页净利润表行 | 本轮严格核心标准 PASS |
| MT-ZH-003 | 200 / 16.792s | FY2025 经营现金流 61.52220498935 billion CNY；FY2024 92.46369216843 billion CNY；同比 -33.46%；发行人显示“贵州茅台” | 同一审计年报第 6 页经营现金流表行 | 本轮严格核心标准 PASS |

- 两份不覆盖历史记录的运行结果分别保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v22_mt_zh_002_run.json` 与 `.../local_qwen_v22_mt_zh_003_run.json`。本轮本地模型 usage 合计 input 7,970、output 111 tokens；cached token 未提供。真实远程 Provider/DeepSeek 请求为 0，外部 API 成本 $0。
- 最终离线回归：`pytest -q tests/test_document_loader.py tests/evaluation/test_final_answer_policy.py tests/evaluation/test_fact_ledger_row_grounding.py tests/evaluation/test_p1_4_evidence_first.py` → **282 passed**；相关 Ruff → **PASS**；`git diff --check` → **PASS**（仓库其他既有改动仍有行尾转换提示）。
- 测试后仅停止 v21 隔离 API、worker、Redis 容器；v21 DB、Chroma、uploads、logs volumes 均仍存在。未执行 `down`、卷删除或生产数据操作。复核正式六服务：frontend、backend、agent-worker、postgres、redis、chromadb 均 healthy。

**范围结论：**本轮只重测 002/003，两题对同比前期金额遗漏和英文 `moutai` 标签的回归已修复。不能据此把贵州茅台完整 10Q 评测改为 PASS：其他题未重跑，且此前 004–009 的历史失败仍需按冻结顺序逐题复核；010 未运行。DeepSeek 仍禁用。

## MT-ZH-004 失败及离线回归修复

- 冻结题原文：`年报中2025年经营活动现金流净额下降主要归因于什么？`。在改动前以隔离 QA 的 HTTP → Ollama-only 本地问答链路请求一次：HTTP 200 / 25.756s，但最终答案只复述 FY2025/FY2024 经营现金流和 -33.46%，没有回答下降原因。唯一引用预览是第 6 页结构化现金流表行，不含原因段落；所以本题 **FAIL**，不因为数值正确或报告有引用而给 PASS。
- 资料不是缺失：对已缓存的 CNINFO 官方 PDF 做只读页文本抽取，第 6 页明确写到现金流净额减少主要与控股子公司吸收集团成员单位存款减少、以及不可随时支取的同业存款增加有关。这个结论来自报告原文，不是模型推断。
- 已证实的离线链路问题：改动前 `classify_query_scope` 将“主要归因于什么”判为 `FACT`，required-fact plan 只要求数值及同比；现有显式 driver 问句规则也未覆盖这类财务变化归因问法。因此 API 只拿到/使用了数字表行并补全数字，没有确保因果披露进入最终上下文。**具体遗漏发生在 candidate、rerank 或 context builder 哪一阶段，现有 HTTP 响应未暴露分阶段记录，仍不能精确归因。**
- 离线修复：把“归因/下降原因/减少原因/下滑原因/变化原因”和对应英文因果措辞归入 `ANALYSIS`；该类分析问题通过已观察到的公司/期间上下文生成有限的指标原因检索 probe，使自然语言原因段落与数字表行有机会共同进入检索结果；不改 reranker 权重、Top-K 或 frozen expected answer。新增 scope/probe 回归，覆盖公司从已检索证据继承、query 期间可见及现金流净额原因 probe。
- 新增的三个定向 pytest 与 Ruff 当前通过；完整相关离线回归和修复后的 MT-ZH-004 HTTP 验证仍须单独记录，不能先行将该题改判 PASS。失败后已停止 QA 容器；v21 隔离卷保留，未再发送模型请求。

**当前结论：**002/003 本轮通过；004 最近一次真实 QA 仍为 FAIL。离线 cause-intent/probe 修复已经落地，但在再次通过隔离 HTTP 链路证实原因段进入证据并由回答引用前，不继续 005–010。

## MT-ZH-004 离线修复后的隔离 HTTP 验证

- 离线回归完成：
  `pytest -q tests/test_hybrid_retrieval.py tests/test_retrieval_probes.py tests/evaluation/test_query_scope.py tests/evaluation/test_answer_grounding_contract.py tests/evaluation/test_final_answer_policy.py tests/evaluation/test_fact_ledger_row_grounding.py`
  → **283 passed**；两条引号/中英文来源回归 → **2 passed**；相关 Ruff → **PASS**；`git diff --check` → **PASS**。
- 仅重建隔离 v21 QA API 与 worker，继续挂载原 v21 SQLite、Chroma、uploads、logs 卷；Compose `config -q` 通过，API `/api/v1/ready` HTTP 200，worker/API healthy。Ollama 模型可用，运行配置确认 `LLM_PROVIDER=ollama`、固定 Qwen 3.8、`ALLOW_REAL_PROVIDER=false`。生产六服务未重建。
- 首次验证时遗漏了认证：请求以 tenant 0 运行，而只读检查显示官方报告的 589 个 chunk 全在 tenant 1；因此该次 HTTP 200 / 0 引用 / 0 usage 是无证据拒答，不是模型调用或质量评分。修正测试身份后，通过 QA 注册接口创建临时测试用户（默认 tenant 1）；密码/JWT 未输出、未写入结果文件。
- 使用冻结数据集原文 `年报将2025年经营活动现金流净额下降主要归因于什么？` 单独请求一次：HTTP **200**，耗时 **45.093s**，执行耗时 45.053s；Ollama input/output **5,878/213** tokens，cached unknown；远程 Provider/DeepSeek 调用 0。
- 最终回答明确给出年报披露的两项原因：控股子公司吸收集团成员单位存款减少、不可随时支取的同业存款增加。返回 1 条引用，指向贵州茅台 2025 年审计年报第 6 页，预览含同一因果原文；未出现“证据不足”矛盾句或额外因果推断。故 `MT-ZH-004: PASS`、Evidence Utilization `FULL`。自动补充的来源摘录带有英文前缀 `Moutai:`，不影响公司/事实/引用正确性，但属于可后续改善的中文呈现细节。
- 完整响应与引用保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v24_mt_zh_004_authenticated_run.json`。前述未认证调用不纳入有效模型测试；没有为了替换任何有效失败结果而重跑。

**当前闸门：**MT-ZH-002、003、004 在当前修复线上各自通过；贵州茅台完整 10Q 仍是 `PARTIAL / FAIL`，不能推断整体通过。按冻结顺序，下一项是 MT-ZH-005；其余结果仍需逐题审核，超时或 Provider 错误均停止该轮，不自动重试。隔离 v21 QA 容器当前保持运行以便后续验证；四个 QA volumes 与生产卷均未删除或覆盖。

## MT-ZH-005 首次当前版本验证

- 使用冻结问题 `2025年茅台酒和其他系列酒各自实现多少收入？各自毛利率是多少？` 经隔离 QA API 只请求一次，HTTP **200** / 31.213s，Ollama-only；input/output **6,192/110** tokens，cached unknown，DeepSeek/远程调用 0。
- 答案未满足要求，判 **FAIL**：回答把 `76.11%` 作为没有产品限定的毛利率，又把 `4.85014232268 billion CNY` 作为公司营收；但 API 返回的引用预览分别标明“其他系列酒收入”和“国外地区收入”。回答遗漏茅台酒收入 146,499,906,480.49 元、茅台酒毛利率 93.53%、其他系列酒收入 22,274,678,707.16 元及其毛利率的完整标签绑定。因此这是可观察到的产品/地域维度污染与事实覆盖失败，不是报告缺少这些数据的证据。
- 原始答案及两条返回 citation preview 保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v24_mt_zh_005_authenticated_run.json`。**不重试，不继续 006–010**；下一步应将这次失败转为离线回归，检查 required-fact plan、产品维度检索覆盖、证据标签与数字 claim grounding，之后先用无 Provider contract tests 验证。
- QA 隔离卷保留。认证请求使用的临时 QA 测试用户凭据未记录；不会为撤销测试记录而直接改写 QA 审计/用量数据。生产数据、生产卷和正式六服务未修改。

**当前状态：**本修复线上 MT-ZH-002/003/004 为 PASS，MT-ZH-005 为 FAIL，MT-ZH-006–010 未运行；完整 10Q 维持 `PARTIAL / FAIL`。`READY_FOR_NEXT_QWEN_CASE: NO`，待 MT-ZH-005 的离线维度/标签回归与修复完成后再决定是否继续。

## MT-ZH-005 离线根因确认与类别作用域修复

- 一次且仅一次的已认证本地 Qwen 请求已记录为 FAIL；没有重试。离线只读查看 v21 QA Chroma 的 589 个报告 chunk，确认茅台酒、其他系列酒与地域行均来自报告第 10 页的解析结果，财报数据不是缺失。
- 用相同的生产 `HybridRetriever`、QA 隔离 Chroma、tenant 1 对冻结问题做无 Provider 检索复现：基础 Top-4 前两项正是茅台酒与其他系列酒行；完整生产检索/探针上下文包含 8 个 chunk，其中还混有酒类总计、国内/国外、直销/批发等不同维度。生产计划却将问题判为 `FACT`，只要求通用 `revenue` 与 `gross_margin`，`FactLedger` 也把所有类别下的同 metric 值合并在一起。由此可确定是维度/类别作用域缺失，而非向量召回缺失；不能把后续回答错误归因给 embedding 或文件内容。
- 离线修复：`FinancialFact` 现在保留结构化行的 `dimension/category`；FactLedger lookup、必答计划、数值防串用与账本补全可按类别精确限定。对明确询问多个产品类别“各自/分别”的问题，计划为每个类别分别要求其被问到的指标；未标明类别的数值不能满足这些要求，错误类别/地域数值会被移除，再从同类别证据确定性补全。
- 新增两个针对真实解析结构的离线合同测试，验证“茅台酒 / 其他系列酒”收入与毛利率分别绑定，且国外地域营收不能填进产品营收。完整关联套件：`pytest -q tests/test_hybrid_retrieval.py tests/test_retrieval_probes.py tests/evaluation/test_query_scope.py tests/evaluation/test_answer_grounding_contract.py tests/evaluation/test_final_answer_policy.py tests/evaluation/test_fact_ledger_row_grounding.py` → **285 passed**。初次 Ruff 找到一处 E731 风格错误，已改为局部函数；当前 Ruff 与 `git diff --check` 均 PASS。
- 本轮到此停止：尚未将类别作用域修复重建到隔离 QA 镜像，也未再次调用本地 Qwen；因此 `MT-ZH-005` 仍按真实 Provider 结果标记 FAIL，新增修复只可记为 offline PASS。继续之前需单独重建隔离 API/worker 并只重测固定 005 一次；不得据离线测试改判线上答案通过。MT-ZH-006–010 未运行，完整 10Q 仍 `PARTIAL / FAIL`，DeepSeek/远程 Provider 调用 0。

## MT-ZH-005 维度修复后单次 QA 请求

- 修复后的 API/worker 已在隔离 `moutai-qa-v21-20260926` QA 栈重建；API、worker healthy，`/api/v1/ready` HTTP 200。运行配置为本地 Ollama `srchmnmichael/Qwen3.8-Uncensored:Q4_K_M`，`ALLOW_REAL_PROVIDER=false`，请求 deadline 120 秒；生产栈和 QA 数据卷未删除或覆盖。
- 对冻结原题 `2025年茅台酒和其他系列酒各自实现多少收入？各自毛利率是多少？` 发出**唯一一次**认证 `POST /api/v1/chat` 请求。HTTP **504**，总耗时 **120.305 秒**；没有答案、引用或可用 token usage。响应为 deadline 超时提示。结果保存在 `evaluation/results/cninfo_guizhou_moutai_2025_zh_10/local_qwen_v25_mt_zh_005_after_dimension_fix.json`，未记录测试账号凭据、JWT 或 Secret。
- 该 504 证明修复后的真实请求尚未完成，但不能证明类别修复本身正确或错误；API/worker 仍 healthy，应用日志没有提供可归因的阶段级超时记录。因此具体卡在 Ollama 推理、provider I/O 或其他阶段**未确定**。没有自动重试，没有再次调用 Qwen；DeepSeek/远程 Provider 调用仍为 0。
- **结论：MT-ZH-005 = FAIL / TIMEOUT，维度修复的真实回答效果未验证。**本地离线维度作用域回归保持通过，但不得据此声称端到端问题已解决。按单次请求失败即停止规则，MT-ZH-006–010 不运行；贵州茅台完整 10Q 维持 `PARTIAL / FAIL`。下一步应先针对 120 秒请求超时做离线/运行阶段诊断，再由用户明确启动新的单次验证；不得在当前轮重试。
