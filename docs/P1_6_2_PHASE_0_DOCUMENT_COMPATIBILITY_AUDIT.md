# PHASE_0_DOCUMENT_COMPATIBILITY_AUDIT

审计日期：2026-09-29。正式源码与当前 Docker 构建目录：`<repository>`。

状态：PHASE_0_COMPLETE；P1.6.2 实现尚未开始。本文记录当前工作树，不等同于 HEAD 或生产索引的能力声明。本次只检查源码、依赖和本地 fixture，未改变生产 worker、数据库、Chroma、Provider 或已有实现。

## 前提校正

- P1.6.2 是补强 ingestion 的独立工作项，不意味着撤销已存在的 P1.7。P1.7 已有代码和回归测试；本轮没有重新执行全部 P1.7 验收。
- `tests/fixtures/moutai-standard-statements-2025.pdf` 是 71 页摘录：16 页有原生文字、55 页为空白占位、0 页含嵌入图像。它不能代表完整 143 页年报或扫描 PDF。
- “任何失败都可检测”不能作为对所有未知 PDF 的已证明承诺。可验收目标应是：已定义 failure class 的 detectors/corpus 覆盖，以及无法建立可信覆盖关系时不得 READY。
- 现有 native/OCR、表格恢复、格式分派和版本字段需要复用；缺失的是统一库存、丢弃原因、质量契约、恢复路由和 promotion 决策。
- `METRIC_UNMAPPED`、缺少文档身份、空白页、无缓存公式结果不能统称 parser loss。

## 1. 当前真实调用链

上传：`api/routers/upload.py:52` 校验 payload，保存文档并提交 PROCESS_DOCUMENT task；自动发现下载入口：`api/routers/knowledge.py:271`。`tasks/worker.py:33` 分派到 `process_document_task`。

PDF 链路：

```text
process_document_task
  → load_pdf_chunks(document_id=...)
  → parse_pdf
  → PyMuPDF page.get_text(blocks/words)
  → native regions / reading-order heuristic
  → low-text page OCR + OCR noise filter（按页）
  → ParsedBlock + table-context attachment
  → page.find_tables(lines) / ParsedTableCandidate
  → trusted table row text 或 spatial table recovery
  → P1.3 reconstruct_financial_statements
  → ParsedDocument / FinancialTableRow
  → chunk_document / split / merge / deduplicate
  → DocumentChunk
  → embeddings / VectorDocument
  → Chroma delete_document + add_documents
  → P1.4 mapping + P1.5 eligibility + P1.6 persistence
  → task SUCCESS / document indexed
```

非 PDF：`load_document_chunks` → `document_formats.load_structured_document_chunks` → HTML/XLSX/DOCX/CSV parser → 同一 ParsedDocument/chunker。BM25 在检索阶段使用索引中的文本语料，不是本 worker 中另一份独立写入。

## 2. Raw extraction object/schema

`document_loader.py:155` 起已定义：

| 类型 | 当前字段／意义 | 缺口 |
|---|---|---|
| ParsedTextRegion | text, bbox | block 级，并非保留全部 glyph/span 的库存；无 ID |
| ParsedTableRow | cells, cell_bboxes, bbox | 行列由 tuple 位置隐式表达；无独立 cell ID/span schema |
| ParsedTableCandidate | page, table_index, bbox, rows | 已脱离 PDF handle 保存候选表格 |
| ParsedBlock | text/page/section/ocr_used/is_heading/table_context/source_locator/content_type/bbox/financial_table_row | 无稳定 block_id、parser_id、policy_version、discard/recovery provenance |
| ParsedPage | number, blocks, ocr_used, text_regions, table_candidates | 无 page quality report、raw/native/OCR 并存库存 |
| ParsedDocument | filename/pages/parser_version/content_type/financial_table_contexts/financial_table_rows | 无 fingerprint/profile/quality decision |
| DocumentChunk | text/page/section/index/versions/context/locator/content type/format/typed rows | 无 source_block_ids、几何区域列表或 consumed/discarded ledger |

OCR 内部为 PyMuPDF TextPage，但 `_extract_ocr_blocks` 最终返回 `list[str]`，bbox 在该接口丢失。Word tuples 仅在空间表格算法内短期使用。HTML/Office 会先转换为文本 block，没有统一 raw-cell/span inventory。

## 3–4. 可用 parser 与真实能力

