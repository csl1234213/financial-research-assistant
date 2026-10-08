# Financial RAG System Design: Retrieval, Context, and Output Boundary

# 金融 RAG 系统设计：检索、上下文与输出边界（终极版）

**Version / 版本：V2.2 Stable**

---

# 1. Introduction / 项目背景

This project started as a simple PDF question-answering system.

项目最初只是一个简单的 PDF 问答系统。

The goal was:

目标是：

> Upload a financial report and ask questions about it.

上传财报并进行问答。

The initial architecture was straightforward:

最初架构如下：

```text id="a91k2p"
PDF → Embedding → Vector Search → LLM → Answer
```

It worked, but only in simple scenarios.

它在简单场景下是可用的。

However, financial analysis is fundamentally different from QA systems.

但金融分析本质上并不是问答系统。

It requires:

它需要：

* Multi-document reasoning
* Evidence traceability
* Structured outputs
* Controlled hallucination

This led to a full redesign of the system.

因此我对整个系统进行了重构。

---

# 2. System Overview / 系统整体架构

The final system is composed of four layers:

最终系统分为四层：

```text id="p9k3mn"
User Question
      ↓
Retrieval Layer
      ↓
Context Layer
      ↓
LLM Layer
      ↓
Output Layer (Evidence + Report)
```

Each layer has a strict responsibility.

每一层都有明确职责。

---

# 3. Retrieval Layer / 检索层设计

## 3.1 Problem with naive retrieval

Early versions directly used top-k similarity search.

早期版本直接使用 top-k 向量检索。

Problems appeared:

问题包括：

* Mixed company information
* Low signal-to-noise ratio
* Weak ranking stability

---

## 3.2 Improved retrieval strategy

The final retrieval pipeline:

最终检索流程：

```text id="k1n7qp"
Query
  ↓
Embedding
  ↓
Semantic Search
  ↓
Top-K Selection
  ↓
Deduplication
  ↓
Rank Refinement
```

Key improvement:

关键改进：

> Retrieval is no longer just search, but ranked evidence selection.

检索不再只是搜索，而是“证据排序”。

---

# 4. Context Layer / 上下文构建层（核心）

This is the most important part of the system.

这是整个系统最关键的部分。

---

## 4.1 Why Context matters more than Retrieval

A key insight from this project:

项目中的核心认知是：

> Better retrieval does not guarantee better answers.

更好的检索不等于更好的答案。

But:

但：

> Better context construction directly improves LLM reasoning.

更好的上下文构建可以直接提升模型推理质量。

---

## 4.2 Context Builder design

The Context Builder performs three operations:

Context Builder 做三件事：

### 1. Ranking

Sort chunks by relevance score.

按相关性排序。

---

### 2. Filtering

Remove:

过滤掉：

* duplicates
* low relevance chunks
* noisy paragraphs

---

### 3. Structuring

Convert raw chunks into structured context:

将 chunk 转换为结构化上下文：

```text id="c8m1qp"
[Document: NVIDIA Q2 Report]
[Score: 0.92]

Revenue from Data Center increased by 54% year-over-year...
```

---

## 4.3 Key Insight

> LLM performance depends more on context structure than model size.

模型效果更多取决于上下文结构，而不是模型大小。

---

# 5. Prompt Layer / 提示词层设计

## 5.1 Initial prompt problem

Early prompts were simple:

早期 prompt 很简单：

```text id="p2n8qv"
Answer the question based on context.
```

Problems:

问题：

* hallucination
* weak grounding
* inconsistent reasoning

---

## 5.2 Improved prompt design

Final prompt structure:

最终 prompt：

```text id="r9m1kv"
You are a financial research assistant.

Answer ONLY using the evidence below.

If the answer is not in the evidence, reply:

"Not found in provided documents."
```

---

## 5.3 Key design principle

> The model is not allowed to "guess".

模型不允许“猜测”。

This is critical for financial scenarios.

这一点在金融场景非常重要。

---

# 6. Output Boundary Layer / 输出边界设计（核心重点）

This is the most important upgrade in the system.

这是系统中最关键的升级之一。

---

## 6.1 Why Output Boundary is needed

Even with good retrieval and context, LLMs can still:

即使有好的检索和上下文，模型仍然可能：

* hallucinate numbers
* mix companies
* infer missing data
* over-generalize

So we need strict output control.

因此必须进行输出约束。

---

## 6.2 Three constraints in output layer

### 1. Evidence grounding

Every answer must be supported by retrieved chunks.

所有答案必须有证据支持。

---

### 2. No external knowledge

Model cannot use internal knowledge.

模型不能使用自身知识。

Only context is allowed.

只能使用上下文。

---

### 3. Financial strictness

The model cannot:

模型不能：

* invent revenue
* estimate margins
* assume growth rates

---

## 6.3 Final behavior rule

The final rule is:

最终规则是：

> If not in evidence → do not answer.

如果证据中不存在 → 不能回答。

---

# 7. Evidence Layer / 证据层设计

The Evidence Panel is responsible for:

Evidence Panel 负责：

* showing source documents
* displaying retrieved chunks
* linking answer to evidence

---

## 7.1 Why this matters

Without evidence:

没有证据：

> The system is just a chatbot.

系统只是一个聊天机器人。

With evidence:

有证据：

> The system becomes a financial research tool.

系统变成金融研究工具。

---

## 7.2 Structure

```text id="v7m2qp"
Answer
   ↓
Evidence Panel
   ↓
Document Source
   ↓
Chunk Reference
```

---

# 8. Key Architecture Insight / 核心架构认知

The most important realization from this project:

项目最重要的认知：

> RAG systems fail not because retrieval is weak, but because reasoning context is poorly designed.

RAG 系统失败不是因为检索差，而是因为上下文设计差。

---

# 9. Final System Architecture / 最终系统架构

```text id="x8m1qp"
User Question
      ↓
Retrieval Layer (Search + Ranking)
      ↓
Context Layer (Structure + Filter + Compress)
      ↓
Prompt Layer (Strict Instruction)
      ↓
LLM (Constrained Reasoning)
      ↓
Output Layer
   ├── Answer
   └── Evidence Panel
```

---

# 10. Conclusion / 总结

This project evolved from a simple RAG prototype into a structured financial research system.

这个项目从一个简单 RAG 原型，演变为结构化金融研究系统。

The key improvement was not model tuning or retrieval optimization.

核心提升不是模型优化或检索优化。

It was system design:

而是系统设计：

* Context structuring
* Output boundary control
* Evidence-based reasoning

---

## Final Insight / 最终总结

> In production RAG systems, intelligence is not in the model — it is in the system design around the model.

在生产级 RAG 系统中，智能不在模型本身，而在模型周围的系统设计中。
