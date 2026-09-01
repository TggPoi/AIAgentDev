"""构建绑定当前重建语料快照的 V2.1.3 candidate 评测集。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fast_app.evaluation.cases.loader import (
    compute_directory_source_revision,
    load_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import RagEvalDataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE_DIR = "docs/knowledge-base-acl-test"
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.3.json"
)
DATASET_VERSION = "2.1.3"
CREATED_AT = "2026-08-28T16:00:00+08:00"
SOURCE_REVISION = (
    "sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167"
)
ANNOTATED_BY = "codex:v2.1.3-current-corpus-designer"
READER_ID = "user_rp-iYI84UD1vMXH039AGHYQz"
OPERATOR_ID = "user_MBeEmT7K2eGguofW4CZ1aGTp"


DOCS: dict[str, dict[str, str]] = {
    "word_toon": {
        "doc_id": "doc_aacae76309d38da9",
        "source_revision": (
            "48b024bbe0cf05a681615da7bbcda353c1d83fd47d4fbc44bb0ae18c261756bf"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/development/"
            "UE5.8.1_二次元卡通渲染零基础学习手册.docx"
        ),
    },
    "pdf_return": {
        "doc_id": "doc_07aa7d96f0e95fd9",
        "source_revision": (
            "8048a6340bf6728fecaa37dea494333a1db4bb0d66615f3136cd24ee42b7a282"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/development/"
            "UE5.8.1_回归学习手册_图解增强版.pdf"
        ),
    },
    "deployment": {
        "doc_id": "doc_0d8f2203acdebd05",
        "source_revision": (
            "fe98686fe312eeadbef42a9a6a29a536200846beeccc3b1bcc6fcf99fa6993a9"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/development/rag-backend-deployment.md"
        ),
    },
    "assets": {
        "doc_id": "doc_570ac386aa95cc44",
        "source_revision": (
            "5ee52eecb7aa9d62cd4df97c9ee064c0ab4758f15a52b1cb07842d7130c85295"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/development/"
            "游戏开发资产列表_RAG测试.xlsx"
        ),
    },
    "combat_dev": {
        "doc_id": "doc_24f9024466249c44",
        "source_revision": (
            "b0b51cfadc0c92aacd8186ad334eb40a92de2d4736bcfdb75ad472f680a872f6"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/development/"
            "UE5战斗系统程序架构设计_RAG测试.md"
        ),
    },
    "public": {
        "doc_id": "doc_189ae0f93483e18d",
        "source_revision": (
            "25cc83eb78525b33aa0efc929eb1c9acac9039af55a7ed6b05880142611597aa"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/public/project-overview.md"
        ),
    },
    "art": {
        "doc_id": "doc_c0ff151b2e523735",
        "source_revision": (
            "fafa020e5ffbf05eaf3d9c561268e786672944e0494b9fc8e831367c0100e24b"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/art/character-art-style.md"
        ),
    },
    "combat_product": {
        "doc_id": "doc_586ef0c6400cb8c8",
        "source_revision": (
            "af915eb2de1cfb6c28fcace60b02257d4e264f4434265388e03a74facff4d491"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/product_planning/combat-design.md"
        ),
    },
    "combat_pptx": {
        "doc_id": "doc_81ba7c85ae484df0",
        "source_revision": (
            "2ba3b1cf0f484f39df8ab377844c691a0ed1186e0173068164de144337e20229"
        ),
        "source_path": (
            "docs/knowledge-base-acl-test/product_planning/"
            "UE5战斗系统设计方案_RAG测试用PPT.pptx"
        ),
    },
}


def fact(fact_id: str, text: str, *, critical: bool = False) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "text": text,
        "weight": 1.0,
        "critical": critical,
    }


def expected_source(
    doc_key: str,
    chunk_ids: list[str],
    section_keywords: list[str],
    *,
    parent_id: str | None = None,
) -> dict[str, Any]:
    document = DOCS[doc_key]
    return {
        "logical_doc_id": document["doc_id"],
        "source_revision": document["source_revision"],
        "logical_chunk_ids": chunk_ids,
        "logical_parent_id": parent_id,
        "matched_logical_child_ids": chunk_ids if parent_id else [],
        "source_path": document["source_path"],
        "section_keywords": section_keywords,
    }


def answerable_case(
    *,
    case_id: str,
    question: str,
    principal_id: str,
    sources: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    intent: str,
    keywords: list[str],
    tags: list[str] | None = None,
    top_k: int = 5,
    candidate_k: int = 10,
    filters: dict[str, Any] | None = None,
    note: str = "",
    parent_ids: list[str] | None = None,
) -> dict[str, Any]:
    relevant_chunks = [
        chunk_id
        for source in sources
        for chunk_id in source["logical_chunk_ids"]
    ]
    relevant_docs = list(
        dict.fromkeys(source["logical_doc_id"] for source in sources)
    )
    parent_ids = parent_ids or []
    return {
        "case_id": case_id,
        "dataset_version": DATASET_VERSION,
        "metric_profile": "rag",
        "question": question,
        "answerable": True,
        "expected_route": "rag_answer",
        "eval_principal_id": principal_id,
        "knowledge_version": 0,
        "source_revision": SOURCE_REVISION,
        "mode": "hybrid",
        "top_k": top_k,
        "candidate_k": candidate_k,
        "min_score": 0.0,
        "filters": filters or {},
        "retrieval_relevance_unit": (
            "logical_parent" if parent_ids else "logical_chunk"
        ),
        "relevant_logical_chunk_ids": relevant_chunks,
        "relevant_logical_parent_ids": parent_ids,
        "relevant_doc_ids": relevant_docs,
        "authoritative_logical_chunk_ids": (
            [] if parent_ids else relevant_chunks
        ),
        "authoritative_logical_parent_ids": parent_ids,
        "forbidden_logical_chunk_ids": [],
        "expected_sources": sources,
        "required_key_facts": facts,
        "question_intent": intent,
        "constraints": ["只根据当前评测身份可见的知识库证据回答"],
        "hard_gate_labels": ["critical_fact_missing"],
        "scenario_tags": tags or ["answerable"],
        "expected_answer_keywords": keywords,
        "forbidden_answer_keywords": [],
        "annotation_method": "model_assisted",
        "annotated_by": ANNOTATED_BY,
        "review_status": "pending_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": "等待 human:TGG 对问题、qrels 和关键事实进行人工审核。",
        "note": note,
    }


def no_answer_case(
    *,
    case_id: str,
    question: str,
    forbidden_chunks: list[str],
    forbidden_keywords: list[str],
    tags: list[str],
    intent: str,
    note: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "dataset_version": DATASET_VERSION,
        "metric_profile": "rag",
        "question": question,
        "answerable": False,
        "expected_route": "rag_no_answer",
        "eval_principal_id": READER_ID,
        "knowledge_version": 0,
        "source_revision": SOURCE_REVISION,
        "mode": "hybrid",
        "top_k": 5,
        "candidate_k": 10,
        "min_score": 0.0,
        "filters": {},
        "retrieval_relevance_unit": "logical_chunk",
        "relevant_logical_chunk_ids": [],
        "relevant_logical_parent_ids": [],
        "relevant_doc_ids": [],
        "authoritative_logical_chunk_ids": [],
        "authoritative_logical_parent_ids": [],
        "forbidden_logical_chunk_ids": forbidden_chunks,
        "expected_sources": [],
        "required_key_facts": [],
        "question_intent": intent,
        "constraints": [
            "只根据当前评测身份可见的知识库证据回答",
            "缺少可见证据时必须明确说明无法从知识库确认",
        ],
        "hard_gate_labels": ["acl_no_leak"] if forbidden_chunks else [],
        "scenario_tags": tags,
        "expected_answer_keywords": [],
        "forbidden_answer_keywords": forbidden_keywords,
        "annotation_method": "model_assisted",
        "annotated_by": ANNOTATED_BY,
        "review_status": "pending_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": "等待 human:TGG 对不可回答边界进行人工审核。",
        "note": note,
    }


def build_cases() -> list[dict[str, Any]]:
    cases = [
        answerable_case(
            case_id="reader_word_face_outline_debugging",
            question=(
                "二次元渲染手册列出的 Face SDF 与 Outline 常见错误有哪些，"
                "排查时应按什么单变量顺序逐步恢复系统？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "word_toon",
                    [
                        "chunk_e580786f64c96bf7",
                        "chunk_56c46c48dae35a45",
                        "chunk_9dc18e783095bd13",
                    ],
                    ["7.3 Face SDF", "7.4 Outline", "7.5 单变量原则"],
                )
            ],
            facts=[
                fact(
                    "face_sdf_errors",
                    "Face SDF 常见错误包括头部方向向量坐标空间错误、左右 SDF 翻转错误、UV/纹理导入导致采样失真，以及真实投影和 SDF 阴影叠加。",
                    critical=True,
                ),
                fact(
                    "outline_errors",
                    "Outline 常见错误包括近远线宽不一致、Backface Shell 裂缝、TAA/TSR 抖动和远景环境描边噪声。",
                    critical=True,
                ),
                fact(
                    "single_variable_order",
                    "调试顺序是先关闭后处理和复杂 GI，只看基础 Toon，再加入 Face SDF、Outline，最后恢复场景照明。",
                    critical=True,
                ),
            ],
            intent="综合查询 Face SDF、Outline 的故障清单和单变量调试顺序。",
            keywords=["坐标空间", "SDF 翻转", "TAA/TSR", "单变量"],
            note="Word 长文档跨三个相邻章节的多 Chunk 完整性 Case。",
        ),
        answerable_case(
            case_id="reader_word_six_week_acceptance",
            question=(
                "二次元卡通渲染手册的六周学习计划每周产出是什么，"
                "六周后的最低验收项目又要求达到哪些效果？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "word_toon",
                    ["chunk_2854cb6729bca647", "chunk_aa4216b2f5630d34"],
                    ["第 8 部分 六周学习计划", "8.2 最低验收项目"],
                )
            ],
            facts=[
                fact(
                    "weekly_outputs",
                    "第 1 至 6 周依次产出基础材质实验、材质数学与实例、Cel/Rim/Outline、Face SDF 与头发、官方 Toon 对比，以及整合后的性能检查。",
                    critical=True,
                ),
                fact(
                    "character_acceptance",
                    "最低验收角色必须包含 2~3 段 Toon Lighting、Face SDF、独立头发高光、稳定 Outline 和可读眼睛。",
                    critical=True,
                ),
                fact(
                    "environment_build_acceptance",
                    "还要在白天、黄昏、阴天三种环境光下工作，并在 Development Build 正确显示且能解释各模块用途。",
                    critical=True,
                ),
            ],
            intent="查询六周学习路线的阶段产出和最终验收口径。",
            keywords=["第 6 周", "Face SDF", "三种环境光照", "Development Build"],
            note="Word 长文档中计划章节与验收章节的联合回答 Case。",
        ),
        answerable_case(
            case_id="reader_pdf_companion_ai_guard",
            question=(
                "回归手册建议怎样把传统 Gameplay AI、StateTree 与 Neural Policy 分层，"
                "模型输出非法或模型不可用时由什么机制兜底？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "pdf_return",
                    [
                        "chunk_c2b4f00cc5881d6e",
                        "chunk_de6eafe9f0278d00",
                        "chunk_1aacfb4570bf0fbe",
                        "chunk_5237f6b9758968d7",
                    ],
                    ["Page 18 StateTree", "Page 20 Companion 分层", "Page 21 fallback"],
                )
            ],
            facts=[
                fact(
                    "layer_responsibility",
                    "传统 Gameplay AI 负责规则边界，StateTree 表达宏观状态，Neural Policy 只在有限状态内产生高层 Action Intent。",
                    critical=True,
                ),
                fact(
                    "runtime_chain",
                    "推荐链路是 Player Model 到 5~10 Hz Neural Policy，再到 Action Intent、StateTree/Gameplay Guard，最后驱动 Ability、Navigation 和 Animation。",
                    critical=True,
                ),
                fact(
                    "guard_fallback",
                    "Gameplay Guard 拒绝非法动作，模型不可用时由 StateTree 或 Rule Policy 提供 fallback。",
                    critical=True,
                ),
            ],
            intent="查询 Companion AI 的分层职责、执行链和确定性兜底。",
            keywords=["StateTree", "Neural Policy", "Gameplay Guard", "Rule Policy"],
            note="PDF 跨页文本连续块 Case，重点验证分页分块后的事实拼接。",
        ),
        answerable_case(
            case_id="reader_pdf_nne_training_runtime",
            question=(
                "Learning Agents、Python/PyTorch 与 NNE 在训练和运行阶段各负责什么，"
                "自定义模型从训练到 UE 推理的推荐链路是什么？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "pdf_return",
                    [
                        "chunk_dfec29f8331e1bd6",
                        "chunk_c80e0436eac5de05",
                        "chunk_1aacfb4570bf0fbe",
                    ],
                    ["Page 19 Learning Agents/NNE", "Page 20 NNE Runtime"],
                )
            ],
            facts=[
                fact(
                    "learning_agents_role",
                    "Learning Agents 适合快速做 imitation/PPO 实验，但 Observation、Action、Reward 和模型结构应保持引擎无关。",
                    critical=True,
                ),
                fact(
                    "training_runtime_chain",
                    "自定义模型由 PyTorch 训练并导出 ONNX，再导入 NNE Model Data，通过 NNE 的 CPU/GPU/RDG Runtime 在 UE 中推理。",
                    critical=True,
                ),
                fact(
                    "responsibility_split",
                    "PyTorch 负责训练，UE/NNE 负责运行模型；复杂 Transformer、Offline RL 或自定义 Loss 由 PyTorch 主导。",
                    critical=True,
                ),
            ],
            intent="区分训练基础设施、Python 训练和 UE 模型运行的职责。",
            keywords=["Imitation", "PyTorch", "ONNX", "NNE"],
            note="PDF 跨页且包含图像解析文本的多 Chunk Case。",
        ),
        answerable_case(
            case_id="reader_pdf_mover_migration",
            question=(
                "从 UE5.5 迁移到 5.8.1 时，正式项目应如何选择 CharacterMovementComponent 与 Mover，"
                "为什么不能因为 Mover 出现就判定 CMC 已过时？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "pdf_return",
                    [
                        "chunk_00499a8f184e0ffd",
                        "chunk_50f5a64967ad9d11",
                        "chunk_f67c617af929dfce",
                        "chunk_0c20779a4e397e0d",
                    ],
                    ["Page 22 Mover", "Page 26 迁移矩阵", "Page 27 误判"],
                )
            ],
            facts=[
                fact(
                    "maturity",
                    "Mover 在 5.8.1 仍是 Experimental，API、属性和数据格式可能变化；CMC 成熟且仍会继续支持。",
                    critical=True,
                ),
                fact(
                    "project_choice",
                    "正式原型继续使用 CharacterMovementComponent 或自定义 Movement Mode，Mover 只在独立小地图验证。",
                    critical=True,
                ),
                fact(
                    "migration_rule",
                    "新系统出现不等于旧系统过时，迁移矩阵仍要求正式项目继续使用 CMC。",
                    critical=True,
                ),
            ],
            intent="查询 CMC/Mover 的成熟度、迁移策略和误判纠正。",
            keywords=["Experimental", "CharacterMovementComponent", "独立小地图"],
            note="PDF 跨第 22、26、27 页的迁移决策 Case。",
        ),
        answerable_case(
            case_id="reader_pdf_performance_workflow",
            question=(
                "回归手册如何定义 60 FPS 的帧预算和最小性能定位流程，"
                "并建议用什么固定回归路线及优化顺序避免凭感觉调优？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "pdf_return",
                    [
                        "chunk_2bb0f60692f8a56c",
                        "chunk_a23b10b3c3530f50",
                        "chunk_c02d631ae39cf2bb",
                        "chunk_436a0ab36656305a",
                    ],
                    ["Page 23 Frame Budget", "Page 24 性能风险", "Page 25 回归路线"],
                )
            ],
            facts=[
                fact(
                    "frame_budget",
                    "60 FPS 对应每帧 16.67 ms，最终帧率由 Game、Render、GPU 中最慢路径决定，不能把各线程时间简单相加。",
                    critical=True,
                ),
                fact(
                    "profiling_order",
                    "先用 stat unit 判断 Game/Render/GPU 方向，再用 Unreal Insights 或 GPU Profiler 定位具体任务或 Pass。",
                    critical=True,
                ),
                fact(
                    "regression_route",
                    "固定路线应覆盖地面城镇、最大速度穿越森林、高空俯视、跨 Streaming 区域、降落和多敌人/VFX 战斗。",
                ),
                fact(
                    "optimization_order",
                    "优化顺序从内容预算、Scalability、LOD/HLOD、Shader、Tick/AI/Animation、Streaming/引用到 C++ 热点和 Engine Config，最后才考虑改引擎源码。",
                    critical=True,
                ),
            ],
            intent="查询帧预算、定位工具、回归路径和优化优先级。",
            keywords=["16.67 ms", "stat unit", "Unreal Insights", "Engine Source"],
            note="PDF 多页综合问答，检验答案完整性和上下文利用。",
        ),
        answerable_case(
            case_id="reader_longdocs_toon_production_multi_source",
            question=(
                "两份 UE5.8.1 长手册对官方 Toon Shader 的能力、局限和成熟度有什么共同判断，"
                "正式项目推荐采用怎样的可回退生产路线？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "word_toon",
                    [
                        "chunk_6f31fe460a4ff15b",
                        "chunk_6943a61c17523604",
                        "chunk_e5ec8dd05af050cd",
                    ],
                    ["5.1 官方 Toon", "5.6 Hybrid", "6.5 决策标准"],
                ),
                expected_source(
                    "pdf_return",
                    [
                        "chunk_9168f669a931b580",
                        "chunk_519c11634c2ef350",
                        "chunk_6fb6c9494ea6327d",
                    ],
                    ["Page 9 Substrate", "Page 10 Toon Shader", "Page 11 Anime Pipeline"],
                ),
            ],
            facts=[
                fact(
                    "official_capability",
                    "官方 Toon 基于 Substrate NPR，支持本地光、Sky Light、Lumen GI、Toon Profile/Ramp、各向异性高光和 Hatching。",
                    critical=True,
                ),
                fact(
                    "not_one_click",
                    "它只是官方 NPR 光照入口，不会自动解决 Face SDF、头发高光、Outline、后处理、灯光和资产协作。",
                    critical=True,
                ),
                fact(
                    "maturity_fallback",
                    "Toon 仍是 Experimental，Substrate 文档口径也要求谨慎，因此核心角色模块必须保持可替换并保留自定义材质 fallback。",
                    critical=True,
                ),
                fact(
                    "hybrid_route",
                    "推荐 Hybrid：角色使用专用 Anime Material/Face SDF/头发高光/轮廓，环境保留 Stylized PBR，另设官方 Toon 技术验证分支。",
                    critical=True,
                ),
            ],
            intent="综合两份长文档判断官方 Toon 的能力边界和生产技术路线。",
            keywords=["Experimental", "Face SDF", "Hybrid", "fallback"],
            tags=["answerable", "multiple_relevant_sources"],
            note="跨 DOCX/PDF 的多来源 Case，长文档是新评测集核心证据。",
        ),
        answerable_case(
            case_id="reader_deployment_env_parent_expansion",
            question=(
                "RAG 后端部署规范中的环境变量章节要求配置哪些服务类别，"
                "并对认证密钥和 Elasticsearch 客户端提出了哪些注意事项？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "deployment",
                    ["chunk_ac5579214b6a604d", "chunk_c4c06a13c5280044"],
                    ["4. 环境变量配置"],
                    parent_id="parent_8203549515f66e1b",
                )
            ],
            facts=[
                fact(
                    "configuration_groups",
                    "配置覆盖应用日志、认证/JWT、PostgreSQL、Milvus、Elasticsearch、LLM、Embedding 和 Rerank Provider。",
                    critical=True,
                ),
                fact(
                    "auth_requirements",
                    "JWT_SECRET_KEY 和 API_KEY_PEPPER 不得为空，AUTH_ENABLED=true 时受保护接口必须携带有效认证信息。",
                    critical=True,
                ),
                fact(
                    "es_compatibility",
                    "Elasticsearch Python 客户端版本必须与 Docker 服务版本保持一致。",
                    critical=True,
                ),
            ],
            intent="查询环境变量父章节的配置范围和安全/兼容性注意事项。",
            keywords=["JWT_SECRET_KEY", "API_KEY_PEPPER", "Milvus", "Elasticsearch"],
            tags=["answerable", "parent_expansion"],
            parent_ids=["parent_8203549515f66e1b"],
            note="两个 Markdown 子块应扩展为同一个完整父块，并按父块逻辑身份计分。",
        ),
        answerable_case(
            case_id="reader_xlsx_perfect_block_asset",
            question=(
                "资产清单中的 AST-0022 完美格挡火花位于什么路径、当前状态和优先级是什么，"
                "格式及性能限制有哪些？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "assets",
                    ["chunk_59d89c39b0ad2fb6"],
                    ["资产清单 Row 23", "AST-0022"],
                )
            ],
            facts=[
                fact(
                    "identity_path",
                    "AST-0022 是完美格挡火花，路径为 /Game/VFX/Combat/NS_Perfect_Block。",
                    critical=True,
                ),
                fact(
                    "status_priority_format",
                    "该资产状态为待采购、优先级 P1、格式为 Niagara + uasset。",
                    critical=True,
                ),
                fact(
                    "performance_limits",
                    "需要限制 GPU 粒子数量和 Overdraw，并为主机平台设置单独质量档位。",
                    critical=True,
                ),
            ],
            intent="查询 XLSX 单行资产的精确结构化字段和性能约束。",
            keywords=["AST-0022", "NS_Perfect_Block", "待采购", "Overdraw"],
            note="XLSX 精确行级检索 Case。",
        ),
        answerable_case(
            case_id="reader_combat_perfect_block",
            question=(
                "程序架构文档规定完美格挡成功后会产生哪些效果，"
                "判定窗口应由什么控制且不应该怎样实现？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "combat_dev",
                    ["chunk_afe53a82b6a0d200"],
                    ["14.3 完美格挡"],
                )
            ],
            facts=[
                fact(
                    "success_effects",
                    "成功后伤害降为零、返还部分精力、攻击者硬直，并触发慢动作、摄像机震动、专用特效和音效。",
                    critical=True,
                ),
                fact(
                    "window_control",
                    "完美格挡窗口由技能时间轴或动画通知控制。",
                    critical=True,
                ),
                fact(
                    "forbidden_tick_design",
                    "不应在 Tick 中用多个时间判断分支实现窗口。",
                    critical=True,
                ),
            ],
            intent="查询完美格挡的成功效果和时间窗口实现约束。",
            keywords=["伤害降为零", "技能时间轴", "动画通知", "Tick"],
            note="Development Markdown 精确章节 Case。",
        ),
        answerable_case(
            case_id="reader_public_acl_underfilled",
            question=(
                "公开文档被错误写成 allowed_departments=[\"public\"] 会造成什么问题，"
                "如果只有 Elasticsearch 支持 public 过滤又会怎样，正确规则是什么？"
            ),
            principal_id=READER_ID,
            sources=[
                expected_source(
                    "public",
                    ["chunk_9306991da46132c3", "chunk_aa8db320ce8941f2"],
                    ["10.1 public 文档", "10.2 Elasticsearch public 过滤"],
                )
            ],
            facts=[
                fact(
                    "public_visibility",
                    "public 文档应设置 visibility=public，而不是把 public 当作部门写入 allowed_departments。",
                    critical=True,
                ),
                fact(
                    "department_mismatch",
                    "错误的 allowed_departments=[public] 会让系统尝试匹配名为 public 的用户部门，导致正常部门用户无法读取公开文档。",
                    critical=True,
                ),
                fact(
                    "hybrid_consistency",
                    "只在 Elasticsearch 支持 public 会造成 Hybrid 结果不一致，Milvus 与 Elasticsearch 必须使用同一权限规则。",
                    critical=True,
                ),
            ],
            intent="查询公开文档 ACL 的两类错误及跨检索源一致规则。",
            keywords=["visibility", "allowed_departments", "Milvus", "Elasticsearch"],
            tags=["answerable", "permission_filter", "underfilled_k"],
            top_k=20,
            candidate_k=20,
            filters={"source_path": DOCS["public"]["source_path"]},
            note="当前 public 文档只有 16 个有效子块，source_path 限定且 top_k=20，构成确定性 underfilled_k。",
        ),
        no_answer_case(
            case_id="reader_art_acl_negative",
            question="art 部门内部测试关键词中的“月光披风规则”和“女巫帽轮廓标准”分别是什么？",
            forbidden_chunks=["chunk_36c26dd9a52eeb3d"],
            forbidden_keywords=["月光披风规则", "女巫帽轮廓标准"],
            tags=["unanswerable", "permission_filter"],
            intent="验证 development Reader 不能读取 art 部门内部关键词。",
            note="相关 art Chunk 对 Reader 不可见；如被检索或复述即为 ACL 泄漏。",
        ),
        no_answer_case(
            case_id="reader_no_result_wwise_audio",
            question=(
                "知识库是否规定了 Wwise 语音聊天回声消除参数和音频 Profiler 的验收阈值？"
            ),
            forbidden_chunks=[],
            forbidden_keywords=["AEC 阈值为", "Wwise Profiler 必须低于"],
            tags=["unanswerable", "no_result"],
            intent="验证知识库完全没有 Wwise 语音聊天和音频性能阈值证据时的保守拒答。",
            note="当前 9 份文档均未定义 Wwise、语音回声消除或音频 Profiler 验收阈值。",
        ),
        answerable_case(
            case_id="operator_art_pixel_sprite",
            question="角色美术规范中像素 Sprite 的核心原则、制作要求和二级运动顺序是什么？",
            principal_id=OPERATOR_ID,
            sources=[
                expected_source(
                    "art",
                    ["chunk_5346edbe699fc775"],
                    ["8. 像素 Sprite 规范"],
                )
            ],
            facts=[
                fact(
                    "clarity_first",
                    "像素 Sprite 的核心原则是清晰度优先于细节数量。",
                    critical=True,
                ),
                fact(
                    "production_rules",
                    "制作要求包括清晰色块、避免单像素噪点、保证头手和武器轮廓可读、不过度抗锯齿且动画帧不改变核心轮廓。",
                    critical=True,
                ),
                fact(
                    "secondary_motion",
                    "二级运动顺序是身体先动、头发随后、披风略微延迟、饰品最后跟随。",
                    critical=True,
                ),
            ],
            intent="全库 Operator 查询 art 部门 Sprite 制作规范。",
            keywords=["清晰度优先", "单像素噪点", "披风略微延迟"],
            tags=["answerable", "permission_filter"],
            note="Operator 具有全库读取权限，合法跨部门读取 art 文档。",
        ),
        answerable_case(
            case_id="operator_product_skill_definition",
            question="产品规划文档要求每个技能定义哪些信息，并把技能划分为哪些类型？",
            principal_id=OPERATOR_ID,
            sources=[
                expected_source(
                    "combat_product",
                    ["chunk_343ee42cb1c2685c"],
                    ["6. 技能系统设计"],
                )
            ],
            facts=[
                fact(
                    "skill_fields",
                    "每个技能至少定义名称、类型、冷却、资源消耗、伤害倍率、范围、控制效果、前后摇、可打断性和普通攻击衔接性。",
                    critical=True,
                ),
                fact(
                    "skill_types",
                    "技能类型包括输出、控制、位移、防御、增益和召唤。",
                    critical=True,
                ),
                fact(
                    "differentiation",
                    "技能之间必须有明显差异，不能只是不同颜色的伤害按钮。",
                ),
            ],
            intent="全库 Operator 查询 product_planning 的技能数据定义和分类。",
            keywords=["冷却时间", "资源消耗", "召唤技能"],
            tags=["answerable", "permission_filter"],
            note="Operator 具有全库读取权限，合法跨部门读取 product_planning Markdown。",
        ),
        answerable_case(
            case_id="operator_pptx_input_buffer",
            question=(
                "战斗系统 PPT 更新后的输入缓存窗口范围是多少，由什么机制开关，"
                "角色处于哪些状态时必须拒绝连招请求？"
            ),
            principal_id=OPERATOR_ID,
            sources=[
                expected_source(
                    "combat_pptx",
                    ["chunk_4fa2c1cee4de0e73", "chunk_633fcabfcec448b8"],
                    ["Slide 5 输入缓存", "Slide 6 增量更新验证页"],
                )
            ],
            facts=[
                fact(
                    "updated_window",
                    "更新后的输入缓存采用 0.18~0.28 秒动态窗口。",
                    critical=True,
                ),
                fact(
                    "notify_control",
                    "缓存窗口由当前 Montage NotifyState 开启和关闭，而不是写死在输入层。",
                    critical=True,
                ),
                fact(
                    "blocked_states",
                    "角色带有 State.Stunned 或 State.Dead 时必须拒绝连招请求。",
                    critical=True,
                ),
            ],
            intent="全库 Operator 查询 PPT 增量更新后的连招缓存规则。",
            keywords=["0.18~0.28", "Montage NotifyState", "State.Stunned", "State.Dead"],
            tags=["answerable", "permission_filter"],
            note="PPTX 跨原页面和增量插入页面的同义多 Chunk Case。",
        ),
    ]
    return cases


def build_payload() -> dict[str, Any]:
    payload = {
        "schema_version": "2.0",
        "dataset_id": "stage11_acl_rag_eval",
        "dataset_version": DATASET_VERSION,
        "lifecycle": "candidate",
        "content_sha256": "",
        "name": "stage11_acl_rag_eval_v2_1_3_candidate",
        "description": (
            "V2.1.3 candidate：完全基于当前重建后的 9 份知识文档重新设计；"
            "以新增 DOCX/PDF 长文档为核心，并覆盖 Markdown 父子块、XLSX、PPTX、"
            "ACL 正负例、无结果、underfilled 和跨文档多来源场景。"
        ),
        "knowledge_base_dir": KNOWLEDGE_BASE_DIR,
        "source_revision": SOURCE_REVISION,
        "created_at": CREATED_AT,
        "cases": build_cases(),
    }
    return seal_eval_dataset_payload(payload)


def main() -> None:
    actual_revision = compute_directory_source_revision(
        PROJECT_ROOT / KNOWLEDGE_BASE_DIR
    )
    if actual_revision != SOURCE_REVISION:
        raise SystemExit(
            "当前知识目录已经变化，拒绝生成过期 candidate："
            f"expected={SOURCE_REVISION}, actual={actual_revision}"
        )

    payload = build_payload()
    RagEvalDataset.model_validate(payload)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    dataset = load_eval_dataset(
        OUTPUT_PATH,
        verify_source_revision=True,
        repository_root=PROJECT_ROOT,
    )
    print(f"V2.1.3 candidate 已写入：{OUTPUT_PATH}")
    print(f"cases={len(dataset.cases)} lifecycle={dataset.lifecycle}")
    print(f"content_sha256={dataset.content_sha256}")
    print(f"source_revision={dataset.source_revision}")


if __name__ == "__main__":
    main()