本地确认：PyMuPDF 1.27.2.3、openpyxl 3.1.5、python-docx 1.2.0；运行容器 Tesseract 5.5.0，镜像包含 eng/chi-sim 包。

| 现有组件 | 适合角色 | 能力与限制 |
|---|---|---|
| PyMuPDF native blocks/words | native PDF primary | 原生文字与坐标；非扫描识别器；文字抽取成功不证明覆盖完整 |
| PyMuPDF find_tables(lines) | 表格候选 primary | cells/geometry；依赖布局；异常目前降为空候选 |
| 既有 spatial binding + P1.3 reconstruction | 原生财务表结构恢复 | 显式列/期间/单位/scope、相邻续表约束；只验证已有候选行 |
| Tesseract via PyMuPDF | scan fallback；未来可作为异常区域 verifier | 当前 full-page OCR；文本噪声筛选；无 native/OCR 数值冲突契约 |
| `_column_reading_order` | native layout recovery | 能识别部分双栏；不确定时回退默认顺序，无 FAIL/WARNING 信号 |
| stdlib HTMLParser | HTML primary | 保留表格行文本；丢失空单元格/独立列定位；不支持完整 SEC/XBRL 语义 |
| openpyxl | XLSX primary | 坐标、合并范围检查、公式缓存值；没有计算公式 |
| python-docx | DOCX primary | 文档顺序、段落/表格行定位；合并金融单元格标记为 unverified |
| stdlib csv | CSV primary | 列头绑定、行号；非几何 parser |

未发现现有 Docling/pdfplumber/layout 模型适配器，不能列为已支持。当前没有独立运行的 shadow parser。原生二次抽取可作为一致性检查，但不能宣称独立 parser 交叉验证。

## 5–6. 几何、reading order 与追踪

Native block bbox、表格 bbox、行 bbox、cell bbox 已保留；typed FinancialTableRow 保存 source_region/source_locator。reading order 仅由列表顺序表达，无置信度／证明状态。

一般文本的 bbox 没有进入 DocumentChunk；chunk 只保存页面、section 和拼接 locator，locator 还会截断到 1000 字符。typed row 的来源信息随 financial_table_rows_json 保存。当前可追到 chunk/page 或 typed row/cell，不能普遍实现 `chunk → block IDs → raw spans`。

## 7. 丢弃、降级与潜在 silent-loss 位置

以下是已审查主链路中的位置；“缺少审计记录”不代表已经证明每处都丢失了有效内容。

| 位置 | 当前行为 | 需要的审计分类 |
|---|---|---|
| `_extract_text_regions`:798 | 去除非 text blocks、空字符串；不保存 image/figure inventory | NON_TEXT/EMPTY discard，图片区域仍须登记 |
| `parse_pdf`:412–430 | 低文字量页 OCR 有可用结果即整体替换 native；清空 native regions | native/OCR 冲突与替换审计；不能仅以字数裁决数字可信度 |
| `_filter_ocr_blocks`:2309 | 丢噪声 block，只有数量日志；全拒绝后回 native | 每块 reason/source；mixed 文档的空页可能被其它页掩盖 |
| `_column_reading_order`:828 | 不确定时返回 None，调用者用默认 geometric order | MULTICOLUMN_READING_ORDER_ERROR，无法证明正确时明确降级 |
| `_find_native_table_objects`:1131 | find_tables 异常记录日志后返回 [] | PAGE/TABLE failure，不能等价于“无表格” |
| `_materialize_table_candidates`:1150 | 某候选异常只记日志并省略该候选 | TABLE_STRUCTURE_LOSS inventory |
| `_extract_structured_table_blocks`:1216 | 密度、表头、列数不合格则跳过；bound_row=None 无逐行 reason | 合理拒绝结构化与原文丢失分别计数；原生文本/候选表可能仍存在 |
| spatial/P1.3 reconstruction | 跳过重复表头、空值、无列映射、无法 parse Decimal 等 | 对合法 discard 与未知数据损失分别登记；保持既有 VERIFIED 门禁 |
| `_attach_table_context`:2700 | 部分文字重写为绑定行／更改 trust type，没有 old/new 映射 | TRANSFORMATION provenance，不能用文本相等误判 orphan |
| `_merge_chunks`:2627 | 归一化去重段落，context 取 first-or-second，locator 截断 | 重复内容合并后需保留全部来源；检测 context/locator loss |
| `_deduplicate_chunks`:2677 | 全文去重、短于 40 字、heading-only 删除，无逐块 reason | CHUNK_BLOCK_LOSS；页不同但文字相同的出处会被合并丢失 |
| HTML parser | 空 td 不进入 cells，row flatten；短 block(<2)删除；无独立 row ID | 空列位置/serialization coverage；避免把行文本保留等同于列结构保留 |
| DOCX/CSV | 少于 2 行的 DOCX table 跳过；标题/header 消费后无统一 inventory | 单行有效表格、header context 需有来源与 discard 记录 |
| `_clean_cell` | >4000 字截断并附提示 | 已有提示但无 document hard gate／残余内容库存 |

