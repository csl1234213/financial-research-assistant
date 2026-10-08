# How I Designed the Context Builder in a Financial RAG System

# 我是如何设计金融 RAG 系统中的 Context Builder

**Version / 版本：V2.2 Stable**

---

## Introduction / 项目背景

In most RAG systems, developers focus heavily on retrieval and model selection.

在大多数 RAG 系统中，开发者往往更关注检索算法和模型选择。

However, during this project, I found that the real bottleneck was not retrieval or LLM capability.

但在这个项目中，我逐渐发现真正的瓶颈并不是检索能力或大模型能力。

It was how context is constructed before being sent to the model.

而是“如何构建输入给模型的上下文”。

---

## The Initial Problem / 初始问题

The early version of the system directly passed retrieved chunks into the LLM.

早期版本是直接把检索到的 chunks 传给模型。

The pipeline looked like this:

流程如下：

```text id="x9k2mp"
Query
   ↓
Retriever
   ↓
Top-K Chunks
   ↓
LLM
   ↓
Answer
```

At first, this worked reasonably well.

在最初阶段，这种方式是有效的。

But as the system grew, problems started to appear.

但随着系统扩展，问题逐渐出现：

* Redundant information
* Inconsistent formatting
* Context overflow
* Hallucination in multi-document scenarios

---

## Core Issue / 核心问题

The main issue was not retrieval quality.

核心问题并不是检索质量。

It was that raw chunks are not usable as model context.

而是原始 chunk 并不适合作为模型上下文输入。

Chunks are:

chunk 的问题在于：

* Unstructured
* Redundant
* Not ranked semantically
* Lacking explicit relationships

LLMs require structured, prioritized context.

而大模型需要结构化、有优先级的上下文。

---

## Design Goal / 设计目标

I defined three goals for the Context Builder:

我为 Context Builder 定义了三个目标：

### 1. Relevance prioritization / 相关性排序

Most important information should appear first.

最重要的信息必须排在前面。

---

### 2. Noise reduction / 噪声过滤

Remove redundant or low-value chunks.

去除冗余和低价值信息。

---

### 3. Structured evidence formatting / 结构化证据组织

Make context interpretable and traceable.

让上下文可解释、可追溯。

---

## Final Architecture / 最终设计

The Context Builder sits between retrieval and LLM:

Context Builder 位于检索和大模型之间：

```text id="m2k9qp"
Retriever
   ↓
Context Builder
   ↓
Prompt Builder
   ↓
LLM
```

It is not just a formatter.

它不仅仅是格式化工具。

It is a reasoning preparation layer.

它是一个“推理准备层”。

---

## Key Design Decisions / 核心设计决策

---

### 1. Chunk Ranking Before Formatting / 先排序再构建

Instead of passing raw top-K results directly,

不直接使用 raw top-K，

chunks are re-ranked based on:

而是重新排序：

* semantic similarity score
* document importance
* redundancy filtering

This ensures higher signal-to-noise ratio.

提升信噪比。

---

### 2. Deduplication Layer / 去重机制

Financial documents often contain repeated content.

金融文档中经常存在重复内容。

Without deduplication:

如果不去重：

* same paragraph appears multiple times
* model gets biased toward repeated signals

So I introduced a deduplication step.

因此加入了去重层。

---

### 3. Context Compression / 上下文压缩

LLMs have limited context windows.

模型上下文长度有限。

So raw chunks must be compressed:

因此必须对 chunk 进行压缩：

* remove irrelevant sentences
* keep key numeric information
* preserve financial indicators

This is especially important for:

这一点对以下内容尤其重要：

* revenue
* margin
* cash flow
* guidance

---

### 4. Evidence Tagging / 证据标记

Each chunk is enriched with metadata:

每个 chunk 都会附带元信息：

* Source document
* Ranking score
* Chunk index

This enables traceability in Evidence Panel.

用于 Evidence Panel 的可追溯性展示。

---

## Why Context Matters More Than Retrieval / 为什么 Context 比检索更重要

During experiments, I observed a key pattern:

在实验过程中，我发现一个关键现象：

> Improving retrieval quality alone does not significantly improve final answer quality.

仅提升检索质量，并不会显著提升最终答案质量。

However:

但：

> Improving context construction significantly improves LLM output quality.

提升上下文结构，会显著改善模型输出质量。

This was a major architectural insight.

这是一个非常关键的架构认知。

---

## Common Failure Cases / 常见失败模式

Without a proper Context Builder, the system suffered from:

缺少 Context Builder 时，系统会出现：

### 1. Mixed company signals / 公司信息混杂

Apple + Tesla + NVIDIA results mixed together.

---

### 2. Overloaded prompts / 上下文过载

Too many chunks lead to hallucination.

---

### 3. Loss of hierarchy / 信息无层级结构

Important financial metrics buried in noise.

---

## Final Outcome / 最终效果

After introducing Context Builder:

引入 Context Builder 后：

* Answer consistency improved
* Hallucination reduced
* Evidence traceability improved
* Multi-document reasoning became stable

The system became significantly more reliable.

系统整体稳定性明显提升。

---

## Key Insight / 核心经验

The most important realization was:

最重要的结论是：

> Retrieval retrieves information, but Context decides intelligence.

检索负责找信息，但上下文决定智能上限。

In other words:

换句话说：

> RAG systems fail not because of retrieval, but because of poor context design.

RAG 系统失败，往往不是检索问题，而是上下文设计问题。

---

## Conclusion / 总结

The Context Builder became one of the most important components in the system.

Context Builder 成为了系统中最关键的模块之一。

It transformed raw retrieval results into structured reasoning input.

它将原始检索结果转化为结构化推理输入。

This was the step that moved the project from:

这一步让项目从：

> a retrieval system

变成：

> a reasoning system for financial analysis

---

The biggest improvement was not model tuning.

最大的提升不是模型调优。

It was structuring information before reasoning.

而是在推理前先结构化信息。
