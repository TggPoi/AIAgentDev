"""离线验证 Direct Web 页面正文提取的择优、噪声剥离与空正文回退语义。"""

from fast_app.services.rag.direct_web_page_text import (
    MIN_USEFUL_TEXT_CHARS,
    extract_page_text,
)


LONG_ARTICLE_TEXT = (
    "PostgreSQL 行级安全策略允许数据库管理员为表配置访问策略，"
    "使得每个用户在执行查询时只能看到符合策略条件的行。" * 5
)
SHORT_CARD_TEXT = "相关推荐：另一篇文章的标题和简短摘要。"


def test_multiple_articles_pick_longest() -> None:
    """多个 <article> 时选文本最长的块，短推荐卡片不再压过正文。"""

    html = (
        "<html><body>"
        f"<article><p>{SHORT_CARD_TEXT}</p></article>"
        f"<article><p>{LONG_ARTICLE_TEXT}</p></article>"
        "</body></html>"
    )
    text = extract_page_text(html)
    assert "行级安全策略" in text, "应选中长正文块"
    assert "相关推荐" not in text, "短卡片内容不应混入结果"


def test_noise_tags_are_stripped() -> None:
    """aside/form/注释等噪声在正文内被剥离。"""

    html = (
        "<html><body><article>"
        "<aside class='toc'>目录：第一章 第二章 第三章</aside>"
        "<form><input placeholder='订阅邮件'>订阅我们</form>"
        "<!-- 骨架占位：loading skeleton -->"
        f"<p>{LONG_ARTICLE_TEXT}</p>"
        "</article></body></html>"
    )
    text = extract_page_text(html)
    assert "行级安全策略" in text
    assert "目录：第一章" not in text, "aside 侧边栏应被剥离"
    assert "订阅我们" not in text, "form 噪声应被剥离"
    assert "skeleton" not in text, "HTML 注释应被剥离"


def test_spa_skeleton_returns_empty() -> None:
    """SPA 骨架页（body 文本不足门槛）返回空串，触发摘要回退。"""

    html = (
        "<html><body><div id='app'>Loading...</div>"
        "<script>var app = bootstrap();</script></body></html>"
    )
    text = extract_page_text(html)
    assert text == "", f"骨架页应返回空串，实际：{text!r}"


def test_short_article_falls_back_to_body() -> None:
    """article 块过短时降级取 body 长文本。"""

    html = (
        "<html><body>"
        f"<article><p>{SHORT_CARD_TEXT}</p></article>"
        f"<div id='content'>{LONG_ARTICLE_TEXT}</div>"
        "</body></html>"
    )
    text = extract_page_text(html)
    assert "行级安全策略" in text, "应降级到 body 层长文本"


def test_no_container_returns_empty() -> None:
    """无 article/main/body 标签时返回空串。"""

    html = f"<div class='root'>{LONG_ARTICLE_TEXT}</div>"
    text = extract_page_text(html)
    assert text == "", "无容器标签应返回空串"


def test_threshold_constant() -> None:
    """门槛值回归锚点，调整需同步评估回退行为。"""

    assert MIN_USEFUL_TEXT_CHARS == 200


if __name__ == "__main__":
    test_multiple_articles_pick_longest()
    test_noise_tags_are_stripped()
    test_spa_skeleton_returns_empty()
    test_short_article_falls_back_to_body()
    test_no_container_returns_empty()
    test_threshold_constant()
    print("test_direct_web_page_text: 全部通过")
