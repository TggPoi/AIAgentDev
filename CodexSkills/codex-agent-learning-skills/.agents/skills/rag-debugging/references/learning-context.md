# AI Agent learning context

The user is systematically studying an AI Agent / RAG / backend engineering tutorial.

## User background

- Has Java backend experience and MySQL framework experience.
- Has C++ / Unreal Engine experience.
- Is transitioning toward AI Agent / RAG / backend / systems engineering.
- Wants to understand why each technical point exists, the underlying mechanism, engineering design choices, and how to independently modify/debug later.

## Answer style

- Chinese.
- Start headings from `##`; do not use first-level headings.
- Prefer: main line -> knowledge map -> module breakdown -> details -> examples -> summary.
- For code: input -> what this step does -> output -> why designed this way.
- Use Mermaid for diagrams.
- If key files are missing, ask for them explicitly.

## Completed learning state

The user has completed tutorial chapters through Chapter 28.

Key mastered topics:
- LangChain tools, MCP, RAG, Milvus, Memory, Output Parser, Prompt Template, Runnable/LCEL.
- Nest basics: Module, Controller, Service, Provider, useFactory, inject, third-party API providers.
- Scheduled jobs in Nest: cron/every/at, SchedulerRegistry, Job services.
- ASR / AI streaming / TTS architecture: FileInterceptor, SSE, WebSocket, MediaSource, EventEmitter, TtsRelayService.
- AGUI / AI SDK stream UI and minimal React concepts: state, hooks, useState.
- LangGraph: State, Partial<State>, Annotation, reducer/default, StateGraph, START/END, MemorySaver/thread_id, interrupt, MessagesAnnotation, ToolNode, toolsCondition.
- Advanced RAG / Agentic RAG / multi-hop RAG.
- Docker: Image, Container, Dockerfile, multi-stage build, Compose, dev/prod environments, localhost vs service name.
- Elasticsearch: index/document/field/mapping, text/keyword, match/term, inverted index, IK analyzer, BM25.
- Hybrid retrieval: ES + Milvus + query augmentation + merge/dedupe + rerank.
- Neo4j / GraphRAG: Node, Label, Property, Relationship, direction, Cypher, driver calls, natural language -> Cypher -> graph query -> answer.

Important recurring mistakes / friction:
- Docker proxy and Dockerfile copied hidden characters.
- ES client/server version mismatch: @elastic/elasticsearch 9.x with ES 8.x causes compatible-with=9 error.
- React/frontend APIs need beginner-friendly explanations.
- Need explicit explanation of unfamiliar browser APIs and events.
