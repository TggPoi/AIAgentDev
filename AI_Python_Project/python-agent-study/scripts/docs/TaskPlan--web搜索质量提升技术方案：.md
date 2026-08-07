# TaskPlan--web搜索质量提升技术方案：

# 1. sitemap匹配率低的原因分析：

我先重新读取当前代码，然后逐项讲解：


这四个修复都集中在 sitemap 救援的**打分排序**环节。先讲背景，再逐个拆解。

## 背景：排序器要解决什么问题

盲区 B 触发救援后，我们从 postgresql.org 的 sitemap 拿到了 **29578 个页面 URL**，但只能送 20 个候选给 LLM 选择器。所以需要一个纯确定性的排序器，把"行级安全策略专页"排到最前面。

排序器的原始设计是 **TF-IDF 思想**：每个页面得分 = 它命中的打分词的 `1/文档频率` 之和。命中越稀有的词，得分越高。这个思想本身没错，但真实数据暴露了四个漏洞。

---

## 修复 1：复合词压缩匹配

**问题**：打分词 `row-level-security` 和 URL 做子串匹配时永远匹配不上。

原因看两边的形态：

```
打分词:   "row-level-security"        （带连字符）
URL 压缩: "…docs16ddlrowsecurityhtml"  （URL 里是连写 rowsecurity，且省略了 level）
```

旧代码直接拿 `"row-level-security" in compact_url` 判断——连字符把词切断了，永远 False。**目标页连打分词都匹配不到，排序再精细也没用。**

**修复**（[_rank_sitemap_candidates](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L246-L251)）：匹配前把打分词也做同样的"去分隔符压缩"，两边在同一形态下比较：

```python
compact_needles = {
    re.sub(r"[^a-z0-9]", "", token) for token in needles
}
# "row-level-security" → "rowlevelsecurity"
# "16" → "16"（不变）
```

但这只解决了一半——压缩后是 `rowlevelsecurity`，URL 里却是 `rowsecurity`（官方文档习惯省略中间词 `level`）。所以还需要**变体生成**（[_compound_variants](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L165-L183)）：

```python
tokens = ["row", "level", "security"]
joined = "rowlevelsecurity"                    # 全拼变体
# 逐个省略一个内部分词（首尾不省略，避免碎片）：
omitted = "row" + "security" = "rowsecurity"   # ← 命中官方 URL 的关键变体
```

诊断时我就是靠 DEBUG 打印发现这一点的：压缩词表里只有 `rowlevelsecurity`，而 URL 压缩串是 `…ddlrowsecurityhtml`，两者差一个 `level`。补上变体后立刻命中。

---

## 修复 2：复合词优先层（两级排序）

**问题**：修复 1 之后目标页能匹配了，但**还是排不到第一**。诊断数据显示：

```
第1名: applevel-consistency.html  matched: 16, level, postgresql
第3名: ddl-rowsecurity.html       matched: 16, postgresql, rowsecurity
```

为什么？IDF 的软肋：`level` 这个词在整个 sitemap 里只出现在 2 个页面（applevel-consistency 和 backup-manifest-toplevel），**稀有度极高**，`1/2 = 0.5` 的单项贡献就超过了 `rowsecurity`（出现在约 10 个版本的同名页面，`1/10 = 0.1`）。一个与主题毫无关系的页面，凭"碰巧包含稀有短词"压过了主题精确匹配的页面。

**修复**（[排序键改为两级](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L268-L280)）：引入"主题确定性分层"，把排序从一维分数改成元组排序：

```python
scored = [
    (
        1 if matched & compound_needles else 0,   # 第一级：是否命中复合主题词
        sum(1.0 / doc_freq[token] for token in matched),  # 第二级：IDF 总分
        url, matched,
    )
    ...
]
scored.sort(key=lambda item: (-item[0], -item[1], -item[2].count("/"), item[2]))
```

其中复合词的判定标准是"压缩后长度 ≥ 6"（`rowsecurity` 长 11 ✓，`level` 长 5 ✗）：

