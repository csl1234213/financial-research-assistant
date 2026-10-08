"""Report a complete, source-reviewed rerun without reusing earlier grades."""

import argparse
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def percentile(values, p):
    values = sorted(values)
    position = (len(values) - 1) * p / 100
    left = int(position)
    right = min(left + 1, len(values) - 1)
    return round(values[left] + (values[right] - values[left]) * (position - left), 2)


def apply_citation_override(support, rank, supported_ranks):
    """Keep unused retrieved evidence distinct from claims cited by the answer."""

    if support == "UNUSED_RETRIEVED_CONTEXT":
        return support
    return "VALID_SUPPORTED" if rank in supported_ranks else "VALID_BUT_NOT_SUPPORTED"


def scope_metrics(rows):
    grades = Counter(row["answer_grade"] for row in rows)
    valid = len(rows) - grades["FAILED"]
    latencies = [row["latency_ms"] for row in rows]
    cost = [row["estimated_cost_usd"] for row in rows if row["estimated_cost_usd"] is not None]
    return {
        "requested": len(rows),
        "grades": dict(grades),
        "valid_completed": valid,
        "correct_over_valid": round(grades["CORRECT"] / valid, 6) if valid else None,
        "strict_correct_over_requested": round(grades["CORRECT"] / len(rows), 6),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2),
            "min": min(latencies),
            "max": max(latencies),
            **{f"p{p}": percentile(latencies, p) for p in [50, 90, 95, 99]},
        },
        "known_list_price_cost_usd": round(sum(cost), 8),
        "full_list_price_cost_usd": round(sum(cost), 8) if len(cost) == len(rows) else None,
        "unknown_cost_queries": len(rows) - len(cost),
    }


