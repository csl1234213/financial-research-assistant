"""Derive an honest report without changing frozen labels or raw responses.

Manual source adjudications below are explicit, auditable overrides, not new
golden answers. No provider calls are made by this command.
"""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from evaluation.live_100 import response_failure

APPROVED_DATASET_SHA256 = "9a6768b98d3f2faf27ca872150bf60e2ee22a063d2610f2e80197f8d58f04fbb"

ADJUDICATIONS = {
    "EN-005": (
        "PARTIAL",
        "Q2 figures and full-year caveat are correct, but the final risk says QoQ cannot be calculated. "
        "The same table contains Q1-2025 and Q2-2025; this claim is false.",
        None,
    ),
    "EN-006": (
        "PARTIAL",
        "Q4-2025 declines are explicitly labelled Q4, not Q2 as the assisted reviewer claimed. "
        "However, Q4/FY2025 risk disclosures are not clearly distinguished from the requested Q2 report.",
        None,
    ),
    "EN-007": (
        "INCORRECT",
        "Refuses Q1 FY2027 results although the verified PDF contains revenue $81.6bn and Data Center $75.2bn. "
        "Q2 guidance does not support the requested Q1 results.",
        [],
    ),
    "EN-037": (
        "PARTIAL",
        "Apple net sales 111,184 and 17% growth match page 18, but the financial summary omits available "
        "net income 29,578 and diluted EPS 2.01; dollar figures lack an explicit million-unit label.",
        [2, 4],
    ),
    "ZH-002": (
        "CORRECT",
        "Q2 Tesla revenue 22,496m and components match the page-4 table. "
        "QoQ 16.3% and missing Q2-2024 YoY baseline are correctly distinguished.",
        [2],
    ),
    "ZH-004": (
        "CORRECT",
        "Tesla Q2 GAAP margin 17.2%, gross profit 3,878m and revenue 22,496m match page 4; Q4 YoY is not misused.",
        [1],
    ),
    "ZH-005": (
        "CORRECT",
        "Q2 production 410,244, deliveries 384,122, storage 9.6GWh and financial figures match tables. "
        "Robotaxi/Cybercab narrative is explicitly full-year, not attributed to Q2.",
        [1, 2, 3, 4],
    ),
    "ZH-006": (
        "CORRECT",
        "Qualified refusal: retrieved operational/full-year passages do not establish Q2-specific risk disclosures. "
        "The Q4 figures are labelled Q4; no fabricated Q2 risks.",
        [],
    ),
    "ZH-007": (
        "CORRECT",
        "Q1 NVIDIA revenue 81,615m, Data Center 75.2bn, GAAP margin 74.9%, GAAP EPS 2.39 "
        "and non-GAAP EPS 1.87 match the filing; Q2 outlook is labelled forward-looking.",
        [1, 2],
    ),
    "ZH-008": (
        "CORRECT",
        "Q1 Data Center 75.2bn (+92% YoY), compute 60.4bn and networking 14.8bn match the filing and sum correctly.",
        [1, 2],
    ),
    "ZH-009": (
        "PARTIAL",
        "Revenue and segment figures are correct, but the answer omits the filing's explicit "
        "AI-factory/agentic-AI demand explanation of growth and substitutes an overcautious refusal.",
        [2, 4],
    ),
    "ZH-010": (
        "CORRECT",
        "Q1 margins 74.9%/75.0% and comparisons to 75.0%/60.5% are correct; Q2 guidance is clearly separated.",
        [1, 4],
    ),
    "ZH-011": (
        "INCORRECT",
        "Refuses other business segments, but the verified filing explicitly reports Edge Computing "
        "revenue $6.4bn (+29% YoY) and the Data Center/Edge Computing market platforms.",
        [1],
    ),
    "ZH-012": (
        "CORRECT",
        "China-excluded Q2 outlook, tax exclusions and forward-looking supply/inventory risks match the source. "
        "Does not claim a complete risk-factor catalogue.",
        [1, 2, 4],
    ),
    "ZH-013": (
        "INCORRECT",
        "Claims no overall sales, net income or EPS are provided; the full PDF page 4 contains "
        "111,184m, 29,578m and 2.01 respectively. Retrieval omitted the relevant table.",
        [],
    ),
    "ZH-014": (
        "INCORRECT",
        "Refuses total revenue/growth despite page-18 total sales 111,184m and 17% YoY being available. "
        "Main model answer is also truncated mid-sentence.",
        [],
    ),
    "ZH-033": (
        "PARTIAL",
        "Correctly refuses absent Microsoft/Azure data without irrelevant citations, "
        "but returns English rather than the requested Chinese.",
        [],
    ),
    "ZH-034": (
        "PARTIAL",
        "Correctly refuses absent Alibaba financials without invented figures, "
        "but returns English rather than the requested Chinese.",
        [],
    ),
}