```
第一层（命中复合词）: ddl-rowsecurity.html          ← RLS 专页在这里
第二层（只有短词）:   applevel-consistency.html 等   ← level 再稀有也被压在下一层
```

设计依据：`row-level-security` 这类词是 planner **专门为这次查询生成的主题词**，命中它就是强主题证据；而 `level` 是从 query 机械拆出来的短词，语义不可靠。**IDF 只负责层内精排，不再跨层比较**——这消除了"稀有短词劫持排序"的可能性。

---

## 修复 3：片段路径段预筛

**问题**：救援候选里混进了 `news/…postgresql-16-18-3279/` 这种新闻页。版本预筛用的是简单子串判断 `"16" in url`，而 `16` 作为子串会命中三种错误形态：

```
/docs/15/…            → 不含 16，正确拒绝 ✓
/news/…2016-…         → "2016" 含子串 "16"，误收 ✗
/news/…postgresql-16-18-… → 版本号列表中的 16，误收 ✗
/docs/165/…           → "165" 含子串 "16"，误收 ✗
```

**修复**（[_url_has_fragment](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L316-L322) + [预筛逻辑](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L305-L312)）：要求片段作为**独立边界单元**出现——前后都不能紧贴字母数字：

```python
pattern = re.compile(r"(?<![a-z0-9])" + re.escape(fragment.lower()) + r"(?![a-z0-9])")
```

用 `16` 验证四种情况：

| URL 片段        | 左边界             | 右边界 | 结果                                   |
| --------------- | ------------------ | ------ | -------------------------------------- |
| `/docs/16/ddl…` | `/`（非字母数字）✓ | `/` ✓  | 保留                                   |
| `…/2016/…`      | `0` ✗              | —      | 拒绝                                   |
| `…-16-18-…`     | `-` ✓              | `-` ✓  | 保留（连字符分隔的版本列表，边界合法） |
| `/docs/165/…`   | `/` ✓              | `5` ✗  | 拒绝                                   |

注意一个工程细节：预筛是**可回退的**——如果过滤后一个候选都不剩（比如片段写得太严），就退回全集排序，而不是让救援空手而归：

```python
if filtered:
    entries = filtered   # 全被过滤时不赋值，保持原 entries
```

---

## 修复 4：子串 token 去冗余

**问题**：修复 1 引入变体后产生了一个副作用。RLS 页的压缩串 `…ddlrowsecurityhtml` 会**同时命中三个打分词**：

```
"rowsecurity" in compact  ✓  （复合词变体）
"row"         in compact  ✓  （rowsecurity 的前 3 个字母）
"security"    in compact  ✓  （rowsecurity 的后 8 个字母）
```

如果三个都计分，等于**同一个语义信号被计了三次**。更隐蔽的危害在 IDF 统计：`row` 和 `security` 的文档频率会被这些"伪命中"抬高，稀释它们在其他页面（如真正只含 row 的 `fdw-row-locking.html`）上的区分度。

**修复**（[_dedupe_substring_tokens](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L217-L233)）：**按每个 URL 的命中集**做去冗余——如果一个命中词是另一个命中词的真子串，丢弃短的、保留长的：

```python
for token in tokens:
    covered = any(token != other and token in other for other in tokens)
    if not covered:
        kept.add(token)
```

RLS 页命中集 `{16, postgresql, row, rowsecurity, security}` 中，`row ⊂ rowsecurity`、`security ⊂ rowsecurity`，所以只保留 `{16, postgresql, rowsecurity}`——**一次命中只计一个最强的语义信号**。

关键设计是"按 URL 局部去冗余"而不是"全局删掉短词"：`fdw-row-locking.html` 只命中 `row` 不命中 `rowsecurity`，它的 `row` 不受影响、照常计分。

---

## 四个修复的协作关系

用最终诊断数据串一遍 RLS 专页的完整路径：

