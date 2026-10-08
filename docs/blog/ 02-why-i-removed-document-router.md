# Why I Removed the Document Router

# 为什么我最终移除了 Document Router

**Version / 版本：V2.2 Stable**

---

## Introduction / 项目背景

In the early stage of this project, I introduced a component called the Document Router.

在项目早期，我设计了一个叫 Document Router（文档路由器）的模块。

Its purpose was simple:

它的目标很简单：

> Before retrieval, determine which document the question belongs to.

在检索之前，先判断问题属于哪个文档。

The idea sounded reasonable.

这个想法在理论上是合理的。

It is similar to how humans narrow down search scope before reading.

类似于人类在阅读前先缩小信息范围。

---

## The Original Motivation / 最初动机

As more financial PDFs were added to the system:

随着越来越多的财报 PDF 被加入系统：

* Apple reports
* Tesla reports
* NVIDIA reports

The retrieval space became noisy.

检索空间开始变得混乱。

For example, a simple question like:

例如一个简单问题：

> How has gross margin changed?

could return results from multiple companies.

可能会同时返回多个公司的内容。

So I introduced a routing step:

因此我引入了一层“路由判断”：

```text id="r1k3pa"
User Question
      ↓
Document Router
      ↓
Selected Company Documents
      ↓
Vector Retrieval
      ↓
LLM Answer
```

At first glance, this seemed like a good optimization.

从表面看，这是一个合理的优化。

---

## What Went Wrong / 问题在哪里

After implementing the router, several issues started to appear.

但在实现之后，问题逐渐暴露。

---

### 1. Ambiguity in Real Questions / 问题本身是模糊的

Financial questions are often not single-document specific.

金融问题本身往往不是单一文档导向的。

For example:

例如：

* Compare Apple and Tesla margins
* How does NVIDIA differ from AMD?
* Which company has better cash flow stability?

These questions **cannot be assigned to one document.**

这些问题无法归类到单一文档。

The router becomes a wrong assumption layer.

路由层反而变成了一个错误假设层。

---

### 2. Company Detection Is Fragile / 公司识别不稳定

The router relied on keyword-based matching.

路由逻辑依赖关键词匹配。

But in real usage:

但在真实场景中：

* Users use abbreviations
* Users use product names
* Users use industry terms

For example:

例如：

* “Tesla” vs “TSLA”
* “AI chip leader” vs “NVIDIA”

This caused frequent misrouting.

导致频繁误判。

---

### 3. Retrieval Already Solves This Problem / 检索本身已经解决问题

Vector retrieval is already strong enough.

向量检索本身已经足够强大。

It naturally finds relevant chunks across all documents.

它可以自动在全库中找到相关片段。

So the router was duplicating work.

因此 Router 实际上是在重复已有能力。

---

### 4. Increased System Complexity / 系统复杂度上升

Introducing the router added:

引入 Router 带来了：

* Extra logic layer
* More edge cases
* Harder debugging
* More maintenance cost

Every new feature increased cognitive load.

每增加一个功能，系统理解成本都会上升。

---

## The Key Realization / 核心认知变化

The most important realization was this:

最重要的认知变化是：

> Better architecture is not about adding control layers, but about trusting retrieval.

更好的架构不是增加控制层，而是信任检索本身的能力。

Initially I tried to control retrieval.

最开始我试图“控制检索”。

Later I realized:

后来我意识到：

> Retrieval quality matters more than routing precision.

检索质量比路由精度更重要。

---

## Final Decision / 最终决策

I removed the Document Router completely.

我最终移除了 Document Router。

The system became simpler:

系统结构变得更简单：

```text id="f8x2mp"
User Question
      ↓
Semantic Retrieval
      ↓
Context Builder
      ↓
Prompt Builder
      ↓
LLM
      ↓
Research Report
```

No routing layer.

没有路由层。

No manual filtering.

没有人工过滤。

---

## What Improved After Removal / 移除后的变化

After removing the router:

移除之后：

* System became more stable
* Debugging became easier
* Retrieval quality improved in multi-document queries
* Architecture became cleaner

Most importantly:

最重要的是：

> The system became easier to reason about.

系统变得更容易理解和推理。

---

## Key Lesson / 核心经验

This change taught me an important engineering lesson:

这次调整让我学到了一个重要的工程经验：

> Sometimes, removing a feature improves the system more than adding one.

有时候，删除一个功能比增加一个功能更能提升系统质量。

Not every intelligent idea is necessary at system level.

不是所有“聪明的设计”都适合系统落地。

---

## When Document Routing Makes Sense / 什么时候 Router 是有价值的？

After this experience, I believe Document Routing is still useful in some cases:

在这次经历之后，我认为 Router 在以下场景仍然有价值：

* Large-scale enterprise document systems (1000+ documents)
* Strict domain separation (legal, medical, finance isolated)
* Compliance-driven systems requiring isolation

But for a small-to-medium RAG system:

但对于中小型 RAG 系统：

> It introduces more complexity than value.

它带来的复杂度大于收益。

---

## Conclusion / 总结

Removing the Document Router was not a regression.

移除 Document Router 并不是退步。

It was a simplification.

而是一次架构简化。

This decision helped transform the project from:

这个决定让项目从：

> a prototype RAG system

变成：

> a structured Financial Research Assistant

---

The biggest improvement was not performance.

最大的提升不是性能。

It was clarity.

而是系统清晰度。
