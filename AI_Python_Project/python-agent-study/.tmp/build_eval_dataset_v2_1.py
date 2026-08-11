"""构建新评测集 candidate：stage11_rag_eval_cases.v2.1.0.json。

- 所有 logical_record_id / doc_id / parent_id / source_revision 均从
  .tmp/knowledge_inventory.json（Milvus 真实盘点）中解析，防止手写错 ID。
- 通过 RagEvalCase / RagEvalDataset Pydantic 校验后，
  用 seal_eval_dataset_payload 计算 content_sha256。
- lifecycle=candidate，review_status=pending_review，等待人工审核晋升 golden。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fast_app.evaluation.cases.loader import (
    compute_directory_source_revision,
    load_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import RagEvalDataset

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path(__file__).parent / "knowledge_inventory.json"
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.0.json"
)

KNOWLEDGE_BASE_DIR = "docs/knowledge-base-acl-test"
DATASET_VERSION = "2.1.0"
KNOWLEDGE_VERSION = 6
RBAC_READER = "user_rp-iYI84UD1vMXH039AGHYQz"
RBAC_OPERATOR = "user_MBeEmT7K2eGguofW4CZ1aGTp"

# ---------------------------------------------------------------------------
# 从盘点数据建立索引
# ---------------------------------------------------------------------------
INVENTORY = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
BY_CHUNK = {item["logical_record_id"]: item for item in INVENTORY}
DOC_REVISION = {item["doc_id"]: item["source_revision"] for item in INVENTORY}
DOC_PATH = {item["doc_id"]: item["source_path"] for item in INVENTORY}


def chunk(key: str) -> dict:
    if key not in BY_CHUNK:
        raise SystemExit(f"盘点中不存在 logical_record_id: {key}")
    return BY_CHUNK[key]


def doc_id_of(chunk_id: str) -> str:
    return chunk(chunk_id)["doc_id"]


def parent_of(chunk_id: str) -> str:
    parent = chunk(chunk_id)["logical_parent_id"]
    if not parent:
        raise SystemExit(f"{chunk_id} 没有 logical_parent_id")
    return parent


def source(chunk_id: str, keywords: list[str], with_parent: bool = False) -> dict:
    """构建一个 ExpectedSource JSON dict。"""

    item = chunk(chunk_id)
    source: dict = {
        "logical_doc_id": item["doc_id"],
        "source_revision": DOC_REVISION[item["doc_id"]],
        "logical_chunk_ids": [chunk_id],
        "source_path": item["source_path"],
        "section_keywords": keywords,
    }
    if with_parent:
        source["logical_parent_id"] = parent_of(chunk_id)
        source["matched_logical_child_ids"] = [chunk_id]
    return source


def multi_source(chunk_ids: list[str], keywords: list[str]) -> list[dict]:
    return [source(chunk_id, keywords) for chunk_id in chunk_ids]


def base_case(
    *,
    case_id: str,
    question: str,
    principal: str,
    answerable: bool,
    scenario_tags: list[str],
    chunks: list[str],
    sources: list[dict] | None = None,
    facts: list[dict] | None = None,
    forbidden_chunks: list[str] | None = None,
    intent: str,
    constraints: list[str] | None = None,
    hard_gates: list[str] | None = None,
    answer_keywords: list[str] | None = None,
    forbidden_keywords: list[str] | None = None,
    top_k: int = 5,
    candidate_k: int = 10,
    note: str = "",
) -> dict:
    relevant_chunk_ids = list(chunks)
    relevant_doc_ids = sorted({doc_id_of(chunk_id) for chunk_id in chunks})
    return {
        "case_id": case_id,
        "dataset_version": DATASET_VERSION,
        "metric_profile": "rag",
        "question": question,
        "answerable": answerable,
        "expected_route": "rag_answer" if answerable else "rag_no_answer",
        "eval_principal_id": principal,
        "knowledge_version": KNOWLEDGE_VERSION,
        "source_revision": SOURCE_REVISION,
        "mode": "hybrid",
        "top_k": top_k,
        "candidate_k": candidate_k,
        "min_score": 0.0,
        "filters": {},
        "relevant_logical_chunk_ids": relevant_chunk_ids,
        "relevant_doc_ids": relevant_doc_ids,
        "forbidden_logical_chunk_ids": forbidden_chunks or [],
        "expected_sources": sources or [],
        "required_key_facts": facts or [],
        "question_intent": intent,
        "constraints": constraints or ["只根据当前身份可见的知识库证据回答"],
        "hard_gate_labels": hard_gates or [],
        "scenario_tags": scenario_tags,
        "expected_answer_keywords": answer_keywords or [],
        "forbidden_answer_keywords": forbidden_keywords or [],
        "annotation_method": "model_assisted",
        "annotated_by": "lingma-agent:v2.1-candidate-builder",
        "review_status": "pending_review",
        "note": note,
    }


SOURCE_REVISION = compute_directory_source_revision(
    PROJECT_ROOT / KNOWLEDGE_BASE_DIR
)

CASES: list[dict] = [
    # ---------- rbac_reader（development 部门） ----------
    base_case(
        case_id="reader_ue5_damage_formula_parent",
        question="UE5 战斗系统中最终生命伤害的计算公式",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "parent_expansion", "underfilled_k"],
        chunks=["chunk_7cb94aed146a6d3b", "chunk_84348081c94edf87"],
        sources=[
            source("chunk_7cb94aed146a6d3b", ["伤害计算架构", "计算流程"], with_parent=True),
            source("chunk_84348081c94edf87", ["伤害计算服务"]),
        ],
        facts=[
            {"fact_id": "formula_chain", "text": "最终生命伤害由基础伤害依次乘以技能倍率、武器倍率、属性倍率、暴击倍率、元素克制倍率，再减去防御减伤和格挡减伤得到。", "weight": 1.0, "critical": True},
            {"fact_id": "central_service", "text": "伤害计算建议集中在独立的伤害计算服务或 GAS Execution Calculation 中完成。", "weight": 0.5, "critical": False},
        ],
        intent="查询 UE5 战斗系统伤害计算公式。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["基础伤害", "技能倍率", "防御减伤"],
        note="只有 2 个黄金相关块但 top_k=5，验证 underfilled_k；公式块依赖父块扩展获得完整上下文。名词化单问避免 Router 拆解。",
    ),
    base_case(
        case_id="reader_ue5_perfect_block",
        question="UE5 战斗系统设计中完美格挡成功后的效果与时间窗口控制方式",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "parent_expansion"],
        chunks=["chunk_2d0790c48f8b0092"],
        sources=[
            source("chunk_2d0790c48f8b0092", ["完美格挡"], with_parent=True),
        ],
        facts=[
            {"fact_id": "zero_damage", "text": "完美格挡成功可以将伤害降为零，并返还部分精力。", "weight": 1.0, "critical": True},
            {"fact_id": "counter_effects", "text": "完美格挡成功还会对攻击者施加硬直，并触发慢动作、摄像机震动以及专用特效和音效。", "weight": 0.8, "critical": False},
            {"fact_id": "window_control", "text": "完美格挡窗口应由技能时间轴或动画通知控制，不应在 Tick 中使用多个时间判断分支。", "weight": 0.6, "critical": False},
        ],
        intent="查询完美格挡的成功效果和窗口控制方式。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["伤害降为零", "硬直", "技能时间轴"],
        note="单个黄金块 + 父块扩展场景。",
    ),
    base_case(
        case_id="reader_gitlab_rollback_multi_source",
        question="知识库文档发布出问题需要回滚时的正确回滚方式",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "multiple_relevant_sources"],
        chunks=["chunk_296a2380e2d87791", "chunk_bb13f7442fb8745c"],
        sources=multi_source(
            ["chunk_296a2380e2d87791", "chunk_bb13f7442fb8745c"],
            ["回滚原则", "手动回滚"],
        ),
        facts=[
            {"fact_id": "revert_mr", "text": "文档事实回滚必须通过 GitLab 新建 Revert Commit 和 MR，再由 Maintainer 合并。", "weight": 1.0, "critical": True},
            {"fact_id": "forbidden_direct_change", "text": "禁止直接把 PostgreSQL 正式版本指针改回旧值，也禁止直接删除 ES/Milvus 新记录。", "weight": 1.0, "critical": True},
            {"fact_id": "manual_sql", "text": "系统配置层面的手动回滚可以通过 SQL 更新 publication_version 到指定历史版本。", "weight": 0.6, "critical": False},
        ],
        intent="查询发布回滚的推荐流程和禁止操作。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["Revert", "MR", "publication_version"],
        note="两个 development 文档共同支撑回滚问题，验证多来源聚合。",
    ),
    base_case(
        case_id="reader_webhook_worker_multi_source",
        question="GitLab MR 合并后文档发布任务是如何处理的？",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "multiple_relevant_sources"],
        chunks=["chunk_dea252b8024f71e1", "chunk_0452d406311e7d7b"],
        sources=multi_source(
            ["chunk_dea252b8024f71e1", "chunk_0452d406311e7d7b"],
            ["独立 Worker 处理", "Webhook 只登记任务"],
        ),
        facts=[
            {"fact_id": "webhook_register_only", "text": "Webhook 接收端应快速返回 202，只登记或合并待处理任务，不直接处理文档发布。", "weight": 1.0, "critical": True},
            {"fact_id": "worker_duties", "text": "独立 Worker 负责从任务队列拉取 pending 任务、拉取对应 commit 的文档内容、校验权限规则并写入 Elasticsearch/Milvus 等存储。", "weight": 1.0, "critical": True},
        ],
        intent="查询 Webhook 只登记任务与独立 Worker 职责分工。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["202", "任务队列", "Worker"],
        note="治理规范与部署验收清单两个文档交叉验证。",
    ),
    base_case(
        case_id="reader_milvus_index_check",
        question="RAG 后端文档导入后检查 Milvus collection 需要确认哪些内容？",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable"],
        chunks=["chunk_4e797af9683c05c2"],
        sources=[source("chunk_4e797af9683c05c2", ["Milvus 索引检查"])],
        facts=[
            {"fact_id": "collection_created", "text": "文档导入后需要确认 Milvus collection 已经创建。", "weight": 1.0, "critical": True},
            {"fact_id": "check_fields", "text": "需要检查 collection name、vector dimension、primary key、doc_id、chunk_id、visibility、allowed_departments 等内容。", "weight": 1.0, "critical": True},
        ],
        intent="查询 Milvus 索引导入后的检查项。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["collection", "vector dimension", "allowed_departments"],
        note="单块直接命中的常规 answerable case。",
    ),
    base_case(
        case_id="reader_art_acl_negative",
        question="角色美术规范里的月光披风规则和女巫帽轮廓标准具体是怎么定义的？",
        principal=RBAC_READER,
        answerable=False,
        scenario_tags=["unanswerable", "permission_filter"],
        chunks=[],
        forbidden_chunks=["chunk_0aa1bbea341cfb4d", "chunk_15eb212207bbd84e"],
        intent="development 用户询问 art 部门内部测试关键词，验证 ACL 过滤不泄漏。",
        constraints=[
            "只根据当前身份可见的知识库证据回答",
            "不得输出 art 部门文档中的内部测试关键词内容",
        ],
        hard_gates=["acl_no_leak"],
        forbidden_keywords=["月光披风", "女巫帽轮廓"],
        note="art/character-art-style.md 对 development 用户不可见，应保守拒答。",
    ),
    base_case(
        case_id="reader_visibility_positive",
        question="权限过滤规则中 development 用户应能检索到哪些文档，以及不应检索到哪些文档？",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "permission_filter", "multiple_relevant_sources"],
        chunks=["chunk_f8a53eabbef5743c", "chunk_e61f024c79efd70d"],
        sources=multi_source(
            ["chunk_f8a53eabbef5743c", "chunk_e61f024c79efd70d"],
            ["权限过滤规则", "development 部门用户"],
        ),
        facts=[
            {"fact_id": "visible_docs", "text": "development 用户应能检索到 development/rag-backend-deployment.md 和 public/project-overview.md。", "weight": 1.0, "critical": True},
            {"fact_id": "invisible_docs", "text": "development 用户不应检索到 art 目录下的角色美术风格文档等 art 部门私有文档。", "weight": 1.0, "critical": True},
        ],
        intent="查询 development 用户可见与不可见文档边界。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["rag-backend-deployment", "project-overview", "art"],
        note="权限过滤正例：问题本身可见且可回答。",
    ),
    base_case(
        case_id="reader_incremental_input_buffer",
        question="增量更新验收规则中输入缓存窗口的建议值",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable"],
        chunks=["chunk_fbbecbe7a07925ba"],
        sources=[source("chunk_fbbecbe7a07925ba", ["增量更新测试"])],
        facts=[
            {"fact_id": "buffer_window", "text": "输入缓存窗口建议使用 0.18～0.28 秒。", "weight": 1.0, "critical": True},
            {"fact_id": "notify_state", "text": "输入缓存窗口由 Montage Notify State 控制开启与关闭。", "weight": 0.6, "critical": False},
        ],
        intent="查询增量更新验收规则中的输入缓存窗口参数。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["0.18", "0.28", "Montage Notify State"],
        note="验证增量 ingestion 后新增内容可被检索。",
    ),
    base_case(
        case_id="reader_unanswerable_audio_middleware",
        question="知识库中是否有关于 Wwise 音频中间件 Profiler 接入战斗系统性能分析的资料？",
        principal=RBAC_READER,
        answerable=False,
        scenario_tags=["unanswerable"],
        chunks=[],
        intent="知识库中没有任何音频中间件接入内容，应保守拒答而不是编造。",
        forbidden_keywords=["Wwise Profiler", "AudioMeter"],
        note="话题与战斗系统相关但知识库无证据，测试 no-evidence 拒答。",
    ),
    base_case(
        case_id="reader_checklist_env_single_gold",
        question="本地部署 RAG 后端时的数据库迁移命令与迁移后需要确认的表",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable", "underfilled_k"],
        chunks=["chunk_7dafc7207a61cc2e"],
        sources=[source("chunk_7dafc7207a61cc2e", ["数据库迁移"])],
        facts=[
            {"fact_id": "alembic_command", "text": "启动依赖服务后需要执行 alembic upgrade head 完成数据库迁移。", "weight": 1.0, "critical": True},
            {"fact_id": "table_check", "text": "迁移完成后需要确认 users、api_keys、refresh_tokens、documents 等表存在。", "weight": 0.8, "critical": False},
        ],
        intent="查询数据库迁移命令和迁移后的表检查。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["alembic upgrade head", "users", "api_keys"],
        top_k=8,
        candidate_k=16,
        note="top_k=8 但只有 1 个黄金块，验证 underfilled_k 下的 Recall/Precision。",
    ),
    base_case(
        case_id="reader_worker_failure_recovery",
        question="知识发布任务 Worker 失败后的恢复处理方式",
        principal=RBAC_READER,
        answerable=True,
        scenario_tags=["answerable"],
        chunks=["chunk_bf7e323eb34c4674"],
        sources=[source("chunk_bf7e323eb34c4674", ["Worker 任务失败"])],
        facts=[
            {"fact_id": "old_version_keeps_serving", "text": "Worker 失败时旧正式版本应继续提供检索。", "weight": 1.0, "critical": True},
            {"fact_id": "inspect_first", "text": "应先读取任务的阶段、error_code、租约和重试次数，再检查 GitLab Token、Qwen Embedding、ES 与 Milvus。", "weight": 0.8, "critical": False},
            {"fact_id": "retry_original_task", "text": "外部依赖恢复后使用原任务重试，避免产生重复候选版本。", "weight": 0.8, "critical": False},
        ],
        intent="查询 Worker 任务失败的恢复与重试流程。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["旧正式版本", "error_code", "原任务重试"],
        note="运行手册故障恢复章节单块 case。",
    ),
    # ---------- rbac_operator（art 部门） ----------
    base_case(
        case_id="operator_pixel_sprite_rules",
        question="角色美术规范中像素 Sprite 的制作核心原则与制作要求",
        principal=RBAC_OPERATOR,
        answerable=True,
        scenario_tags=["answerable"],
        chunks=["chunk_a2a894bca15c2988"],
        sources=[source("chunk_a2a894bca15c2988", ["像素 Sprite 规范"])],
        facts=[
            {"fact_id": "clarity_first", "text": "像素 Sprite 的核心原则是清晰度优先于细节数量。", "weight": 1.0, "critical": True},
            {"fact_id": "production_rules", "text": "Sprite 制作要求包括使用清晰色块、避免单像素噪点、保持头部和手部可读、不要过度抗锯齿、保持武器或工具轮廓清晰。", "weight": 1.0, "critical": True},
        ],
        intent="查询角色美术规范中像素 Sprite 的制作要求。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["清晰度优先", "色块", "噪点"],
        note="art 部门用户查询本部门文档的正例。",
    ),
    base_case(
        case_id="operator_art_visible_scope_multi",
        question="在 ACL 权限测试中 art 部门用户应该能检索到哪些文档？",
        principal=RBAC_OPERATOR,
        answerable=True,
        scenario_tags=["answerable", "permission_filter", "multiple_relevant_sources"],
        chunks=["chunk_15eb212207bbd84e", "chunk_9ca728a00b73727c"],
        sources=multi_source(
            ["chunk_15eb212207bbd84e", "chunk_9ca728a00b73727c"],
            ["总结", "art 部门用户"],
        ),
        facts=[
            {"fact_id": "visible_docs", "text": "art 用户应能检索到 art/character-art-style.md 和 public/project-overview.md。", "weight": 1.0, "critical": True},
            {"fact_id": "invisible_docs", "text": "art 用户不应检索到 product_planning/combat-design.md 等其他部门私有文档。", "weight": 1.0, "critical": True},
        ],
        intent="查询 art 用户的可见与不可见文档边界。",
        hard_gates=["critical_fact_missing"],
        answer_keywords=["character-art-style", "project-overview", "combat-design"],
        note="art 身份下的权限过滤正例，且需要跨 art 与 public 两个文档。",
    ),
    base_case(
        case_id="operator_dev_acl_negative",
        question="知识库中是否有关于 RAG 后端部署环境变量要求与 FastAPI 本地启动命令的资料？",
        principal=RBAC_OPERATOR,
        answerable=False,
        scenario_tags=["unanswerable", "permission_filter"],
        chunks=[],
        forbidden_chunks=["chunk_bf5a29d90fe09980", "chunk_4280ef8844cf5af5"],
        intent="art 用户询问 development 部门部署文档内容，验证 ACL 过滤不泄漏。",
        constraints=[
            "只根据当前身份可见的知识库证据回答",
            "不得输出 development 部署文档中的环境变量和启动命令",
        ],
        hard_gates=["acl_no_leak"],
        forbidden_keywords=["JWT_SECRET_KEY", "uvicorn fast_app.main:app"],
        note="development/rag-backend-deployment.md 对 art 用户不可见，应保守拒答。",
    ),
    # ---------- no_result：检索链路正常执行但无任何相关证据 ----------
    base_case(
        case_id="reader_no_result_backup_schedule",
        question="知识库文档冷备策略的执行时间与备份文件存放的存储桶位置",
        principal=RBAC_READER,
        answerable=False,
        scenario_tags=["unanswerable", "no_result"],
        chunks=[],
        intent="话题属于知识库运维领域会进入检索链路，但知识库中完全没有备份策略内容，预期检索无相关结果后保守拒答。",
        forbidden_keywords=["S3 存储桶", "凌晨两点"],
        note="验证检索执行但零相关证据时的拒答行为（no_result）。",
    ),
]


def main() -> None:
    # 清理临时占位（防御性：确保没有错误 ID 混入）
    for case in CASES:
        case["forbidden_logical_chunk_ids"] = [
            chunk_id
            for chunk_id in case["forbidden_logical_chunk_ids"]
            if chunk_id in BY_CHUNK
        ]

    # Pydantic 校验（含场景语义、来源并集一致性）
    for case_payload in CASES:
        try:
            from fast_app.evaluation.cases.models import RagEvalCase

            RagEvalCase.model_validate(case_payload)
        except Exception as exc:
            raise SystemExit(f"case {case_payload['case_id']} 校验失败: {exc}")

    dataset_payload = {
        "schema_version": "2.0",
        "dataset_id": "stage11_acl_rag_eval",
        "dataset_version": DATASET_VERSION,
        "lifecycle": "candidate",
        "content_sha256": "",
        "name": "stage11_acl_rag_eval_v2_1_candidate",
        "description": (
            "基于知识版本 6、当前 Milvus/ES 真实 274 个 markdown_child 盘点重建的 "
            "V2.1 candidate 评测集：14 条 case 覆盖 rbac_reader（development）与 "
            "rbac_operator（art）两个真实 API Key 身份，覆盖全部 7 个场景标签。"
            "source_revision 为 docs/knowledge-base-acl-test 目录字节哈希。"
        ),
        "knowledge_base_dir": KNOWLEDGE_BASE_DIR,
        "source_revision": SOURCE_REVISION,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "cases": CASES,
    }

    # 场景矩阵自检（candidate 阶段也提前验证，避免晋升时失败）
    covered = {tag for case in CASES for tag in case["scenario_tags"]}
    required = {
        "answerable", "unanswerable", "permission_filter", "parent_expansion",
        "multiple_relevant_sources", "no_result", "underfilled_k",
    }
    missing = required - covered
    if missing:
        raise SystemExit(f"场景矩阵缺少覆盖: {sorted(missing)}")

    sealed = seal_eval_dataset_payload(dataset_payload)
    RagEvalDataset.model_validate(sealed)

    OUTPUT_PATH.write_text(
        json.dumps(sealed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"candidate 数据集已写入 {OUTPUT_PATH}")
    print(f"content_sha256 = {sealed['content_sha256']}")
    print(f"source_revision = {sealed['source_revision']}")

    # 回读验证（sha256 完整性 + source_revision 目录哈希真实比对）
    reloaded = load_eval_dataset(
        OUTPUT_PATH,
        verify_source_revision=True,
        repository_root=PROJECT_ROOT,
    )
    print(f"回读成功：{len(reloaded.cases)} 条 case，lifecycle={reloaded.lifecycle}")


if __name__ == "__main__":
    main()