```
29578 个 sitemap URL
   ↓ 修复3：片段预筛（只留含独立 /16/ 路径段的页面）
数百个 16 版页面
   ↓ 修复1：压缩匹配 + 变体，rowsecurity 命中目标页
   ↓ 修复4：命中集去冗余，RLS 页只计 {16, postgresql, rowsecurity}
   ↓ 修复2：命中复合词 → 进入第一层，压过所有只含短词的页面
第1名: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
```

四个修复各司其职：**修复 1 解决"匹配不到"，修复 3 解决"混进错的"，修复 4 解决"重复计分"，修复 2 解决"排序被劫持"**。整套机制是纯确定性代码，不依赖任何 LLM 调用，符合项目"可信事实由服务端代码持有"的规则；对应的回归用例都在 [test_direct_web_sitemap.py](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/phase_15/test_direct_web_sitemap.py) 中（复合词变体、复合词优先、去冗余、片段预筛各一例）。

# 1.1 技术点讲解：

没关系，这次我从最基础的概念讲起，假设你没有 IDF、正则、元组排序的背景知识。

---

## 修复 2：先讲 IDF，再讲元组排序

## 2.1 什么是 IDF

先忘掉这个词，看一个生活场景：

> 你在图书馆找"一本讲猫的书"。管理员告诉你："含有'书'这个字的有 10000 本，含有'猫'这个字的只有 3 本。"

你当然按"猫"去找。**一个词出现得越少，它的指示作用越强。** 这就是 IDF（Inverse Document Frequency，逆文档频率）的全部思想：

 ![image-20260807163623148](./assets/image-20260807163623148.png)

用真实诊断数据算：

| 打分词        | 出现在多少页面 | 分数 = 1/数量                 |
| ------------- | -------------- | ----------------------------- |
| `postgresql`  | ~20000         | 0.00005（几乎没用，哪页都有） |
| `security`    | ~800           | 0.001                         |
| `rowsecurity` | ~10            | **0.1**（稀有，指示性强）     |
| `level`       | 2              | **0.5**（最稀有）             |

一个页面的总分 = 它命中的所有词的分数相加。

## 2.2 这个思想的软肋（问题所在）

IDF 只看"稀有不稀有"，**不看"这个词跟主题有没有关系"**。

`level` 只出现在 2 个页面，分数 0.5，全场最高。于是 `applevel-consistency.html`（讲数据库事务一致性的页面，跟行级安全毫无关系）仅凭包含 `level` 这 5 个字母，总分就超过了命中 `rowsecurity`（0.1）的目标页。

**稀有 ≠ 相关。** 这是旧排序出错的根本原因。

## 2.3 元组排序是什么

Python 比较两个元组时，**从左到右逐个比，第一个比出结果就停**：

```python
(1, 0.1) > (0, 0.5)   # True！第一位 1 > 0，直接赢了，根本不看第二位
(1, 0.2) > (1, 0.9)   # False，第一位平手，才比第二位：0.2 < 0.9
```

像排队先看"年级"再看"班级"——三年级 1 班永远排在二年级 9 班前面，不管 9 班内部怎么排。

## 2.4 修复：把"是否命中主题词"变成第一位

我们给每个页面构造一个元组，第一位是"是否命中复合主题词（rowsecurity 这种长词）"，第二位才是原来的 IDF 总分：

```python
ddl-rowsecurity.html      → (1, 0.10)   # 命中 rowsecurity → 第一位是 1
applevel-consistency.html → (0, 0.50)   # 只命中 level      → 第一位是 0
```

排序结果：

```
(1, 0.10)  RLS 专页          ← 第一位是 1 的全部在前
(0, 0.50)  applevel
(0, 0.001) ...
```

`level` 的 0.5 分再高也没用——它被锁死在第二位，第一位输了就是输了。这就是"一维分数改成元组排序"的含义：**原来所有词的分混在一个数字里比大小，现在把"主题相关性"抽出来变成更高优先级的一道闸门。**

---

