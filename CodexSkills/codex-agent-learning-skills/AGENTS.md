# AGENTS.md

## Project-level guidance

Use the skills in `.agents/skills` when the user's request matches their descriptions.

Important user preferences:
- Respond in Chinese unless explicitly requested otherwise.
- Do not use first-level Markdown headings. Start headings from `##`.
- Prefer a teaching structure: main line -> knowledge map -> categories/modules -> details -> examples -> summary.
- For code explanations, use the data-flow structure: input -> what this step does -> output -> why designed this way.
- Use Mermaid diagrams when explaining architecture, workflows, graph relationships, or data flows.
- If key source files or context are missing, say what is missing instead of guessing.
- The user is learning AI Agent / RAG / backend engineering and values engineering reasoning over shallow definitions.

Skill usage suggestions:
- Use `agent-tutorial-study-coach` for new tutorial chapters and learning plans.
- Use `code-dataflow-explainer` for code walkthroughs.
- Use `rag-debugging` for RAG, ES, Milvus, rerank, retrieval, or hallucination issues.
- Use `graphrag-cypher-generation` for Neo4j / Cypher / GraphRAG tasks.
- Use `agent-skill-design-review` for Skill design and refactoring tasks.
