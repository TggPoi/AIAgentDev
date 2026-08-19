from __future__ import annotations

import tiktoken


class TiktokenCounter:
    """确定性的本地预算计数器；字符硬上限继续承担模型 tokenizer 差异兜底。

    全工程统一使用这一把尺子：Markdown 父子分块、Office 文档切块、
    RAG 上下文拼装都必须基于同一口径，保证 token_count 处处可比。
    """

    def __init__(self) -> None:
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            # ponytail: tiktoken 首次运行可能需要下载词表；离线部署先用保守字符预算，
            # 预热 TIKTOKEN_CACHE_DIR 后会自动恢复真实 BPE 计数。
            self.encoding = None

    def count(self, text: str) -> int:
        if self.encoding is not None:
            return len(self.encoding.encode(text))
        ascii_count = sum(ord(char) < 128 for char in text)
        return ascii_count // 4 + len(text) - ascii_count

    def split(self, text: str, max_tokens: int) -> list[str]:
        if self.encoding is None:
            # 中文按一字符一 token 保守处理，英文窗口乘四；混合文本宁可多切。
            window = max(1, max_tokens)
            return [
                text[index : index + window].strip()
                for index in range(0, len(text), window)
                if text[index : index + window].strip()
            ]
        tokens = self.encoding.encode(text)
        return [
            self.encoding.decode(tokens[index : index + max_tokens]).strip()
            for index in range(0, len(tokens), max_tokens)
            if tokens[index : index + max_tokens]
        ]


__all__ = ["TiktokenCounter"]