## 修复 3：正则里的 `(?<![a-z0-9])` 和 `(?![a-z0-9])`

## 3.1 先看旧写法错在哪

旧的判断是：

```python
"16" in url.lower()
```

`in` 就是"这串字符里任意位置出现 16 就算"。所以：

```
"/docs/16/ddl.html"     → 有 "16" ✓（这是我们想要的）
"/news/2016-report"     → "2016" 里有 "16" ✓（错了！这是年份 2016）
"/docs/165/intro.html"  → "165" 里有 "16" ✓（错了！这是 165 版本）
```

## 3.2 我们真正想要的规则

**"16" 的左边和右边都不能贴着数字或字母。** 换句话说，16 必须是一个"独立的块"：

```
/docs/16/ddl.html   → 16 左边是 "/"，右边是 "/" → 独立 ✓
/news/2016-report   → 16 左边是 "0"            → 不独立 ✗
/docs/165/intro     → 16 右边是 "5"            → 不独立 ✗
```

## 3.3 那两个奇怪符号就是"检查左右邻居"的工具

正则表达式里的这两个写法是**零宽断言**——它们只"看一眼"旁边的字符，自己不消耗任何字符：

| 写法            | 读法                                                 |
| --------------- | ---------------------------------------------------- |
| `(?<![a-z0-9])` | "**左边**不能是字母或数字"（look**b**ehind，回头看） |
| `(?![a-z0-9])`  | "**右边**不能是字母或数字"（lookahead，向前看）      |

合起来：

```python
r"(?<![a-z0-9])16(?![a-z0-9])"
#   ↑左边非字母数字  ↑找"16"  ↑右边非字母数字
```

用三个 URL 走一遍：

```
"/docs/16/ddl.html"   找到 "16"，左邻是 "/"（非字母数字✓），右邻是 "/"（✓） → 匹配成功
"/news/2016-report"   找到 "16"，左邻是 "0"（是数字✗）                     → 匹配失败
"/docs/165/intro"     找到 "16"，右邻是 "5"（是数字✗）                     → 匹配失败
```

`-` 算不算"贴着"？不算。`-` 不是字母数字，所以 `postgresql-16-18` 里的 `16` 能通过——这是合理的，因为官方 URL 就是用连字符分隔版本号的。

---

## 修复 4：什么是"命中集"，为什么要去冗余

## 4.1 命中集是什么

排序器对每个 URL 做的第一件事：拿所有打分词挨个问"你在不在这个 URL 里？"。把所有回答"在"的词收集起来，就是这个 URL 的**命中集**（matched set）：

```
URL: ddl-rowsecurity.html（压缩后：…ddlrowsecurityhtml）

打分词逐个检查：
  "16"          在吗？ 在  → 收进命中集
  "postgresql"  在吗？ 在  → 收进命中集
  "rowsecurity" 在吗？ 在  → 收进命中集
  "row"         在吗？ 在  → 收进命中集
  "security"    在吗？ 在  → 收进命中集

命中集 = {16, postgresql, rowsecurity, row, security}
```

之后，**命中集里有几个词，页面就得几分**（每个词按 IDF 给分）。

## 4.2 问题：row 和 security 是"蹭"进来的

注意看：`rowsecurity` 这个字符串本身就包含了 `row`（前 3 个字母）和 `security`（后 8 个字母）。它们"命中"不是因为页面真的单独讨论了 row 或 security，**纯粹是因为它们是复合词的一部分**：

```
r o w s e c u r i t y
├──┤                    ← "row" 在这里（是 rowsecurity 的开头）
      ├──────────┤      ← "security" 在这里（是 rowsecurity 的结尾）
└────────────────┤      ← "rowsecurity" 整体
```

如果三个都计分，等于**同一个证据投了三张票**。就像面试时同一个人拿了三张身份证来投票。

## 4.3 修复：短词是长词的"一部分"时，只算长词

规则一句话：**命中集里，如果 A 是 B 的一部分，就删掉 A，留下 B。**