另有确定的入口差异：`load_document_chunks(.pdf)` 未传递 document_id。直接 `parse_pdf` 不传身份时，fixture 的 595 行为 PARTIAL；传入身份则为 VERIFIED。worker 的 PDF 分支传了身份。因此它是调用契约/身份完整性问题，不应伪装成表格恢复失败。

## 8. 当前 ingestion success 条件

`tasks/knowledge_tasks.py:273` 要求 chunks 非空，embedding 数量一致；完成向量写入和 fact ingestion 调用（含 SKIPPED/NO_ELIGIBLE_FACTS 等正常返回）后，435 行设置 SUCCESS，448 行设 indexed。

没有 page/block/critical content coverage gate；没有要求 FinancialFacts 非零。Chroma 先删再加，随后保存关系库事实，并非跨存储原子 promotion；失败时 document 会标 failed，但不能推断已经写入的向量自动回滚。P1.6.2 仅设计离线 promotion，生产事务改造留 P1.6.3。

## 9–15. 现有抽象盘点

| 问题 | 结论 |
|---|---|
| routing 粒度 | 文件级扩展名分派；PDF 内按页低字数 OCR、native-table/spatial fallback；尚无 region router |
| format detection | 扩展名 + signature/container 校验、局部财报标题/期间识别；无可组合 format-family profile |
| capability abstraction | 无统一 registry/supports/parse_page/parse_region 协议 |
| failure taxonomy | 有 DocumentProcessingError、日志、typed-row verification_reasons；无统一 compatibility failure taxonomy |
| recovery policy | 有散落的 OCR、空间表格、续页 context、双栏启发式；无 signature/registry/router 或版本对比 |
| quarantine | 有 unverified_table 和 row eligibility；Document.status 无正式 QUARANTINED 状态机/契约门禁 |
| policy versioning | 已有 parser_version=`pymupdf-blocks-ocr-v20-financial-row-reconstruction` 和 chunker_version=`page-block-section-v5-table-trust-boundaries`；无独立 parser_policy_version |

parser version 应描述实现，policy version 应描述组合/阈值/路由/恢复规则；二者不应互相替代。

## 16. 茅台 fixture 基线与 format families

本轮直接离线解析（OCR 关闭，显式 document_id）：

| 指标 | 实测 |
|---|---:|
| PAGES_TOTAL | 71 |
| PAGES_NATIVE_TEXT | 16 |
| EMPTY_PLACEHOLDER_PAGES | 55 |
| PAGES_WITH_EMBEDDED_IMAGES | 0 |
| RAW_NATIVE_SPANS（另读 PyMuPDF dict） | 1566 |
| PARSED_TEXT_REGIONS | 289 |
| PARSED_BLOCKS | 884 |
| BLOCKS_WITH_BBOX | 289 |
| BLOCKS_WITH_SOURCE_LOCATOR | 595 |
| TABLE_CANDIDATES | 21 |
| FINANCIAL_STATEMENT_CONTEXTS | 8 |
| VERIFIED_ROWS | 595 |
| FINANCIAL_FACTS（显式提供 fiscal calendar） | 98 |
| CHUNKS | 108 |
| narrative / unverified_table / table chunks | 11 / 38 / 59 |

98 facts 使用显式 supplied fiscal context，不表示生产自动推断或生产 DB 已具备这些 facts。Native span 数与 block 数粒度不同，不能直接相除称为覆盖率。当前 ORPHANS、UNEXPLAINED_DROPS、geometry coverage、page PASS/WARNING/FAIL 均为 NOT_MEASURED，不能报 0。

适合标注的 family：CAS_ANNUAL_REPORT + NATIVE_TEXT_PDF + 财务表格/续表能力。COMPLEX_TABLE_REPORT 的分类阈值需在新 classifier 中定义，不能因为是财报就自动赋予。fixture 空白页不应触发 SCANNED_PDF。

