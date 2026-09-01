"""从不可变 V2.1.3 派生完成标注质量修复的 V2.1.4 candidate。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from fast_app.evaluation.cases.loader import (
    load_eval_dataset,
    seal_eval_dataset_payload,
)
from fast_app.evaluation.cases.models import RagEvalDataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.3.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT
    / "src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.4.json"
)
DATASET_VERSION = "2.1.4"
CREATED_AT = "2026-08-28T18:00:00+08:00"
ANNOTATED_BY = "codex:v2.1.4-qrels-quality-corrector"


def _fact(
    fact_id: str,
    text: str,
    *,
    critical: bool = False,
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "text": text,
        "weight": 1.0,
        "critical": critical,
    }


def _case_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case["case_id"]: case for case in payload["cases"]}


def _reset_candidate_identity(payload: dict[str, Any]) -> None:
    payload.update(
        {
            "dataset_version": DATASET_VERSION,
            "lifecycle": "candidate",
            "content_sha256": "",
            "name": "stage11_acl_rag_eval_v2_1_4_candidate",
            "description": (
                "V2.1.4 candidate：从不可变 V2.1.3 派生，修正第二轮人工前"
                "标注质量复核发现的 qrels 覆盖、Recall@K 上限、underfilled、"
                "ACL 可回答性和冲突 PPT 证据问题。"
            ),
            "created_at": CREATED_AT,
        }
    )
    for case in payload["cases"]:
        case.update(
            {
                "dataset_version": DATASET_VERSION,
                "annotation_method": "model_assisted",
                "annotated_by": ANNOTATED_BY,
                "review_status": "pending_review",
                "reviewed_by": None,
                "reviewed_at": None,
                "review_note": "等待 human:TGG 对 V2.1.4 修正内容进行人工审核。",
            }
        )


def _fix_long_document_toon_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_longdocs_toon_production_multi_source"]
    word_source, pdf_source = deepcopy(case["expected_sources"])
    word_source.update(
        {
            "logical_chunk_ids": [
                "chunk_6f31fe460a4ff15b",
                "chunk_e6d54817043b7a3e",
            ],
            "section_keywords": [
                "5.1 官方 Toon 的能力边界",
                "最后：真正应该记住的 10 句话",
            ],
        }
    )
    pdf_source.update(
        {
            "logical_chunk_ids": [
                "chunk_519c11634c2ef350",
                "chunk_6fb6c9494ea6327d",
            ],
            "section_keywords": [
                "Page 10 Toon Shader 基础能力",
                "Page 11 不是完整 Anime Pipeline",
            ],
        }
    )
    relevant = [
        *word_source["logical_chunk_ids"],
        *pdf_source["logical_chunk_ids"],
    ]
    case.update(
        {
            "question": (
                "两份 UE5.8.1 长手册都说明官方 Toon 不能自动完成 Anime "
                "Character Pipeline。它已经提供哪些基础能力，项目仍需自行"
                "补齐哪些角色渲染模块？"
            ),
            "top_k": 5,
            "candidate_k": 10,
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": relevant,
            "expected_sources": [word_source, pdf_source],
            "required_key_facts": [
                _fact(
                    "official_toon_foundation",
                    "官方 Toon 提供分段漫反射和高光、Toon BSDF/Profile/Ramp、各向异性高光、Hatching，并能接入本地光、Sky Light 与 Lumen GI。",
                    critical=True,
                ),
                _fact(
                    "character_modules_still_required",
                    "项目仍需自行设计 Face SDF 或脸部阴影、头发高光、Outline、后处理、灯光和资产协作。",
                    critical=True,
                ),
                _fact(
                    "not_complete_pipeline",
                    "官方 Toon 是 NPR 光照底座或入口，不是一键生成完整 Anime Character Pipeline。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "综合 DOCX/PDF 两份长文档，区分官方 Toon 已提供的基础能力"
                "和仍需项目自行实现的角色模块。"
            ),
            "expected_answer_keywords": [
                "Toon BSDF",
                "Face SDF",
                "头发高光",
                "Outline",
            ],
            "note": (
                "V2.1.4 将问题收窄到两份手册共同明确描述的能力边界；"
                "4 个相关 Chunk 不超过 top_k=5。"
            ),
        }
    )


def _fix_public_underfilled_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_public_acl_underfilled"]
    relevant = [
        "chunk_a96818cd638bdf5e",
        "chunk_0d712ae8b17bbe30",
        "chunk_5b810cc8195b5051",
        "chunk_1d4b9388b6b6a450",
        "chunk_9db8266b4400b809",
        "chunk_46184d5a7c6d3eb2",
        "chunk_ab6631bbb6b4315e",
        "chunk_30679008b2e6d98b",
        "chunk_f6a70fdc86583e29",
        "chunk_34746fe25e2b2d22",
        "chunk_308b696cf3ecd8cd",
        "chunk_0d557c0bdaaed986",
        "chunk_9306991da46132c3",
        "chunk_aa8db320ce8941f2",
        "chunk_f9fff42f4d54189d",
        "chunk_013212d0fb835c38",
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "文档目的与项目目标",
                "权限模型与目录",
                "各部门预期检索行为",
                "测试问题、关键词与验收标准",
                "10.1～10.3 常见错误",
                "总结",
            ],
        }
    )
    case.update(
        {
            "question": (
                "请按章节概述 public 项目整体介绍文档全文：项目目标、权限模型、"
                "测试目录与各部门预期检索行为、推荐测试问题和关键词、验收标准，"
                "以及文档列出的三类常见错误。"
            ),
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "required_key_facts": [
                _fact(
                    "project_goal",
                    "项目用于验证企业 RAG 的多用户、多部门权限隔离，重点是正确控制文档召回范围。",
                    critical=True,
                ),
                _fact(
                    "permission_model",
                    "权限模型由 RBAC、ACL、ABAC 共同组成，public 文档使用 visibility=public，而不是把 public 当成部门。",
                    critical=True,
                ),
                _fact(
                    "department_behavior",
                    "art、product_planning、development 用户均可读取 public 文档，但只能读取各自部门的私有文档。",
                    critical=True,
                ),
                _fact(
                    "test_and_acceptance",
                    "文档给出推荐测试问题、公开测试关键词和跨部门可见性验收标准。",
                ),
                _fact(
                    "three_common_errors",
                    "三类错误是把 public 写成 allowed_departments=[public]、只在 Elasticsearch 支持 public，以及进入 Prompt 前缺少最终权限校验。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "在精确 source_path 范围内概述 public 文档全部章节，形成所有"
                "16 个子块均相关且结果数仍小于 K 的 underfilled 场景。"
            ),
            "expected_answer_keywords": [
                "RBAC",
                "ACL",
                "ABAC",
                "visibility",
                "final_permission_check",
            ],
            "note": (
                "V2.1.4 将问题改为全文概述，当前 public 文档 16 个子块全部"
                "属于 qrels；top_k=20 时 underfilled 不再结构性制造 false positive。"
            ),
        }
    )


def _fix_acl_negative_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_art_acl_negative"]
    case.update(
        {
            "question": (
                "art 部门内部测试关键词列表是否同时包含“月光披风规则”和"
                "“女巫帽轮廓标准”？"
            ),
            "question_intent": (
                "验证 development Reader 无法确认 art 私有关键词列表中确实"
                "存在的两个条目。"
            ),
            "note": (
                "授权 art/全库用户可从 forbidden Chunk 明确回答“包含”；"
                "Reader 无权读取，因此拒答才能单独归因于 ACL。"
            ),
        }
    )


def _replace_conflicting_ppt_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["operator_pptx_input_buffer"]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": ["chunk_074e7c6fc05a33ef"],
            "section_keywords": ["Slide 10: 8. 联机同步与预测策略"],
        }
    )
    case.update(
        {
            "case_id": "operator_pptx_network_strategy",
            "question": (
                "战斗系统 PPT 第 8 节规定客户端预测、服务端权威和回滚修正"
                "分别负责什么，延迟测试使用哪些 PktLag 与 PacketLoss 档位？"
            ),
            "filters": {"source_path": source["source_path"]},
            "relevant_logical_chunk_ids": ["chunk_074e7c6fc05a33ef"],
            "authoritative_logical_chunk_ids": ["chunk_074e7c6fc05a33ef"],
            "expected_sources": [source],
            "required_key_facts": [
                _fact(
                    "prediction_authority",
                    "客户端可预测输入、移动和前摇表现；伤害、硬直、死亡和掉落必须由服务端权威确认。",
                    critical=True,
                ),
                _fact(
                    "rollback_correction",
                    "客户端预测失败时回滚战斗状态，并播放轻量纠正表现。",
                    critical=True,
                ),
                _fact(
                    "bandwidth_scope",
                    "只同步必要的 GameplayTag、AbilitySpecHandle 和 HitContext 摘要。",
                ),
                _fact(
                    "network_test_tiers",
                    "延迟测试使用 Net PktLag=80/150/250，PacketLoss=1%/3%。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "查询 PPT 第 8 节的预测/权威职责、回滚方式和网络模拟档位。"
            ),
            "expected_answer_keywords": [
                "客户端预测",
                "服务端权威",
                "PktLag",
                "PacketLoss",
            ],
            "note": (
                "V2.1.4 移除同一 Chunk 内含 0.18~0.28 与旧 Notes "
                "0.15-0.25 冲突的输入缓存 Case，改用无冲突的 PPT 第 8 节。"
            ),
        }
    )


def _narrow_companion_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_companion_ai_guard"]
    relevant = ["chunk_1aacfb4570bf0fbe", "chunk_5237f6b9758968d7"]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 20: 7.5 Companion 分层",
                "Page 21: Gameplay Guard 与 fallback",
            ],
        }
    )
    case.update(
        {
            "question": (
                "回归手册第 7.5 节给出的 Companion 执行链是什么？"
                "模型输出非法或模型暂时不可用时分别怎样兜底？"
            ),
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "required_key_facts": [
                _fact(
                    "runtime_chain",
                    "执行链是 Player Model → 5~10 Hz Neural Policy → Action Intent → StateTree/Gameplay Guard → Ability/Navigation/Animation → 实际角色行为。",
                    critical=True,
                ),
                _fact(
                    "illegal_action_guard",
                    "Gameplay Guard 负责拒绝模型输出的不合法动作。",
                    critical=True,
                ),
                _fact(
                    "model_fallback",
                    "模型暂时不可用时由 StateTree/Rule Policy 提供 fallback。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "精确查询第 7.5 节的 Companion 执行链、非法动作拒绝和模型故障 fallback。"
            ),
            "expected_answer_keywords": [
                "5~10 Hz",
                "Action Intent",
                "Gameplay Guard",
                "Rule Policy",
            ],
            "note": (
                "V2.1.4 将原第 7 章宽问题收窄到 7.5 节连续跨页证据，"
                "避免宏观 StateTree/Learning Agents 总结块成为漏标 qrels。"
            ),
        }
    )


def _scope_nne_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_nne_training_runtime"]
    relevant = [
        "chunk_fa9d79af16538c98",
        "chunk_dfec29f8331e1bd6",
        "chunk_c80e0436eac5de05",
        "chunk_1aacfb4570bf0fbe",
        "chunk_d8f7f46961b5a99e",
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 18～19: 7.3 Learning Agents",
                "Page 19～20: 7.4 NNE",
                "Page 20: 图 7-2 NNE Runtime",
            ],
        }
    )
    case.update(
        {
            "question": (
                "回归手册第 7.3～7.4 节如何区分 Learning Agents、"
                "Python/PyTorch 与 NNE 的职责？自定义模型如何进入 UE，"
                "图 7-2 又展示了哪些 NNE Runtime 层？"
            ),
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "required_key_facts": [
                _fact(
                    "learning_agents_role",
                    "Learning Agents 是 Experimental 的 UE 训练基础设施，适合快速做 Reinforcement Learning 与 Imitation Learning 实验。",
                    critical=True,
                ),
                _fact(
                    "engine_independent_contract",
                    "Observation、Action、Reward、数据集和模型结构应保持引擎无关，不能绑死在 Learning Agents API。",
                ),
                _fact(
                    "custom_model_chain",
                    "自定义模型由 Python/PyTorch 训练，导出 ONNX，导入 NNE Model Data 后在 UE 中推理。",
                    critical=True,
                ),
                _fact(
                    "nne_runtime_layers",
                    "NNE 提供统一接口，并包含 CPU、GPU、RDG Runtime，由具体插件或 Runtime 完成推理。",
                    critical=True,
                ),
                _fact(
                    "tool_selection",
                    "快速 imitation/PPO 优先 Learning Agents；自定义训练由 Python/PyTorch 主导；已训练 ONNX 通过 NNE 部署。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "精确查询第 7.3～7.4 节的训练/部署职责、ONNX 链路和图 7-2 Runtime 分层。"
            ),
            "expected_answer_keywords": [
                "Imitation Learning",
                "PyTorch",
                "ONNX",
                "RuntimeCPU",
                "RuntimeGPU",
                "RuntimeRDG",
            ],
            "note": (
                "V2.1.4 明确限定第 7.3～7.4 节并补入 Learning Agents "
                "跨页块与图 7-2 图像文本块，5 个 qrels 等于 top_k=5。"
            ),
        }
    )


def _narrow_mover_case(cases: dict[str, dict[str, Any]]) -> None:
    case = cases["reader_pdf_mover_migration"]
    relevant = [
        "chunk_00499a8f184e0ffd",
        "chunk_50f5a64967ad9d11",
        "chunk_0c20779a4e397e0d",
    ]
    source = deepcopy(case["expected_sources"][0])
    source.update(
        {
            "logical_chunk_ids": relevant,
            "section_keywords": [
                "Page 22: 8.1 Mover",
                "Page 27: 10.1 最容易误判的三件事",
            ],
        }
    )
    case.update(
        {
            "question": (
                "回归手册第 8.1 节建议正式项目怎样选择 "
                "CharacterMovementComponent 与 Mover？第 10.1 节为什么说"
                "“Mover 出现，所以 CMC 过时”是误判？"
            ),
            "relevant_logical_chunk_ids": relevant,
            "authoritative_logical_chunk_ids": relevant,
            "expected_sources": [source],
            "required_key_facts": [
                _fact(
                    "mover_status",
                    "Mover 在 UE5.8 仍是 Experimental，API、属性和数据格式可能变化。",
                    critical=True,
                ),
                _fact(
                    "formal_project_choice",
                    "正式原型继续使用 CharacterMovementComponent 或自定义 Movement Mode，Mover 只在独立小地图验证。",
                    critical=True,
                ),
                _fact(
                    "cmc_not_obsolete",
                    "Mover 的未来目标是接替 CMC，但 CMC 成熟且在可预见未来仍会继续支持。",
                    critical=True,
                ),
            ],
            "question_intent": (
                "精确查询第 8.1 节的正式项目选择和第 10.1 节对 CMC 过时误判的纠正。"
            ),
            "expected_answer_keywords": [
                "Experimental",
                "CharacterMovementComponent",
                "独立小地图",
                "继续支持",
            ],
            "note": (
                "V2.1.4 将问题限定到 8.1 与 10.1 两节，去掉迁移矩阵"
                "和其他全书总结块的相关性歧义。"
            ),
        }
    )


def build_payload() -> dict[str, Any]:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    payload = deepcopy(source)
    _reset_candidate_identity(payload)
    cases = _case_map(payload)
    _fix_long_document_toon_case(cases)
    _fix_public_underfilled_case(cases)
    _fix_acl_negative_case(cases)
    _replace_conflicting_ppt_case(cases)
    _narrow_companion_case(cases)
    _scope_nne_case(cases)
    _narrow_mover_case(cases)
    return seal_eval_dataset_payload(payload)


def main() -> None:
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
    print(f"V2.1.4 candidate 已写入：{OUTPUT_PATH}")
    print(f"cases={len(dataset.cases)} lifecycle={dataset.lifecycle}")
    print(f"content_sha256={dataset.content_sha256}")


if __name__ == "__main__":
    main()
