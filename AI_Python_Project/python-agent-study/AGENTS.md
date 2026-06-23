# AGENTS.md

## Project rules

This project is a Python / FastAPI / LangGraph / RAG Agent backend learning project.

Before doing project work, read these files in order:

1. `教学讲解规范.md`
2. `当前学习进度.md`
3. `路线执行索引.md`
4. `学习路线优先级.md`
5. `总学习路线_归档参考.md`

`总学习路线_归档参考.md` is archived reference only.

Do not replace the explicit LangGraph RAG pipeline with `create_agent()` unless the user explicitly asks and a design review has been completed.

Do not change `pipeline.stream()` from token-only. Structured streaming information should use `stream_events()`.

Do not modify `src/app` or `app` temporary learning code unless explicitly requested.

Use Windows PowerShell commands and `curl.exe` examples.

The FastAPI module is `fast_app`.

Before file-level modifications, read the real code and dependency files. If docs and code disagree, code is the source of truth.