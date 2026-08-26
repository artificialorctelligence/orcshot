[English](TRANSLATING.md) | [Español](TRANSLATING.es.md) | [Français](TRANSLATING.fr.md) | [Deutsch](TRANSLATING.de.md) | [Українська](TRANSLATING.uk.md) | [हिन्दी](TRANSLATING.hi.md) | [日本語](TRANSLATING.ja.md) | **中文**

# 翻译 Orcshot

Orcshot 目前提供以下语言：

- 英语（默认——始终可用，无需翻译文件）
- Español
- Français
- Deutsch
- Українська
- हिन्दी
- 日本語
- 中文

如果这份列表里没有您的语言，或者您发现某处翻译有误、别扭或缺失——那么本页就是为您准备的。
**您不需要懂编程，也不需要查看任何源代码。**

## 您需要准备什么

只需一个免费工具：[Poedit](https://poedit.net/)（支持 Windows、Mac 和 Linux）。它是这类翻译文件的
标准编辑器，会给您一个简单的两栏列表——左边是英文原文，右边是留给您填写译文的空白。无需代码，也没有
语法要学。

## 添加一种新语言

1. 下载模板文件：[`po/orcshot.pot`](po/orcshot.pot)。
2. 用 Poedit 打开它。
3. 当 Poedit 询问时，选择“创建新的翻译”，并选定您的语言。
4. 逐条浏览列表，为左边的每一条英文字符串填写译文。
5. 保存文件——Poedit 会把它保存为 `<您的语言代码>.po`（例如意大利语是 `it.po`）。
6. 把文件发回来（见下面的“把文件发回来”）。

## 改进现有的翻译

1. 从 [`po/`](po/) 中取得该语言的文件（例如西班牙语对应
   [`po/es.po`](po/es.po)）。
2. 用 Poedit 打开它，修改其中需要订正的条目。
3. 保存，然后以同样的方式发回来。

## 需要注意的一点

有些字符串中含有 `{}` 占位符，就像这样：

```
"You're running the latest version ({})."
```

这个 `{}` 会在运行时被替换成别的内容（版本号、文件名等等）——请在译文中保留它，只需把它移到符合您所用
语言语序的自然位置即可。如果译文缺少原文中有的占位符，Poedit 会提醒您，这通常说明有地方需要再检查
一遍。

您还会看到少数字符串是专有名词（比如“Orcshot”本身）或纯粹的符号、数字——它们应当保持原样，完全不需要
翻译。

## 把文件发回来

**如果您用得惯 GitHub**：请提交一个 pull request，在 `po/` 下添加或更新您的文件。这样就可以了——不
需要改动任何其他文件。

**如果您用不惯**：完全没关系。只需
[提交一个 issue](https://github.com/artificialorctelligence/orcshot/issues/new)
并附上您的 `.po` 文件。如果您完全不想使用 GitHub，也可以改为把文件用电子邮件发送到
<orc.shot@yahoo.com>。无论哪种方式，都会有人替您提交 pull request。

## 之后会发生什么

维护者会审阅这份翻译（最好还能请另一位讲该语言的人帮忙把关，因为翻译质量很重要，而我们当中没有人能
亲自核实每一种语言），把它合并进来，它就会随下一个版本一起发布。