def summarize(root):
    raw = read_rows(root / "evaluation_100_results.jsonl")
    expected = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    freeze = json.loads((root / "dataset_freeze.json").read_text(encoding="utf-8"))
    if len(raw) != 100 or len({r["id"] for r in raw}) != 100:
        raise ValueError("Exactly 100 unique real requests required")
    if Counter(r["language"] for r in raw) != {"en": 50, "zh": 50}:
        raise ValueError("Exactly 50 English and 50 Chinese requests required")
    if hashlib.sha256((root / "dataset.json").read_bytes()).hexdigest() != freeze["sha256"]:
        raise ValueError("Frozen dataset changed")
    expected = {r["id"]: r for r in expected}
    reviews = {r["id"]: r for r in read_rows(root / "semantic_reviews.jsonl")}
    manual_path = root / "retest_adjudications.json"
    manual = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path.exists() else {}
    corpus = json.loads((root / "reference_chunks.json").read_text(encoding="utf-8"))
    chunks = dict(zip(corpus["ids"], corpus["metadatas"]))
    citations = Counter()
    graded = []
    for row in raw:
        if any(
            row[field] != expected[row["id"]][field] for field in ["question", "expected_answer", "expected_sources"]
        ):
            raise ValueError("Question or expected criterion changed: " + row["id"])
        review = reviews.get(row["id"], {})
        grade = review.get("answer_grade", "UNKNOWN_REVIEW_FAILED")
        reason = review.get("reason", "No fresh review available")
        override = manual.get(row["id"])
        if override:
            if override["answer_sha256"] != hashlib.sha256(row["actual_answer"].encode()).hexdigest():
                raise ValueError("Adjudication belongs to a different answer")
            grade, reason = override["answer_grade"], override["reason"]
        if row["error"]:
            grade, reason = "FAILED", row["error"]
        assessed = {c["rank"]: c for c in review.get("citations", [])}
        citation_review = []
        for citation in row["citations"]:
            metadata = chunks.get(citation["chunk_id"], {})
            exists = metadata.get("source") == citation["source"] and metadata.get("page") == citation.get("page")
            item = assessed.get(citation["rank"], {})
            support = item.get("grade", "UNKNOWN_SUPPORT_NOT_REVIEWED")
            if review.get("answer_grade") == "UNKNOWN_REVIEW_FAILED":
                support = "UNKNOWN_SUPPORT_NOT_REVIEWED"
            if row["error"]:
                support = (
                    "UNUSED_RETRIEVED_CONTEXT"
                    if item.get("grade") == "UNUSED_RETRIEVED_CONTEXT"
                    else "VALID_BUT_NOT_SUPPORTED"
                )
            if override and "supported_citation_ranks" in override:
                support = apply_citation_override(
                    support, citation["rank"], override["supported_citation_ranks"]
                )
            if not exists:
                support = "INVALID_SOURCE"
            citations["total"] += 1
            citations["source_exists"] += int(exists)
            citations[support] += 1
            citation_review.append(
                {
                    **citation,
                    "source_exists": exists,
                    "support_grade": support,
                    "support_reason": override["reason"] if override else item.get("reason", "Not reviewed"),
                    "exact_quote_validation_failed": item.get("quote_validation_failed", False),
                }
            )
        graded.append(
            {
                **row,
                "answer_grade": grade,
                "grading_reason": reason,
                "failure_modes": (
                    override.get("failure_modes", review.get("failure_modes", []))
                    if override
                    else review.get("failure_modes", [])
                ),
                "review_method": "Fresh Codex source adjudication"
                if override
                else review.get("method", "Not reviewed"),
                "citation_review": citation_review,
            }
        )
    groups = {
        scope: scope_metrics([r for r in graded if scope == "all" or r["language"] == scope])
        for scope in ["all", "en", "zh"]
    }
    citation_total = citations["total"]
    with_citations = sum(bool(r["citations"]) for r in graded)
    with_support = sum(any(c["support_grade"] == "VALID_SUPPORTED" for c in r["citation_review"]) for r in graded)
    citation_rates = {
        "answers_with_citations": with_citations,
        "presence_over_all_requests": with_citations / 100,
        "structural_validity": citations["source_exists"] / citation_total if citation_total else None,
        "supported_over_total_citations": citations["VALID_SUPPORTED"] / citation_total if citation_total else None,
        "answers_with_at_least_one_supported_claim": with_support,
        "answer_level_support_over_all_requests": with_support / 100,
        "validity_scope": "Exact source/chunk/page existence only; company/period semantic fit assessed separately",
        "full_company_period_validity": "NOT_INDEPENDENTLY_VERIFIED",
        "answer_level_scope": (
            "At least one relevant material claim supported; not complete coverage of all conclusions"
        ),
    }
    full_cost = groups["all"]["full_list_price_cost_usd"]
    summary = {
        "conclusion": (
            "COMPLETE_100_REQUESTS; quality results are provisional source-assisted grades, not independent human gold"
        ),
        "run": root.name,
        "question_categories": dict(Counter(r["category"] for r in raw)),
        "requested_models": dict(Counter((r["response"].get("routing") or {}).get("model", "UNKNOWN") for r in raw)),
        "failure_injection": json.loads((root / "failure_injection.json").read_text(encoding="utf-8")),
        "configured_output_budget": 8192,
        "dataset_sha256": freeze["sha256"],
        "expected_answers_unchanged": True,
        "prior_answers_and_grades_not_reused": True,
        "groups": groups,
        "http_status_counts": dict(Counter(r["status_code"] for r in raw)),
        "business_errors": dict(Counter(r["error"] for r in raw if r["error"])),
        "direct_chat_routing_mismatches": [
            r["id"]
            for r in raw
            if r["category"] == "direct_chat"
            and ((r["response"].get("execution") or {}).get("strategy") != "direct_llm" or bool(r["citations"]))
        ],
        "citations": dict(citations),
        "citation_rates": citation_rates,
        "finish_length_queries": sum(
            any(c.get("finish_reason") == "length" for c in (r["response"].get("usage") or {}).get("calls", []))
            for r in raw
        ),
        "known_token_subtotals": {
            k: sum(r[k] or 0 for r in raw) for k in ["input_tokens", "output_tokens", "cached_tokens"]
        },
        "known_total_tokens": sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0) for r in raw),
        "token_queries_with_unknown_usage": sum(r["input_tokens"] is None or r["output_tokens"] is None for r in raw),
        "deterministic_zero_llm_call_queries": sum(
            (r["response"].get("usage") or {}).get("complete") is True
            and (r["response"].get("usage") or {}).get("calls") == []
            for r in raw
        ),
        "full_cost_100_usd": full_cost,
        "cost_per_query_usd": full_cost / 100 if full_cost is not None else None,
        "projection_1000_usd": full_cost * 10 if full_cost is not None else None,
        "projection_10000_usd": full_cost * 100 if full_cost is not None else None,
        "projection_assumption": (
            "Same model, published price window and observed input/output/cache mix; not invoice or SLA"
        ),
        "evaluator_usage_separate": {
            k: sum((r.get("evaluator_usage") or {}).get(k) or 0 for r in reviews.values())
            for k in ["input_tokens", "output_tokens", "cached_tokens"]
        },
        "evaluator_calls_with_unknown_usage": sum(r.get("evaluator_usage") is None for r in reviews.values()),
        "failure_modes": dict(
            Counter(mode for r in graded if r["answer_grade"] != "CORRECT" for mode in r["failure_modes"])
        ),
        "review_labels_all_questions": dict(Counter(mode for r in graded for mode in r["failure_modes"])),
        "fresh_reviews": len(reviews),
        "unknown_grades": sum(r["answer_grade"] == "UNKNOWN_REVIEW_FAILED" for r in graded),
        "no_provider_credentials_in_report": True,
        "full_http_failure_and_state_drill": "NOT_VERIFIED; prior seam injection evidence retained separately",
    }
    summary["average_known_tokens_per_all_requests"] = summary["known_total_tokens"] / 100
    summary["production_readiness"] = "FAIL_FOR_UNSUPERVISED_FINANCIAL_QA; baseline, not a deployment certification"
    by_id = {r["id"]: r for r in graded}
    summary["paired_grade_mismatches"] = [
        {
            "pair": number,
            "en_grade": by_id[f"EN-{number:03}"]["answer_grade"],
            "zh_grade": by_id[f"ZH-{number:03}"]["answer_grade"],
        }
        for number in range(1, 51)
        if by_id[f"EN-{number:03}"]["answer_grade"] != by_id[f"ZH-{number:03}"]["answer_grade"]
    ]
    (root / "evaluation_100_graded.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in graded), encoding="utf-8"
    )
    (root / "evaluation_100_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (root / "report.md").write_text(report_text(graded, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def report_text(rows, summary):
    sections = [
        "# Financial RAG — 8192 输出预算 / 100 题真实复测",
        "## 1. Executive Summary",
        "本轮单独执行相同冻结题库 100 次真实 API 请求，中英文各 50，未用新回答替换历史失败记录。",
        "运行完成不等于质量通过。语义评分为同 Provider 源 PDF 约束评审及显式 Codex 裁决，不是独立人工金标准。",
        f"Strict Accuracy {summary['groups']['all']['strict_correct_over_requested']:.2%}；"
        f"P95 {summary['groups']['all']['latency_ms']['p95']}ms；Cost100 ${summary['full_cost_100_usd']}。",
        "## 2. Environment",
        "canonical D 盘仓库；financial-rag-prod 六服务；health 版本 8.2.0。只调整预算和 Compose 透传。",
        "backend/worker 运行时 LLM_MAX_TOKENS=8192；同一基线镜像、模型、Retriever、Prompt、公开文档和题库。",
        "2026-09-14；HEAD ccdec23b490b5064b6e2ac8742ed33f25115700f，含未提交修改；运行镜像8.2.0。",
        "Embedding intfloat/multilingual-e5-small，revision614241f622f53c4eeff9890bdc4f31cfecc418b3；",
        "Hybrid Vector+BM25、RRF k=60、权重1:1、candidate multiplier4、每公司Top-K4；PostgreSQL+Redis+Chroma。",
        "普通套餐及安全限流不关闭，仅原独立评测工作空间允许 1000 chats/day。",
        "## 3. Dataset / methodology",
        f"冻结 SHA-256：`{summary['dataset_sha256']}`。100 个唯一 ID，50EN/50ZH；逐题核对未更改 expected criteria。",
        "先执行独立 5 题 Smoke：5 个非空正文，finish_reason 全为 stop，链路门禁通过后执行正式请求。",
        "每批 5 题，串行真实 HTTP；8 个多轮 setup 与 Smoke 单独记录，不混入主样本。",
        f"问题类别分布：{summary['question_categories']}。原题、标准、公司、来源保存在 dataset.json。",
        "语义评审调用与主请求分别记录，评审在另一进程执行；主查询延迟仍为实际 HTTP 完整返回时间。",
        "评审与主请求共享Provider账户，可能影响并发/吞吐；未单独instrument retrieval/LLM spans，不虚构延迟分解。",
        "## 4. Answer grades",
        "| Scope | Requested | Correct | Partial | Incorrect | Failed | Unknown | Correct/valid | Strict correct |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scope, m in summary["groups"].items():
        g = m["grades"]
        accuracy = f"{m['correct_over_valid']:.2%}" if m["correct_over_valid"] is not None else "UNKNOWN"
        sections.append(
            f"| {scope} | {m['requested']} | {g.get('CORRECT', 0)} | {g.get('PARTIAL', 0)} "
            f"| {g.get('INCORRECT', 0)} | {g.get('FAILED', 0)} | {g.get('UNKNOWN_REVIEW_FAILED', 0)} "
            f"| {accuracy} | {m['strict_correct_over_requested']:.2%} |"
        )
    c = summary["citations"]
    sections.extend(
        [
            "Valid completed 仅排除 FAILED；未知裁决仍公开并保守保留于分母。Strict correct 包含全部请求。",
            f"中英文对应题评分不同 {len(summary['paired_grade_mismatches'])}/50 对；"
            "差异记录于summary，不将单次随机生成差异全部归因于翻译。",
            "## 5. Citations / source truth",
            f"Source/chunk/page 存在校验：{c.get('source_exists', 0)}/{c.get('total', 0)}。",
            f"语义支持：{c.get('VALID_SUPPORTED', 0)}；真实但不支持：{c.get('VALID_BUT_NOT_SUPPORTED', 0)}；"
            f"未被回答引用的检索上下文：{c.get('UNUSED_RETRIEVED_CONTEXT', '未按新口径单独统计')}；"
            f"评审标注不可验证：{c.get('REVIEW_INDETERMINATE', 0)}；"
            f"无效：{c.get('INVALID_SOURCE', 0)}；未知支持：{c.get('UNKNOWN_SUPPORT_NOT_REVIEWED', 0)}。",
            "存在率不等于问题/公司/季度匹配。逐引用理由在 graded JSONL；辅助支持引文进行 exact-substring 校验。",
            "好例：EN-008 正确引用NVIDIA数据中心$75.2bn；坏例：EN-007只召回Q2指引却否认Q1实绩。",
            "坏例：ZH-044‘什么叫毛利率’误走RAG，引用Apple报表并拒绝给出通用定义。",
            f"Citation presence（全部100请求）：{summary['citation_rates']['presence_over_all_requests']:.2%}；"
            f"支持率（全部引用）：{summary['citation_rates']['supported_over_total_citations']:.2%}。",
            f"至少一个相关主张获支持的回答：{summary['citation_rates']['answers_with_at_least_one_supported_claim']}/100；"
            "不等于全部结论均获支持。",
            "Tesla_Q2_2025.pdf 实际为 Q4/FY2025，只有历史 Q2 表格；不可把 Q4 YoY 当作 Q2 YoY。",
            "Apple Q2 FY2026 收入111,184m/净利润29,578m/EPS2.01；NVIDIA Q1 FY2027 收入81.6bn/Data Center75.2bn。",
            "## 6. E2E latency (ms)",
            "| Scope | Mean | P50 | P90 | P95 | P99 | Min | Max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scope, m in summary["groups"].items():
        sections.append(
            "| "
            + scope
            + " | "
            + " | ".join(str(m["latency_ms"][k]) for k in ["mean", "p50", "p90", "p95", "p99", "min", "max"])
            + " |"
        )
    sections.extend(
        [
            "线性插值分位数；包含失败，不把快速 fallback 解释为 RAG 性能提升。单次实验不是 SLA。",
            "## 7. Tokens / cost",
            f"实测已知 token 小计：{summary['known_token_subtotals']}；缺失 usage 不按零处理。",
            f"已知总 token {summary['known_total_tokens']}；"
            f"每请求平均 {summary['average_known_tokens_per_all_requests']}；"
            f"usage 未知题数 {summary['token_queries_with_unknown_usage']}。",
            f"确定性零LLM调用题数 {summary['deterministic_zero_llm_call_queries']}；"
            "这些不是SDK返回过零token的调用，不计模型调用次数。",
            f"应用 Cost100 公开价估算（USD）：{summary['full_cost_100_usd']}；"
            f"per-query：{summary['cost_per_query_usd']}。",
            f"同配置/价格时段/token与缓存分布假设：1k queries ${summary['projection_1000_usd']}；"
            f"10k queries ${summary['projection_10000_usd']}。不是实际账单或商业保证。",
            "请求模型 deepseek-v4-flash；实际 served model 在每题 usage.calls 记录。",
            "[DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：",
            "Flash 工作日 UTC01–04/06–10 每百万 cached/uncached/output tokens 为 $0.006/$0.30/$1.20，非高峰减半。",
            f"辅助 evaluator 用量单独记录，不计应用 Cost100：{summary['evaluator_usage_separate']}。",
            f"辅助评审usage缺失调用 {summary['evaluator_calls_with_unknown_usage']}；"
            "该小计不代表完整评审token或成本，也未将缺失调用按零收费。",
            "## 8. Failure & degradation testing",
            "本轮重跑真实 SDK/adapter 的隔离 HTTP MockTransport 注入，而非向真实 Provider 发故障请求：",
            "429：3 attempts/2 retries，遵守注入的 Retry-After，但短 Retry-After 会取代指数退避，评级 PARTIAL。",
            "503：9 attempts/8 retries，SDK 与 adapter 嵌套，超出目标单层3次总尝试，评级 FAIL。",
            "Timeout：3 attempts/2 retries，有SDK指数退避及jitter，未验证完整HTTP用户体验，评级 PARTIAL。",
            "Chroma：Retriever seam 异常传播、未编造证据；HTTP错误与state恢复未验证，评级 PARTIAL。",
            "Redis：cache miss安全并能恢复，broker禁用后DB polling fallback；"
            "实际worker/state恢复未验证，评级 PARTIAL。",
            "[本轮故障注入原始记录](failure_injection.json)。未停服务、未删Volume，注入样本不计正常100题分母。",
            "上一轮 retry 候选修改的单层3次、指数退避/jitter证据仍保留，但本轮基线镜像尚未包含该修复。",
            "## 9. Failure analysis",
            f"真实 HTTP 状态：{summary['http_status_counts']}；业务错误：{summary['business_errors']}。",
            f"finish_reason=length：{summary['finish_length_queries']}；语义失败标签：{summary['failure_modes']}。",
            f"概念/闲聊Direct Chat路由或引用违约：{summary['direct_chat_routing_mismatches']}。",
            "失败标签只计非CORRECT题；比例分母仍为全部100题，标签可重叠。正确缺失来源拒答不算质量失败。",
            "所有失败保留，不修改 expected、不删除错误回答，不用 citation presence 替代语义质量。",
            "这些是 dependency-seam 仿真，不是本轮真实停机或完整 HTTP state-integrity 验证。",
            "本轮不删 Volume、不覆盖数据库；未部署上轮候选 retry 修复，避免混入预算对照实验。",
            "## 10. Production readiness / validation",
            "质量评级：FAIL（不适合无人监督的金融问答）；完成100请求仅说明样本完整，不等于生产认证。",
            "4096 时同两题模型正文为空、finish=length；8192 时 5 题 Smoke 均非空、finish=stop。",
            "历史100题曾受余额不足影响，因此不能把历史/本轮准确率变化全部归因于输出预算。",
            "Compose 预算透传回归：修改前2失败，修改后2通过；全局默认仍4096，本地显式8192。",
            "此前相关294测试+4报告安全测试、前端31测试与build通过；"
            "完整 credential-free suite 曾600秒超时，不宣称通过。",
            "本轮最终检查记录在 validation.json；未自动 stage、commit、push。",
            "## 11. Priority fixes",
            "P0：源文件期间标签校验、季度表格召回、核心结论与引用的公司/期间/数值一致性校验。",
            "P0：中文概念问答与财报研究意图区分，避免‘什么叫毛利率’被财务关键词强制推入RAG。",
            "P1：多轮主题/公司继承；部署并重测已存在的单层 retry 候选修复（当前503实测9 attempts）。",
            "P2：独立专家抽审与完整HTTP故障恢复/state integrity验证；建立事前约定的质量门禁。",
            "## 12. Conclusion",
            "适合作为透明展示工程链路和真实质量差距的 Portfolio；只能选已验证答案做监督式Demo。",
            "不建议无人监督公网金融咨询。预算调整只解决链路空正文，不保证召回及财务推理准确。",
            f"正式100请求完成；未知裁决 {summary['unknown_grades']}。"
            "质量状态以逐题结果为准，不因 HTTP 200 自动判 PASS。",
            "## Appendix — Per-question evidence",
            "[Raw](evaluation_100_results.jsonl), [graded](evaluation_100_graded.jsonl), "
            "[summary](evaluation_100_summary.json),",
            "[fresh semantic reviews](semantic_reviews.jsonl), [Smoke](smoke_results.jsonl), "
            "[provenance](retest_manifest.json)。",
            "| ID | Question | Grade | HTTP | ms | Reason |",
            "|---|---|---|---:|---:|---|",
        ]
    )

    def clean(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    for r in rows:
        sections.append(
            f"| {r['id']} | {clean(r['question'])} | {r['answer_grade']} | {r['status_code']} "
            f"| {r['latency_ms']} | {clean(r['grading_reason'])} |"
        )
    lines = []
    for section in sections:
        if section.startswith("#"):
            lines.extend(["", section, ""])
        elif section.startswith("|"):
            lines.append(section)
        else:
            if lines and lines[-1].startswith("|"):
                lines.append("")
            lines.extend([section, ""])
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    summarize(parser.parse_args().root)
