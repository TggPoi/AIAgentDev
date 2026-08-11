"""诊断单个 case 的检索链路：打印各阶段召回文档的逻辑身份与得分。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

CASE_ID = sys.argv[1] if len(sys.argv) > 1 else "reader_visibility_positive"
USER = sys.argv[2] if len(sys.argv) > 2 else "rbac_reader"

os.environ["RAG_PIPELINE_PROVIDER"] = "rag_agent"

KEYS = json.loads(
    Path(".tmp/rag_eval_api_keys.json").read_text(encoding="utf-8")
)
os.environ["RAG_EVAL_API_KEY"] = KEYS[USER]["api_key"]


async def main() -> None:
    from fast_app.core.config import get_settings
    from fast_app.evaluation.cases.loader import load_eval_dataset
    from fast_app.main import app
    from fast_app.rag_eval.target import InProcessStructuredStreamTarget, RagEvalAuth

    settings = get_settings()
    dataset = load_eval_dataset(
        Path("src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.0.json"),
        verify_source_revision=True,
        repository_root=Path.cwd(),
    )
    case = next(c for c in dataset.cases if c.case_id == CASE_ID)
    print("question:", case.question)
    print("expected logical_chunk_ids:", case.relevant_logical_chunk_ids)

    auth = RagEvalAuth.from_environment(settings)
    target = InProcessStructuredStreamTarget(
        app=app,
        settings=settings,
        pipeline_provider="rag_agent",
        auth=auth,
    )
    async with app.router.lifespan_context(app):
        execution = await target.execute(case)

    stream = execution.stream
    print("route_intent:", stream.route_intent)
    print("knowledge_retrieval_performed:", execution.knowledge_retrieval_performed)
    stages = execution.snapshot.payload.retrieval_stages
    for stage_name, stage in stages.items():
        print(f"\n=== stage: {stage_name} ({len(stage.documents)} docs) ===")
        for doc in stage.documents:
            logical = getattr(doc, "logical_chunk_id", None)
            doc_id = getattr(doc, "doc_id", None)
            score = getattr(doc, "score", None)
            text = (getattr(doc, "text", "") or "")[:80].replace("\n", " ")
            mark = ""
            if logical in case.relevant_logical_chunk_ids:
                mark = " <<<< GOLDEN"
            print(
                f"  {logical} | doc={doc_id} | score={score} | {text}{mark}"
            )
    answer = stream.answer or ""
    print("\nanswer:", answer[:500])


if __name__ == "__main__":
    asyncio.run(main())
