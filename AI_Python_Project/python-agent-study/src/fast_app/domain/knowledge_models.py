from dataclasses import dataclass


@dataclass
class KnowledgeChunk:
    id: str
    content: str
    source: str
    title: str