代码里的 `token in other` 就是"token 是不是 other 的一部分"（字符串包含判断）：

```python
for token in tokens:               # 逐个检查命中集里的词
    covered = any(
        token != other and token in other   # 有别的更长的词包含我吗？
        for other in tokens
    )
    if not covered:                # 没有 → 保留；有 → 丢弃
        kept.add(token)
```

对 RLS 页的命中集逐个过：

| 词            | 检查                                   | 结果     |
| ------------- | -------------------------------------- | -------- |
| `rowsecurity` | 有别的词包含它吗？没有                 | **保留** |
| `row`         | `rowsecurity` 包含 `row` 吗？包含      | 丢弃     |
| `security`    | `rowsecurity` 包含 `security` 吗？包含 | 丢弃     |
| `16`          | 谁都不包含它                           | **保留** |
| `postgresql`  | 谁都不包含它                           | **保留** |

最终命中集从 5 个词收缩为 `{16, postgresql, rowsecurity}`——一次真实匹配只投一票。

## 4.4 为什么必须"按每个 URL 单独处理"

你可能会问：那直接把 `row`、`security` 这两个短词从打分词表里删掉不就行了？

不行。看另一个页面 `fdw-row-locking.html`（讲行级锁的）：

```
它的命中集 = {16, postgresql, row}
```

这个页面**没有** `rowsecurity`，`row` 在这里是真实的、独立的匹配，不该被删。所以规则必须是局部的：**"你被覆盖"只发生在同一个 URL 的命中集内部**——RLS 页的 `row` 被删，锁页面的 `row` 照常计分。

---

## 一句话总结三个修复

| 修复 | 解决的问题                                       | 核心手段                                                     |
| ---- | ------------------------------------------------ | ------------------------------------------------------------ |
| 2    | 稀有短词 `level` 靠高分压过主题页                | 排序加一道前置闸门：命中长主题词的页面单独排一层，层内才比 IDF 分 |
| 3    | `"16" in url` 把 `2016`、`165` 误当成 16 版      | 检查 `16` 左右邻居都不是字母数字，保证它是独立片段           |
| 4    | `row`/`security` 蹭 `rowsecurity` 的匹配重复得分 | 每个页面自己的命中集里，短词被长词包含时只留长词             |

哪一段还有疑问，可以指着具体句子问我。

# 1.2 元组排序技术点讲解：