def load_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def percentile(values, p):
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return round(ordered[left] + (ordered[right] - ordered[left]) * (position - left), 2)


def unused_context_count_text(citation_counts):
    """Do not misreport old citation ledgers as having zero unused context."""

    count = citation_counts.get("UNUSED_RETRIEVED_CONTEXT")
    return str(count) if count is not None else "未按新口径单独统计"


def metrics(rows):
    grades = Counter(row["answer_grade"] for row in rows)
    valid = len(rows) - grades["FAILED"]
    times = [row["latency_ms"] for row in rows]
    return {
        "requested": len(rows),
        "http_200": sum(row["status_code"] == 200 for row in rows),
        "grades": dict(grades),
        "valid_completed": valid,
        "accuracy_valid_completed": round(grades["CORRECT"] / valid, 4) if valid else None,
        "strict_correct_over_requested": round(grades["CORRECT"] / len(rows), 4),
        "latency_ms": {
            "mean": round(statistics.mean(times), 2),
            "min": min(times),
            "max": max(times),
            **{f"p{p}": percentile(times, p) for p in [50, 90, 95, 99]},
        },
    }


def finalize(root):
    raw = load_rows(root / "evaluation_100_results.jsonl")
    dataset = json.loads((root / "dataset.json").read_text())
    freeze = json.loads((root / "dataset_freeze.json").read_text())
    if len(raw) != 100 or len({row["id"] for row in raw}) != 100:
        raise ValueError("Complete unique 100 real requests required")
    if hashlib.sha256((root / "dataset.json").read_bytes()).hexdigest() != freeze["sha256"]:
        raise ValueError("Frozen dataset checksum mismatch")
    if freeze["sha256"] != APPROVED_DATASET_SHA256:
        raise ValueError("Source adjudications apply only to the explicitly reviewed frozen dataset")
    by_id = {row["id"]: row for row in dataset}
    reviews = {row["id"]: row for row in load_rows(root / "semantic_reviews.jsonl")}
    corpus = json.loads((root / "reference_chunks.json").read_text())
    chunks = dict(zip(corpus["ids"], corpus["metadatas"]))
    finalized = []
    citation_counts = Counter({"total": 0, "source_exists": 0})
    for row in raw:
        if any(row[field] != by_id[row["id"]][field] for field in ["question", "expected_answer", "expected_sources"]):
            raise ValueError("Raw request criteria differ from frozen dataset")
        review = reviews.get(row["id"], {})
        failure = row["error"] or response_failure(row["status_code"], row["response"])
        grade, reason = review.get("answer_grade", "UNKNOWN_REVIEW_FAILED"), review.get("reason")
        manual = ADJUDICATIONS.get(row["id"])
        if manual:
            grade, reason = manual[:2]
        if failure:
            grade, reason = "FAILED", failure
        if grade == "UNKNOWN_REVIEW_FAILED":
            raise ValueError("Unadjudicated question: " + row["id"])
        citations = []
        reviewed_citations = {c["rank"]: c for c in review.get("citations", [])}
        for c in row["citations"]:
            meta = chunks.get(c["chunk_id"], {})
            exists = meta.get("source") == c["source"] and meta.get("page") == c.get("page")
            assessed = reviewed_citations.get(c["rank"], {})
            support = assessed.get("grade", "UNKNOWN_NOT_ADJUDICATED")
            support_reason = assessed.get("reason", "Not semantically adjudicated")
            if manual and manual[2] is not None and support != "UNUSED_RETRIEVED_CONTEXT":
                support = "VALID_SUPPORTED" if c["rank"] in manual[2] else "VALID_BUT_NOT_SUPPORTED"
                support_reason = "Codex source adjudication: " + manual[1]
            if failure:
                if support != "UNUSED_RETRIEVED_CONTEXT":
                    support = "VALID_BUT_NOT_SUPPORTED"
                support_reason = "No usable main model answer; no answer claim to assess"
            if not exists:
                support, support_reason = "INVALID_SOURCE", "Chunk/source/page mismatch"
            citation_counts[support] += 1
            citation_counts["total"] += 1
            citation_counts["source_exists"] += int(exists)
            citations.append(
                {
                    **c,
                    "source_exists": exists,
                    "support_grade": support,
                    "support_reason": support_reason,
                    "method": "Codex source adjudication" if manual and manual[2] is not None else review.get("method"),
                }
            )
        finalized.append(
            {
                **row,
                "raw_error": row["error"],
                "effective_error": failure,
                "answer_grade": grade,
                "grading_reason": reason,
                "review_method": "Codex source adjudication"
                if manual
                else review.get("method", "deterministic business failure"),
                "citation_review": citations,
            }
        )
    (root / "adjudications.json").write_text(json.dumps(ADJUDICATIONS, indent=2), encoding="utf-8")
    (root / "evaluation_100_graded.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in finalized), encoding="utf-8"
    )
    known_costs = [r["estimated_cost_usd"] for r in finalized if r["estimated_cost_usd"] is not None]
    summary = {
        "conclusion": "PARTIAL; complete 100-request execution, quality gate FAIL; "
        "further paid verification BLOCKED_PROVIDER_402",
        "dataset_sha256": freeze["sha256"],
        "expected_answers_unchanged": True,
        "groups": {
            group: metrics([r for r in finalized if group == "all" or r["language"] == group])
            for group in ["all", "en", "zh"]
        },
        "errors": dict(Counter(r["effective_error"] for r in finalized if r["effective_error"])),
        "citations": dict(citation_counts),
        "cost": {
            "known_usage_queries": len(known_costs),
            "unknown_usage_queries": 100 - len(known_costs),
            "known_cost_subtotal_usd": round(sum(known_costs), 8),
            "full_cost_100_usd": None,
            "full_cost_per_query_usd": None,
            "projected_cost_1000_usd": None,
            "projected_cost_10000_usd": None,
            "known_no_llm_call_queries": sum(
                bool((r["response"].get("usage") or {}).get("complete"))
                and not (r["response"].get("usage") or {}).get("calls")
                for r in finalized
            ),
        },
        "tokens_known_subtotal": {
            key: sum(r[key] or 0 for r in finalized) for key in ["input_tokens", "output_tokens", "cached_tokens"]
        },
        "model_finish_length": sum(
            any(c.get("finish_reason") == "length" for c in (r["response"].get("usage") or {}).get("calls", []))
            for r in finalized
        ),
        "evaluator_usage_separate": {
            key: sum((r.get("evaluator_usage") or {}).get(key) or 0 for r in reviews.values())
            for key in ["input_tokens", "output_tokens", "cached_tokens"]
        },
        "review_limitations": "Same-provider assisted review for available answers; explicit Codex overrides; "
        "not independent human gold-standard accuracy.",
        "real_provider_probe_http_status": 402,
        "fault_injection_full_http_state": "NOT_VERIFIED",
    }
    (root / "evaluation_100_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = make_report(finalized, summary)
    (root / "report.md").write_text(
        report.replace("../evaluation/results/formal_20260914_postfix", "."), encoding="utf-8"
    )
    (root.parent / (root.name + "-docs-report.md")).write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))