## 17. Compatibility Corpus 缺口

现有 tests 已覆盖：native 页/section、双栏 prose、full-width section breaks、空间列绑定、续表继承、OCR mock 噪声/异常、XLSX/DOCX merged-cell rejection、跨格式值一致性、真实茅台重建/P1.5/P1.7。

`tests/fixtures` 当前只有上述真实 PDF；很多场景通过 tmp_path 动态生成 fixture 或 mock，不能说“只有一个测试场景”。缺少统一 manifest、按 capability/failure 的统计与全 corpus runner；尤其缺：

1. 实际扫描 PDF + 真实 OCR 成功/失败与数值冲突；mixed native/scanned PDF 的按页计划。
2. 不确定 reading order 必须 quarantine；区域覆盖缺口与 orphan 恢复。
3. 主 parser 漏关键 block、shadow 保留的 generic recovery 和 provenance。
4. serialization-loss / chunk-loss 注入及 hard gate。
5. 同 failure class 跨两个不同文档使用同 detector/recovery 的验证。
6. unknown profile/failure 拒绝 READY；policy v1/v2 regression comparator。
7. native/OCR numeric conflict 的保留原生值审计；空白页与 image-only 页区分。
8. 完整报告覆盖回归。当前摘录通过不等同于正文、附注、图表全量覆盖。

## 18. 最小增量架构方案

建议建立独立 `document_compatibility/` 层，保留已有 parser 与 P1.3–P1.7 接口。第一版只输出离线报告和 promotion decision。

1. **模型与 inventory**：DocumentFingerprint/PageFeatures/Profile/DocumentBlock/ExtractionInventory/DiscardRecord/PageQualityReport。复用 ParsedBlock/TableCandidate，新增稳定 source IDs、source refs、old/new provenance，raw inventory 与 canonical 版本分别保留。
2. **registries**：可组合 FormatFamily；只登记真实可用 parser 的 CapabilityRegistry；FailureClass/Signature/RecoveryPolicy/QualityContractRegistry。所有规则按结构特征，issuer 信息仅作为文档 metadata。
3. **adapter + versioned policy**：包裹 native、现有 table/reading-order、OCR；支持能力查询，未支持 region parse 必须明确声明。primary/shadow 的 authority 独立，OCR 不得覆盖可信 native 数字。
4. **audit**：page+bbox overlap+保守文本匹配建立 raw→canonical→serialized→chunk 映射；复用 P1.4 aliases 做 critical-presence inventory，不更改语义映射；合法合并/拆分必须保持多对多来源。
5. **targeted recovery**：优先既有 native/table/续页/布局恢复；OCR 只处理需要的页/区域。已知 signature 选择已验证 recovery；未知失败或缺少 detector 证明则 QUARANTINED。恢复再次走相同审计，禁止覆盖既有 VERIFIED rows。
6. **quality/promotion**：结构完整性与财务行可用性分列；hard gate 检查关键 orphan、chunk/serialization loss、来源、未知失败、契约不满足。普通叙述格式不应仅因未覆盖完整财务本体被误判 parser loss；CAS annual 契约可要求三大报表。输出离线 READY/QUARANTINED/FAILED，不直接改 worker。
7. **corpus**：A–H manifest + unknown format/failure + native/OCR conflict + cross-document pair；记录 expected outcome（QUARANTINED 也可为测试通过）。从当前策略建立可执行旧版本基线后再比较新策略；不能杜撰不存在的旧 policy_version。

边界：P1.6.2 只提供可验证的离线选择、恢复、审计及 promotion 决策；生产下载/worker 的强制 shadow/quarantine 接入属于 P1.6.3。当前 scope 不应承诺已经拦住生产不完整文档。

## 本轮交付与下一步

PHASE_0_STATUS = COMPLETE；ARCHITECTURE_IMPLEMENTATION = NOT_STARTED。

本轮新增本文，保留开始时所有历史脏文件。未运行全测试、未提交。上一次 2835 passed 是此前修复阶段结果，不计为 P1.6.2 验收。迁移源码与 tracked 文件存在所列 lineage，但本轮没有再次执行数据库 migration 测试。

下一步：确认上述增量架构后，首先实现 domain/inventory 与离线 audit runner，然后接入最小 adapters 和 corpus；在失败检测与旧基线明确之前，不扩展 parser 依赖或改生产 worker。
