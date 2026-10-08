# From PDF Q&A to Financial Research Assistant

# 从 PDF 问答系统到金融研究助手

**Version / 版本：V2.2 Stable**

---

## Introduction / 项目简介

When I started this project, my goal was simple: build a Retrieval-Augmented Generation (RAG) system that could answer questions based on PDF documents.

刚开始做这个项目的时候，我的目标很简单：做一个基于 PDF 文档的检索增强生成（RAG）系统，让模型能够根据文档回答问题。

The initial idea was straightforward:

最初的流程非常简单：

```text id="a1q7kp"
Upload PDF / 上传PDF
      ↓
Embedding / 向量化
      ↓
Vector Search / 向量检索
      ↓
LLM / 大模型
      ↓
Answer / 回答
```

At that stage, the system worked well for basic question answering.

在这个阶段，系统可以很好地完成基础问答任务。

For example:

例如：

> What was NVIDIA's revenue this quarter?

However, as the project evolved, I realized that this simple QA system is far from real financial research.

但随着项目推进，我逐渐意识到：这种简单的问答系统距离真实的金融研究还有很大差距。

---

## Why PDF Q&A Is Not Enough

## 为什么 PDF 问答系统是不够的

In real financial analysis, users rarely rely on a single document.

在真实的金融分析中，用户几乎不会只依赖一份文档。

Instead, they analyze multiple sources:

分析对象通常包括：

* Annual reports / 年报
* Quarterly earnings reports / 季报
* Earnings call transcripts / 电话会议纪要
* Investor presentations / 投资者材料
* Press releases / 新闻公告

Typical questions are not simple fact retrieval tasks.

常见问题也不再是简单的事实检索，例如：

* How has gross margin changed over time?
* What risks did management highlight this quarter?
* How does NVIDIA compare with Apple in AI strategy?

These questions require cross-document reasoning and structured evidence.

这些问题需要跨文档推理以及结构化证据支持。

This was the first major design turning point of the project.

这也是项目第一次真正的设计转折点。

---

## First Attempt: Document Router

## 初步尝试：Document Router

To improve retrieval quality, I introduced a Document Router.

为了提高检索精度，我引入了 Document Router（文档路由模块）。

The idea was simple:

思路很简单：

> First identify which company the question belongs to, then search only relevant documents.

先判断问题属于哪个公司，然后只检索对应文档。

At first, this worked reasonably well.

一开始，这个方法效果不错。

It reduced noise and improved precision.

它减少了无关文档的干扰，提高了检索精度。

However, problems quickly appeared.

但很快问题就出现了：

* Company names are ambiguous / 公司名称存在歧义
* Users ask comparative questions / 用户会问对比问题
* Routing rules become complex / 路由规则越来越复杂

Eventually, maintenance cost exceeded its benefit.

最终，维护成本超过了收益。

---

## Decision: Remove Complexity

## 决策：移除复杂性

After multiple iterations, I decided to remove the Document Router completely.

经过多次迭代后，我最终决定移除 Document Router。

Instead of filtering documents first, the system now focuses on better retrieval and context building.

系统不再“先筛选文档”，而是专注于提升检索和上下文构建能力。

The architecture became simpler:

系统架构变得更加简洁：

```text id="b8x1mq"
Upload PDF / 上传PDF
      ↓
Knowledge Manager / 知识管理
      ↓
Semantic Retrieval / 语义检索
      ↓
Context Builder / 上下文构建
      ↓
Prompt Builder / 提示词构建
      ↓
LLM / 大模型
      ↓
Research Report / 研究报告
      ↓
Evidence Panel / 证据展示
```

This shift improved both stability and maintainability.

这一调整提升了系统稳定性与可维护性。

---

## Key Components in V2.2 Stable

## V2.2 稳定版本的核心模块

### 1. Knowledge Manager / 知识管理器

Centralized management of documents instead of direct file system access.

统一管理知识源，而不是直接访问文件系统。

Responsibilities:

职责包括：

* Document loading / 文档加载
* Source tracking / 来源管理
* Statistics / 统计信息

---

### 2. Context Builder / 上下文构建器

Prepares structured context for LLM input.

为大模型生成结构化上下文。

It:

* Merges retrieved chunks
* Adds citations
* Formats evidence

---

### 3. Evidence Panel / 证据面板

Ensures transparency of model outputs.

确保模型输出可解释。

Users can see:

用户可以看到：

* Which documents were used
* Which chunks were retrieved
* How answers were generated

---

### 4. Research Report / 研究报告生成

Instead of plain answers, the system now generates structured reports.

系统输出不再是简单回答，而是结构化报告：

* Summary / 总结
* Key Findings / 关键发现
* Risks / 风险
* Evidence / 证据

---

## Lessons Learned / 项目经验

The most important lesson from this project is not how to add features, but when to remove them.

这个项目最重要的收获不是“增加了什么功能”，而是“什么时候该删掉功能”。

The Document Router was not wrong.

Document Router 并不是错误设计。

It simply became unnecessary at this scale.

只是它在当前规模下已经不再必要。

Engineering is not only about building systems.

工程不仅是“构建系统”。

It is also about reducing unnecessary complexity.

同样重要的是“降低系统复杂度”。

---

## Future Work / 未来方向

Future iterations will focus on:

未来版本将重点关注：

* Retrieval optimization / 检索优化
* Hybrid search (local + web) / 本地+网络混合搜索
* Financial analysis modules / 财务分析模块
* AI agent workflows / AI Agent 工作流

The goal is no longer a simple RAG system.

目标已经不再是简单的 RAG 系统。

It is to build a real Financial Research Assistant.

而是构建一个真正可用的金融研究助手。

---

## Conclusion / 总结

This project evolved from a simple PDF question-answering system into a structured financial research assistant.

项目从一个简单的 PDF 问答系统，逐渐演变为结构化的金融研究助手。

The most important transformation was not technical, but architectural thinking.

最重要的变化不是技术层面，而是架构思维的转变。

From “make it work”
to “make it simple and maintainable”.

从“实现功能”
到“保持简洁与可维护性”。
