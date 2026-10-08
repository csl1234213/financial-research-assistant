# Debug Diary #001：RAG 系统中的那些“看似随机但其实有结构”的 Bug

**Version / 版本：V2.2 Stable**

---

## Introduction / 背景

This article records several real debugging cases encountered while building the Financial Research Assistant.

本文记录的是在开发 Financial Research Assistant 过程中遇到的一些真实 Debug 问题。

Unlike typical tutorials, these bugs were not caused by syntax errors.

这些问题并不是语法错误导致的。

They were caused by architectural issues, module coupling, and incorrect assumptions in system design.

而是由架构设计、模块耦合以及错误的系统假设导致的。

---

# Bug 1：Search Failed — “tuple index out of range”

## Symptom / 现象

During testing, the system occasionally crashed with:

在测试过程中，系统偶尔会报错：

```
Search failed: tuple index out of range
```

No clear stack trace pointing to a single function.

没有明确指向某一个函数。

---

## Initial Assumption / 初始判断

At first, I assumed this was an embedding or retrieval bug.

最初以为是 embedding 或检索逻辑问题。

So I focused on:

于是我检查了：

* Vector similarity function
* Top-K selection
* Chunk parsing

Nothing seemed wrong.

但都没有问题。

---

## Root Cause / 根因

Eventually, I discovered the real issue:

最终发现真正问题是：

> The retrieval output format was inconsistent across refactors.

检索输出格式在不同重构阶段不一致。

Some functions returned:

部分函数返回：

```
(List[Chunk], Score)
```

Others returned:

```
(List[Chunk])
```

But the downstream pipeline assumed a fixed structure:

但下游代码默认结构是固定的：

```
chunks[i], score[i]
```

---

## Fix / 修复方式

Standardized retrieval output format:

统一检索输出结构：

```
python id="x9k2wp"
return {
    "chunks": chunks,
    "scores": scores
}
```

This removed implicit tuple unpacking across modules.

避免了跨模块的隐式 tuple 解包。

---

## Lesson / 经验

> In RAG systems, inconsistent data contracts are more dangerous than algorithm bugs.

在 RAG 系统中，“数据结构不一致”比算法错误更危险。

---

# Bug 2：`extract_local_context is not defined`

## Symptom / 现象

After refactoring modules, the system suddenly crashed:

重构模块后，系统报错：

```
NameError: extract_local_context is not defined
```

---

## Initial Confusion / 初期困惑

The function clearly existed in the codebase.

函数明明存在。

* It was implemented
* It was not deleted
* It was used in previous versions

But runtime still failed.

但运行时仍然报错。

---

## Root Cause / 根因

The issue was not deletion.

问题不在于函数被删除。

It was **module responsibility shift during refactoring**.

而是重构过程中模块职责迁移导致的引用断裂。

Specifically:

具体来说：

* Function moved from `core_engine.py` → `context_builder.py`
* Import chain was not updated everywhere
* One layer still assumed old architecture

---

## Fix / 修复方式

Updated import chain:

统一修复 import 关系：

```python id="q1w8nx"
from retrieval.hybrid_retriever import extract_local_context
```

And removed legacy call paths from engine layer.

并移除 engine 层的旧调用路径。

---

## Lesson / 经验

> In modular refactoring, function movement is safer than partial duplication, but dangerous if import chains are not updated consistently.

模块化重构中，“移动函数”比“复制函数”更安全，但如果不更新依赖链，会产生隐性错误。

---

# Bug 3：Document Router causing incorrect answers

## Symptom / 现象

When asking comparative questions:

当提问对比类问题时：

> Compare Apple and Tesla gross margin

The system returned incomplete or biased answers.

系统返回了不完整或偏向某一公司的答案。

---

## Initial Hypothesis / 初始假设

I assumed retrieval quality was poor.

最初认为是检索质量问题。

So I tried:

尝试了：

* Better prompts
* Better chunking
* Better embedding models

But results did not improve.

但效果没有改善。

---

## Root Cause / 根因

The Document Router was filtering documents too aggressively.

Document Router 过度过滤了文档。

It assumed:

它默认认为：

> One question → One document

But financial questions are inherently multi-document.

但金融问题本质上是多文档的。

---

## Fix / 修复方式

Removed Document Router entirely.

直接删除 Router。

Replaced with:

替换为：

* Semantic retrieval over full corpus
* Context Builder for merging evidence

---

## Lesson / 经验

> Over-engineering retrieval logic can reduce answer quality in multi-document systems.

在多文档系统中，过度设计检索逻辑反而会降低答案质量。

---

# Bug 4：Sidebar showing incorrect document state

## Symptom / 现象

After uploading PDFs, sidebar sometimes showed outdated document list.

上传 PDF 后，侧边栏有时显示旧数据。

---

## Root Cause / 根因

Direct file system access from UI layer:

UI 层直接访问文件系统：

```
python id="l9k2ps"
os.listdir("pdfs")
```

This bypassed system state management.

绕过了系统状态管理。

---

## Fix / 修复方式

Introduced Knowledge Manager:

引入 Knowledge Manager：

```
python id="v8k2dm"
get_documents()
get_document_count()
```

UI no longer accesses file system directly.

UI 不再直接访问文件系统。

---

## Lesson / 经验

> UI should never directly access system storage in a modular architecture.

在模块化架构中，UI 不应该直接访问存储层。

---

# Overall Takeaways / 总结

Across all bugs, a common pattern emerged:

这些问题有一个共同点：

> They were not coding bugs, but architecture inconsistencies.

它们不是代码错误，而是架构不一致导致的问题。

Key insights:

核心经验：

* Data contracts matter more than implementation details
* Module boundaries must be strictly enforced
* Refactoring without dependency tracking leads to hidden failures
* Retrieval systems are highly sensitive to architecture changes

---

# Conclusion / 总结

Building a RAG system is not difficult.

构建一个 RAG 系统并不难。

Keeping it maintainable is the real challenge.

真正的挑战是让系统保持可维护性。

Most issues in this project were not solved by better algorithms,

这个项目中的大多数问题，并不是通过更好的算法解决的，

but by simplifying system design.

而是通过简化系统设计解决的。