def make_report(rows, summary):
    table = (
        "| Scope | Requests | Valid completed | Correct | Partial | Incorrect | Failed | "
        "Correct/valid | Strict correct |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    latency = "| Scope | Mean | P50 | P90 | P95 | P99 | Min | Max |\n|---|---:|---:|---:|---:|---:|---:|---:|\n"
    for scope, m in summary["groups"].items():
        g = m["grades"]
        table += (
            f"| {scope} | {m['requested']} | {m['valid_completed']} | {g.get('CORRECT', 0)} | {g.get('PARTIAL', 0)} "
            f"| {g.get('INCORRECT', 0)} | {g.get('FAILED', 0)} | {m['accuracy_valid_completed']:.2%} "
            f"| {m['strict_correct_over_requested']:.2%} |\n"
        )
        t = m["latency_ms"]
        latency += (
            f"| {scope} | " + " | ".join(str(t[k]) for k in ["mean", "p50", "p90", "p95", "p99", "min", "max"]) + " |\n"
        )
    per_question = "| ID | Question | Grade | HTTP | ms | Reason |\n|---|---|---|---:|---:|---|\n"
    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    for row in rows:
        per_question += (
            f"| {row['id']} | {clean(row['question'])} | {row['answer_grade']} | {row['status_code']} "
            f"| {row['latency_ms']} | {clean(row['grading_reason'])} |\n"
        )
    c = summary["citations"]
    unused_context_text = unused_context_count_text(c)
    return f"""# Financial RAG — 100 题正式执行与质量评测

## 1. Executive Summary

2026-09-14：**100/100 真实 authenticated HTTP 请求已执行，中英文各 50。最终 PARTIAL，质量门禁 FAIL。**
五题修复后 Smoke 通过的是运行链路/路由门禁，不是语义全正确门禁。HTTP 200 不等于成功。
DeepSeek 实测返回 **HTTP 402（余额不足）**。ZH-015 至 ZH-050 中，除 ZH-033/034 正确缺失来源拒答外，
其余返回 Runtime Fallback，仍被 HTTP 200 包装；fallback 全部计 FAILED。
停止进一步收费调用；未伪造、过滤或重跑替换失败样本。不能宣称“100 题全部成功”或“生产质量通过”。

## 2. Environment / reproducibility

仓库：D 盘 canonical financial-rag-assistant；main，部署含未提交修改。
基线 HEAD `ccdec23b490b5064b6e2ac8742ed33f25115700f`。
运行版本 health=8.2.0，历史任务名 8.1.0；Docker financial-rag-prod，六服务 healthy，health/ready HTTP 200。
真实 POST `/api/v1/chat`，真实登录、JWT 保护接口和 tenant identity 检查；没有使用 mock 回答。
仅独立评测租户 4 的套餐允许 1,000 chats/day；普通租户、Free plan、全局安全限流未关闭。
100 个主请求之外，Smoke 和 8 个多轮 setup 单独存档，不混入耗时/成本主样本。
每题无 harness 自动重试；SDK/adapter 内部重试未在主查询逐次追踪，不能声称主查询 retry=0。

## 3. Frozen dataset / source truth

50EN + 50ZH 复用既有题库，包含单公司、比较、缺失数据、改写、闲聊、多轮和对抗问题。
请求前冻结 expected criteria，SHA-256 `{summary["dataset_sha256"]}`。
唯一冻结修订是根据真实 manifest 修正 NVIDIA 文件名中的 FY，发生在修复后请求之前；答案标准没有依据实际回答改写。
3 份公开财报的原 PDF hash 匹配公共 Chroma 元数据；303 公共 chunks 单独冻结，无私人财报/凭据导出。
Tesla source 标签 `Tesla_Q2_2025.pdf` 实际内容是 Q4/FY2025 Update，含历史 Q2 表格；必须区分季度、全文叙述和 YoY。
Apple Q2 FY2026：111,184m 收入、29,578m 净利润、EPS 2.01；NVIDIA Q1 FY2027：81.6bn 收入、75.2bn 数据中心。
完整来源 hash/page 数见 [reference manifest](../evaluation/results/formal_20260914_postfix/reference_manifest.json)。

## 4. Answer accuracy / grading

{table}

Valid completed 排除真实失败；PARTIAL/INCORRECT 仍属于可评阅回答。Strict correct 按全部请求计，不剔除失败。
采用相同 provider 的源 PDF 约束辅助评审及 exact-quote 校验，另有显式 Codex 源证据裁决；**不是独立人工金标准结果**。
402 导致辅助评审缺失的中文前 14 题及 EN-037 使用源 PDF 人工式 Codex 裁决；失败样本采用确定性判断。
原辅助评审及所有覆盖理由分别保留，不覆盖 raw answers 或 expected criteria。存在评审偏差，建议后续独立专家复核。

## 5. Citation quality

返回引用总数 {c["total"]}；chunk/source/page 确定性存在校验 {c["source_exists"]}/{c["total"]}。
语义支持 {c.get("VALID_SUPPORTED", 0)}；
有效来源但不支持当前主回答 {c.get("VALID_BUT_NOT_SUPPORTED", 0)}；无效来源 {c.get("INVALID_SOURCE", 0)}。
评审标注不可验证 {c.get("REVIEW_INDETERMINATE", 0)}。
未被回答引用的有效检索上下文 {unused_context_text}。历史数据未按此类别重标。
来源存在率不能当作语义支持率。Tesla 文件标签与实际期间不一致，即使 chunk 存在也不能直接证明季度正确。
相同 provider 评审的支持引文必须是原 chunk 与主答案的准确子串；quote 校验失败会保守降级，存在假阴性。
Codex 裁决另记录方法与具体金额/期间理由。逐引用 source/page/chunk、支持状态及理由保留在 graded JSONL。
EN-007：引用了真实 NVIDIA Q2 guidance，但无法支撑所问 Q1 实绩；Apple 部分问题只有标题/说明片段，不能支撑收入。

## 6. End-to-end latency

单位 ms；HTTP 请求发出至完整 response 返回，包含后端全流程，不以页面标签替代。线性插值分位数。

{latency}

整体统计包含失败；中文后半段快速 fallback 会人为降低均值，不代表 RAG 加速。100 题总样本与语言分组均保留。

## 7. Tokens / model / cost

请求模型 `deepseek-v4-flash`，SDK 实际 served model 为 `deepseek-flash`。价格依据当天 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)。
Flash 高峰（工作日 UTC 01–04/06–10）每百万 token：cached input $0.006、uncached input $0.30、output $1.20；非高峰减半。
应用 100 次主请求中 {summary["cost"]["known_usage_queries"]} 次有完整 actual provider usage；
{summary["cost"]["unknown_usage_queries"]} 次 usage UNKNOWN。
其中 {summary["cost"]["known_no_llm_call_queries"]} 次为可确认没有 LLM 调用的确定性拒答，已知零调用，
不冒充 SDK 返回过零 token 的 usage。
已知 token 小计：input {summary["tokens_known_subtotal"]["input_tokens"]}、
output {summary["tokens_known_subtotal"]["output_tokens"]}、cached {summary["tokens_known_subtotal"]["cached_tokens"]}。
已知请求按时段/缓存实测计算的价格小计 **${summary["cost"]["known_cost_subtotal_usd"]:.8f}**。
这是公开价估算，不是发票核验。
Cost100、全量 per-query、1k/10k projections 均 **UNKNOWN**，不把缺失 usage 当零。
辅助评审用量单独记录：{summary["evaluator_usage_separate"]}；不计入应用 Cost100，也不宣称评审成本为零。
主查询 finish_reason=length 共 {summary["model_finish_length"]}，4096 输出预算下有空正文与截断。
[官方 thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/) 的推理内容与普通正文不同。
本轮没有改变主查询模型/推理设置来美化基线。

## 8. Failure analysis — top five

1. Provider 402 被 HTTP 200 fallback 包装：ZH-015–050（除 033/034）。
区分真实余额失败、套餐与安全限流，不得通过调大套餐虚报修复。
2. 输出预算耗尽：EN-001/023、ZH-001/003 没有可用主回答；多题 finish length。应另做受控预算/推理配置回归。
3. 检索召回错误片段：EN-007、ZH-013/014 原 PDF 有数据却拒答；需财务表格检索和 period-aware rerank。
4. 数据/期间标签：Tesla Q2 名称对应 Q4/FY2025；部分问答把 available evidence 与实际 PDF 混淆，需要入库元数据校验。
5. 多轮与引用语义：EN-045–048 follow-up 丢失财报检索/来源；引用存在不代表对问题有支持，必须独立复核。

这些问题是测出的质量缺陷，不通过改 expected labels、skip 或 mock success 掩盖。

## 9. Fault injection / before-after

隔离 MockTransport 注入真实 SDK/adapter 的 429、503、timeout；真实 Retriever/Cache/Broker 类注入 Chroma/Redis 异常。
这是**依赖边界仿真，不是生产六服务真实停机演练或完整 HTTP conversation-state 验收**。
Before：503 9 次网络尝试；timeout 错分普通 ProviderError；429 SDK 自有 3 次尝试。
After：取消 SDK 隐式重试，由适配器统一最多 3 次，指数 backoff+jitter，Retry-After 为等待下限。
超长等待 fail closed，安全错误消息不含上游 body。
超时最终 ProviderConnectionError；503 ProviderError；429 RateLimitError。故障测试不调用真实 provider，不污染生产数据。
Chroma 故障不生成假证据；Redis cache 可安全 miss 并恢复；broker DB polling fallback 标志有效。
实际 worker DB polling、完整恢复后会话污染检查、HTTP Retry-After 暴露 **NOT_VERIFIED**。
Before/After artifacts 分开保存，不覆盖。重试修复发生在 100 题结束后，未混入基线。
重试修复仅在隔离源码 fixture 回归验证；当前 Docker 镜像仍为评测基线，尚未重新构建部署该修复。

## 10. Fixes / regression validation

最小路由修复：general concepts 优先闲聊；中英文公司业务表现及股票/改写别名正确识别。
17 个新增路由回归修复前 12 failed/5 passed，修复后规划/执行回归通过；benchmark 断言未修改。
新增请求隔离的 provider 实际 usage 采集及兼容 optional response usage，无 prompt/key/header 记录。
评测工具新增 HTTP-200 Runtime Fallback 识别，生成 derived effective_error，原始结果完全保留。
最新测试、Ruff、diff-check 结果见 [validation](../evaluation/results/formal_20260914_postfix/validation.json)。
完整 credential-free suite 的完成情况如实记录。
没有更改 Retriever/Prompt/Corpus 来提高本次分数；没有 stage/commit/push，也没有删除数据或 Volume。

## 11. Per-question results / artifacts

raw request/response：[100 real responses](../evaluation/results/formal_20260914_postfix/evaluation_100_results.jsonl)。
逐题与逐引用裁决：[graded JSONL](../evaluation/results/formal_20260914_postfix/evaluation_100_graded.jsonl)。
指标：[summary JSON](../evaluation/results/formal_20260914_postfix/evaluation_100_summary.json)。
原辅助裁决与 Codex 覆盖、setup、Smoke、source manifest、dataset freeze 一并存档。

{per_question}

## 12. Action plan / final gate

P0：人工补足 provider 余额后再做受控回归；保留本次基线，不替换失败记录。API 应给出可观察的业务错误而非 HTTP 200 假成功。
P1：校验 PDF 年度/季度元数据与财务表格召回，测试 source-aware multilingual retrieval、单位/期间约束和多轮上下文。
P1：受控验证 max output/推理 budget，确保正文完整，不能把生成截断归因“证据不足”。
P2：独立 evaluator/专家抽审，完整 HTTP 故障与恢复、state integrity 和真实成本账单核验。
**FINAL：PARTIAL。100-request execution COMPLETE；answer-quality gate FAIL。**
**New paid verification BLOCKED_PROVIDER_HTTP_402。**
本地及生产持久数据未删除。Secret scan、health、服务状态与 Git 记录见 validation；不提交凭据。
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    finalize(parser.parse_args().root)