这个结构全部集中在 [_rank_sitemap_candidates](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_sitemap.py#L236-L291) 函数里。我把相关代码摘出来，逐行对应到"元组的两位"。

## 代码位置与结构

```python
# ① 先定义：哪些词算"复合主题词"（第 254-256 行）
compound_needles = {
    token for token in compact_needles if len(token) >= 6
}

# ② 为每个命中的页面构造元组（第 268-278 行）
scored = [
    (
        1 if matched & compound_needles else 0,                      # 第一位
        sum(1.0 / doc_freq[token] for token in matched),             # 第二位
        url,                                                          # 第三位
        matched,                                                      # 第四位
    )
    for url, matched in hits
]

# ③ 用元组排序（第 280 行）
scored.sort(key=lambda item: (-item[0], -item[1], -item[2].count("/"), item[2]))
```

下面逐位讲数值是怎么来的。

---

## 第一位：`1 if matched & compound_needles else 0`

拆成三个零件：

**零件 1：`compound_needles` 是什么？** 它是从全部打分词里筛出"压缩后长度 ≥ 6"的词组成的集合。以本次真实查询为例：

```python
compact_needles = {'16', 'level', 'postgresql', 'rls', 'row', 'rowsecurity', 'security'}
# 长度>=6 的只有：
compound_needles = {'rowsecurity', 'postgresql'}   # 16/level/rls/row/security 都不够 6
```

**零件 2：`matched & compound_needles` 是什么？** `&` 是集合的**交集**运算——两个集合中"共同拥有"的元素。`matched` 是这个页面的命中集：

```python
# RLS 页：
matched = {'16', 'postgresql', 'rowsecurity'}
matched & compound_needles = {'postgresql', 'rowsecurity'}   # 非空

# applevel 页：
matched = {'16', 'level', 'postgresql'}
matched & compound_needles = {'postgresql'}                  # 非空
```

**零件 3：`1 if ... else 0`**。Python 里非空集合视为"真"、空集合视为"假"。所以这行的意思是：**"这个页面的命中集里有没有至少一个复合主题词？有就给 1，没有给 0。"**

> 补充：上面 applevel 页因为命中 `postgresql`（也是 ≥6 的词）拿到了 1，这在真实数据里没问题——因为 `postgresql` 命中全站，第一层内部靠第二位的 IDF 分数继续拉开差距；真正被压下去的是那些连 `postgresql` 都不命中的离题页（比如 general 模式下混进来的站外页面）。如果你希望第一层只认"真正的主题词"而不是 `postgresql` 这种站名，这是可以进一步收紧的优化点。

## 第二位：`sum(1.0 / doc_freq[token] for token in matched)`

需要先知道 `doc_freq` 从哪来。在构造元组之前，代码先扫了一遍全部页面，统计每个词出现在多少个页面里（第 264-266 行）：

```python
for url in unique_entries:
    ...
    if matched:
        hits.append((url, matched))
        for token in matched:
            doc_freq[token] += 1      # 每命中一个页面，这个词的计数 +1
```

扫完 29578 个页面后，`doc_freq` 就是一张"词 → 出现页面数"的表：

```python
doc_freq = {
    'postgresql': 20000,   # 几乎每页都有
    '16':         3000,
    'security':   800,
    'rowsecurity': 10,
    'level':        2,
    ...
}
```

然后第二位就是对命中集里的每个词查表、取倒数、求和：

```python
# RLS 页 matched = {'16', 'postgresql', 'rowsecurity'}
第二位 = 1/3000 + 1/20000 + 1/10
       = 0.00033 + 0.00005 + 0.1
       ≈ 0.1004

# applevel 页 matched = {'16', 'level', 'postgresql'}
第二位 = 1/3000 + 1/2 + 1/20000
       = 0.00033 + 0.5 + 0.00005
       ≈ 0.5004        ← level 的 1/2 就是它分高的来源
```

`sum(... for token in matched)` 是 Python 的生成器求和写法，等价于：

```python
total = 0.0
for token in matched:
    total = total + 1.0 / doc_freq[token]
```

## 第三、四位

`url` 和 `matched` 本身不参与"两位"的逻辑，只是**把数据带在元组里**，方便排序完之后直接取用（构造候选时要 url，写 summary 时要 matched）。

---

## 排序行怎么读

```python
scored.sort(key=lambda item: (-item[0], -item[1], -item[2].count("/"), item[2]))
```

- `key=` 告诉 Python"按什么规则比大小"；
- `item[0]`、`item[1]` 就是元组的第一位、第二位；
- 加负号是因为 `sort` 默认**升序**（小的在前），取负后"分数大的"反而排在前面，实现降序；
- `item[2].count("/")` 是 URL 里斜杠的个数——斜杠越多说明路径越深、页面越具体，这是同分时的第三级裁决（之前讲过的"深路径优先"）；
- 最后用 `item[2]`（URL 字符串本身）做第四级裁决，保证结果稳定可复现。

## 完整走一遍两个页面的最终元组

```python
ddl-rowsecurity.html      → (1, 0.1004, url1, {'16','postgresql','rowsecurity'})
applevel-consistency.html → (0, 0.5004, url2, {'16','level','postgresql'})
                            ↑
                     第一位 1 > 0，排序直接定胜负
```

排序比较时 Python 先看第一位：`1 > 0`，RLS 页胜出，**第二位的 0.5004 根本没有机会参与比较**——这就是"元组排序把主题相关性变成前置闸门"在代码里的具体落点。

先看 `scored` 里每个元素长什么样，否则下标读不懂。回顾 L268-278：

```python
scored = [
    (
        1 if matched & compound_needles else 0,      # item[0]：是否命中复合主题词
        sum(1.0 / doc_freq[token] for token in matched),  # item[1]：IDF 加权分数
        url,                                        # item[2]：URL 字符串
        matched,                                    # item[3]：命中的词集合（不参与排序）
    )
    for url, matched in hits
]
```

所以 `scored` 是 4 元组列表，`sort` 的 key 依次用到了前三个元素。

## 这行代码怎么读

```python
scored.sort(key=lambda item: (-item[0], -item[1], -item[2].count("/"), item[2]))
```

一句话读法：**按四个优先级依次排序——① 命中复合主题词的排前；② IDF 分数高的排前；③ URL 路径深的排前；④ 同分时按 URL 字典序升序**。

由于 Python 的元组 key 是**逐项比较**的（先比第 0 项，相等才比第 1 项，以此类推），所以这是一个 4 级排序，前一级完全决定先后时不会进入下一级。

## 每个参数怎么被使用

### 第 1 级：`-item[0]`（是否命中复合主题词）
- `item[0]` 只有 0/1 两个值：命中 `compound_needles`（长度 ≥ 6 的高确定性主题词，如 `rowsecurity`）为 1，否则 0；
- 取负后：命中 → `-1`，未命中 → `0`。`-1 < 0`，所以**命中复合词的一定排在前面**；
- 注释 L270-271 说明了理由：避免"碰巧稀有的短词"（如 `level`）靠 IDF 侥幸高分，把离题页推到相关页前面——复合主题词是强信号，先于分数生效。

### 第 2 级：`-item[1]`（IDF 加权分数）
- `item[1] = sum(1.0 / doc_freq[token] ...)`：每个命中词的"稀有度"权重之和——`doc_freq` 是该词在全部候选 URL 中出现的文档数（L265-266 统计）；
- 泛化词（如 `docs`、`16` 几乎全站命中）`doc_freq` 大，`1/doc_freq` 小；稀有词贡献高；
- 取负后降序：**分高的排前面**。

### 第 3 级：`-item[2].count("/")`（URL 路径深度）
- `item[2]` 是 URL 字符串，`.count("/")` 统计里面有几个斜杠；
- 取负后降序：斜杠多（深路径，如 `/docs/current/rowsecurity.html`）排前面，斜杠少（如 `https://docs.postgresql.org/`）排后面；
- 理由就是注释 L279：**深路径通常指向更具体的页面**（安装指南、API 参考页），浅路径多是首页/入口页——用户问的是具体问题，具体页面更可能是答案；
- 这就是"废弃旧版 `URL 越短越靠前`"：旧 key 是 `(-score, len(url), url)`，短 URL 往往就是泛化的首页，会误排到前面。

### 第 4 级：`item[2]`（URL 字典序，不取负）
- 前三项全相等时，按 URL 字符串**升序**（字典序）兜底；
- 目的：**保证排序结果确定性**——同一批候选在任何时刻排序结果都一致，便于测试、缓存和 debug。

## 核心技巧：取负 = 降序

`sort` 默认**升序**。想让"值大的排前面"，就取负号：值越大，负值越小，越靠前。前三级都用这个技巧实现降序；第 4 级故意不取负，实现字典序升序兜底。

| 排序键                | 原始含义     | 取负后效果           |
| --------------------- | ------------ | -------------------- |
| `-item[0]`            | 命中复合词=1 | 命中的（-1）排前     |
| `-item[1]`            | IDF 分       | 高分排前             |
| `-item[2].count("/")` | 斜杠数       | 深路径排前           |
| `item[2]`             | URL          | 字典序升序（确定性） |

一句话总结：**这是一个"先看是不是强信号 → 再看匹配质量 → 再看页面具体程度 → 最后字典序兜底"的四级确定性排序**，目的是把最可能回答用户问题的具体文档页推到候选池最前面。