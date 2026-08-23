"""对比 cl100k_base / o200k_base / Qwen 官方 tokenizer 的 token 计数差异。"""
import tiktoken
from transformers import AutoTokenizer

cn = "知识库文档同步机制通过五个要素进行增量比对：内容哈希、权限哈希、解析器版本、分块策略版本和分块配置指纹。任何一项不一致都会触发该文档的重新分块与入库。"
en = "The incremental synchronization pipeline compares five identity elements before deciding whether a document must be re-chunked and re-indexed in both stores."
mixed = "RAG 检索采用 parent-child 双层分块：子块 target 260 tokens 用于 embedding 召回，父块 target 900 tokens 用于上下文拼装，预算上限 3000 tokens。"

samples = {"纯中文": cn, "纯英文": en, "中英混合": mixed}

encoders = {
    "cl100k_base": tiktoken.get_encoding("cl100k_base"),
    "o200k_base": tiktoken.get_encoding("o200k_base"),
}
qwen = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B")

print(f"{'样本':<8}{'cl100k':>8}{'o200k':>8}{'qwen':>8}{'o200k/qwen':>12}{'cl100k/qwen':>13}")
for name, text in samples.items():
    c = len(encoders["cl100k_base"].encode(text))
    o = len(encoders["o200k_base"].encode(text))
    q = len(qwen.encode(text))
    print(f"{name:<10}{c:>8}{o:>8}{q:>8}{o / q:>12.3f}{c / q:>13.3f}")
