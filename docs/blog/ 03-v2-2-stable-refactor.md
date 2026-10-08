# V2.2 Stable Refactor：From Prototype to Engineering System

# V2.2 稳定版重构：从原型系统到工程化系统

**Version / 版本：V2.2 Stable**

---

## Introduction / 项目背景

When I started this project, the system was a simple RAG prototype.

项目最开始只是一个非常简单的 RAG 原型。

It could:

它可以：

* Upload PDFs
* Embed text
* Retrieve relevant chunks
* Generate answers

At that stage, the system was functional, but not structured.

在那个阶段，系统是“能用的”，但不是“工程化的”。

As the project evolved, new features were added continuously:

随着开发推进，功能不断叠加：

* Document routing
* Multi-document retrieval
* Compare mode
* Evidence tracking

Eventually, the codebase became difficult to maintain.

最终代码逐渐变得难以维护。

This led to the V2.2 refactor.

这也是 V2.2 重构的起点。

---

## The Problem / 重构的原因

Before refactoring, the system had several issues:

重构前系统存在几个问题：

### 1. Over-coupled core engine / 核心引擎过于复杂

`core_engine.py` handled everything:

核心引擎承担了所有职责：

* Retrieval
* Context building
* Prompt construction
* Report generation
* Debug logic

This made the file too large and difficult to reason about.

导致文件过大且难以维护。

---

### 2. Mixed responsibilities / 职责混乱

Different concerns were mixed together:

不同职责混在一起：

* Knowledge loading
* Retrieval logic
* UI dependencies
* Debug utilities

There was no clear separation of layers.

没有清晰的分层结构。

---

### 3. Document Router added unnecessary complexity / Router增加复杂度

A Document Router was introduced early to improve retrieval precision.

为了提升检索精度，曾引入 Document Router。

However:

但最终发现：

* It was fragile
* It introduced ambiguity
* It duplicated retrieval logic

It was later removed completely.

最终被彻底移除。

---

## Refactoring Strategy / 重构策略

The goal of V2.2 was not to add features, but to simplify the system.

V2.2 的目标不是增加功能，而是简化系统。

The guiding principle was:

核心原则是：

> Each module should have a single responsibility.

每个模块只负责一件事。

---

## Final Architecture / 最终架构

After refactoring, the system was reorganized into clear modules:

重构后的系统被拆分为清晰模块：

```text id="q9v2ka"
User Input
      ↓
core_engine.py
      ↓
Knowledge Manager
      ↓
Hybrid Retriever
      ↓
Context Builder
      ↓
Prompt Builder
      ↓
LLM
      ↓
Report Builder
      ↓
Evidence Panel
```

---

## Module Breakdown / 模块拆分

### 1. core_engine.py

Now acts as an orchestrator only.

现在只负责流程调度。

Responsibilities:

职责：

* Initialize system
* Coordinate modules
* Execute RAG pipeline

It no longer contains business logic.

不再包含业务逻辑。

---

### 2. knowledge_manager.py

Introduced to centralize knowledge source management.

用于统一管理知识源。

Responsibilities:

* Document discovery
* Document counting
* Knowledge source abstraction

This prevents UI from directly accessing file system logic.

避免 UI 直接操作文件系统。

---

### 3. context_builder.py

Extracted from core engine.

从核心引擎中拆分出来。

Responsibilities:

* Build context from retrieved chunks
* Format evidence
* Prepare input for LLM

This improves readability and modularity.

提升可读性与模块独立性。

---

### 4. hybrid_retriever.py

Responsible for semantic retrieval only.

只负责语义检索。

Responsibilities:

* Embedding search
* Top-K retrieval
* Similarity scoring

No longer contains routing logic.

不再包含路由逻辑。

---

### 5. report_builder.py

Handles final output formatting.

负责最终报告结构化输出。

Outputs include:

* Summary
* Key Insights
* Risks
* Evidence

---

## What Changed After Refactoring / 重构后的变化

After V2.2 refactoring, the system improved in several ways:

重构后系统有以下变化：

### 1. Simpler architecture / 架构更清晰

Each module has a clear responsibility.

每个模块职责明确。

---

### 2. Easier debugging / 更容易调试

Issues can now be isolated to a single module.

问题可以快速定位到单一模块。

---

### 3. Better scalability / 更好的扩展性

New features can be added without modifying core engine.

新增功能不再需要修改核心引擎。

---

### 4. Reduced cognitive load / 降低理解成本

The system is easier to understand for new developers.

新开发者更容易理解系统结构。

---

## Key Design Decision / 核心设计决策

The most important decision during this refactor was:

最重要的决策是：

> Removing the Document Router completely.

彻底移除 Document Router。

This decision simplified the entire retrieval pipeline.

这个决定大幅简化了检索流程。

It replaced rule-based routing with semantic retrieval.

用语义检索替代规则路由。

---

## Lessons Learned / 项目经验

The most important lesson from this refactor was:

本次重构最重要的经验是：

> Refactoring is not about changing code. It is about reducing complexity.

重构不是改代码，而是降低复杂度。

In early development, adding structure seems helpful.

在早期开发中，增加结构看似合理。

But over time, unnecessary structure becomes technical debt.

但随着时间推移，过度设计会变成技术债务。

---

## Before vs After / 重构前后对比

### Before V2.2

* Large monolithic engine
* Mixed responsibilities
* Routing layer
* Hard to debug
* Hard to extend

---

### After V2.2

* Modular architecture
* Clear separation of concerns
* Simple retrieval pipeline
* Easier maintenance
* Better scalability

---

## Conclusion / 总结

V2.2 Stable is not just a version upgrade.

V2.2 稳定版不仅是一次版本更新。

It represents a shift from:

它代表了一种转变：

> “Make it work” → “Make it maintainable”

从“先实现功能”到“保证可维护性”。

This refactor laid the foundation for future improvements such as hybrid search and AI agent workflows.

这次重构也为后续的 Hybrid Search 和 AI Agent 打下了基础。

---

The goal is no longer just building a RAG system.

目标已经不只是构建 RAG 系统。

It is building a real financial research assistant.

而是构建一个真正可用的金融研究助手。
