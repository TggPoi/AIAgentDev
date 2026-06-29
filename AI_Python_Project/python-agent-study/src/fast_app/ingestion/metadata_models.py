import hashlib
import json
from pathlib import Path
from typing import Any

from fast_app.domain.knowledge_models import DocumentType

PERMISSION_RULES_FILE_NAME = ".permission-rules.json"


def normalize_source_path(source_path: str) -> str:
    """把本地路径统一转换成 POSIX 风格路径。

    ingestion 后续会把 source_path 写入 ES / Milvus metadata。统一成 `/`
    分隔符后，同一份文档在 Windows 和类 Unix 环境中更容易得到稳定 doc_id。
    """

    return Path(source_path).as_posix()


def build_doc_id(source_path: str) -> str:
    """根据规范化后的文档路径生成稳定 doc_id。

    doc_id 以 source_path 为输入，因此同一路径的文档重复入库时会得到同一个
    doc_id，方便 replace_docs 模式按文档删除旧 chunks 后再写入新 chunks。
    """

    normalized = normalize_source_path(source_path)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def build_chunk_id(
    doc_id: str,
    section_path: list[str],
    chunk_index: int,
) -> str:
    """根据文档、章节路径和 chunk 序号生成稳定 chunk_id。

    chunk_id 是 ES 文档 ID 和 Milvus 主键的来源。把 section_path 纳入 hash，
    可以降低不同章节中相同 chunk_index 发生 ID 冲突的概率。
    """

    raw = "|".join([doc_id, *section_path, str(chunk_index)])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


def build_document_metadata(
    source_path: str,
    document_type: DocumentType,
    knowledge_base_dir: str | None = None,
) -> dict[str, Any]:
    """构造文档级 metadata。

    这里生成所有 chunks 都会继承的基础字段，包括 doc_id、source_path、文件信息
    以及阶段 15-3 新增的权限字段。权限字段在文档级生成，是为了保证同一文档的
    所有 chunks 拥有一致访问边界。knowledge_base_dir 用于读取知识库根目录下的
    权限规则文件，避免把部门目录写死在代码中。
    """

    normalized = normalize_source_path(source_path)
    path = Path(normalized)

    return {
        "doc_id": build_doc_id(normalized),
        "source_path": normalized,
        "document_type": document_type,
        "file_name": path.name,
        "file_extension": path.suffix,
        **build_permission_metadata(
            source_path=normalized,
            knowledge_base_dir=knowledge_base_dir,
        ),
    }


def build_permission_metadata(
    source_path: str,
    knowledge_base_dir: str | None = None,
) -> dict[str, Any]:
    """两种权限来源：根据根目录规则文件 + sidecar metadata 生成文档权限 metadata。

    根目录规则文件提供默认权限，sidecar metadata 用于覆盖跨部门或指定用户可见
    的特殊文档。最终返回值会经过 normalize_permission_metadata 统一校验形状。
    """

    base_policy = infer_permission_metadata_from_path(
        source_path=source_path,
        knowledge_base_dir=knowledge_base_dir,
    )
    sidecar_policy = load_sidecar_permission_metadata(source_path)
    if sidecar_policy:
        base_policy.update(sidecar_policy)
        # 标注当前权限来源，后期排查权限错误问题
        base_policy["permission_source"] = "sidecar_metadata"

    return normalize_permission_metadata(base_policy)


def infer_permission_metadata_from_path(
    source_path: str,
    knowledge_base_dir: str | None = None,
) -> dict[str, Any]:
    """根据文档所在目录推断默认权限。

    优先读取知识库根目录下的 .permission-rules.json。规则文件不存在或没有命中
    时，只保留 public 目录兜底；其他路径按 default_policy 处理，避免把部门 code
    写死在代码里。
    """

    rule_policy = match_permission_rule_from_file(
        source_path=source_path,
        knowledge_base_dir=knowledge_base_dir,
    )
    if rule_policy:
        return rule_policy

    parts = {part.lower() for part in Path(source_path).parts}
    if "public" in parts:
        return {
            "visibility": "public",
            "allowed_departments": [],
            "allowed_users": [],
            "permission_source": "folder_rule",
        }

    return {
        "visibility": "public",
        "allowed_departments": [],
        "allowed_users": [],
        "permission_source": "default_policy",
    }


def match_permission_rule_from_file(
    source_path: str,
    knowledge_base_dir: str | None,
) -> dict[str, Any]:
    """用知识库根目录权限规则匹配当前文档。

    输入的 source_path 可能是绝对路径，也可能是相对路径；规则文件只关心相对
    知识库根目录的路径，例如 `development/a.md`。所以这里会先定位规则文件，
    再把 source_path 转成相对路径，最后用 path_prefix 做前缀匹配。

    多条规则同时命中时，优先选择 path_prefix 更长的规则。例如同时存在
    `development/` 和 `development/private/` 时，后者应该覆盖前者。
    """

    # 没有知识库根目录，就无法定位 .permission-rules.json。
    # 这里返回空 dict，让上层继续走 public 目录兜底或 default_policy。
    if not knowledge_base_dir:
        return {}

    # 规则文件固定放在知识库根目录下，而不是跟着每个文档单独放。
    # 这样同一批知识库文档的权限规则可以集中维护和版本化。
    rules_file = Path(knowledge_base_dir) / PERMISSION_RULES_FILE_NAME
    if not rules_file.exists():
        return {}

    # load_permission_rules_file 会同时完成 JSON 读取、基本结构校验和字段规范化。
    # 这里拿到的 path_prefix 已经统一成类似 `development/` 的小写 POSIX 前缀。
    rules_config = load_permission_rules_file(rules_file)

    relative_path = build_relative_permission_path(
        source_path=source_path,
        knowledge_base_dir=knowledge_base_dir,
    )

    # 收集所有命中的规则。使用 startswith 是为了让一个目录规则覆盖该目录下所有文档。
    # 例如 path_prefix=development/ 可以命中 development/rag-backend-deployment.md。
    matched_rules = [
        rule
        for rule in rules_config.get("rules", [])
        if relative_path.startswith(str(rule.get("path_prefix") or ""))
    ]

    # 没有命中任何 path_prefix 时，使用规则文件里的 default。
    # 如果规则文件没有 default，则返回空 dict，让上层继续走默认 public 策略。
    if not matched_rules:
        default_policy = rules_config.get("default")
        return default_policy if isinstance(default_policy, dict) else {}

    # 选择最长 path_prefix，是为了支持更细粒度的子目录覆盖。
    # 例：development/private/ 的长度大于 development/，因此 private 规则优先。
    matched_rules.sort(
        key=lambda rule: len(str(rule.get("path_prefix") or "")),
        reverse=True,
    )

    rule_policy = {
        key: value
        for key, value in matched_rules[0].items() # 选择最长的路径
        if key != "path_prefix"
    }

    rule_policy.setdefault("permission_source", "permission_rules_file")
    return rule_policy


def load_permission_rules_file(rules_file: Path) -> dict[str, Any]:
    """读取并校验知识库根目录权限规则文件。

    规则文件必须是 JSON object，并通过 rules 数组声明 path_prefix 到权限 metadata
    的映射。这里不校验部门是否存在于数据库，只负责入库 metadata 的结构正确性。
    """

    raw = json.loads(rules_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"权限规则文件必须是 JSON object: {rules_file}")

    rules = raw.get("rules", [])
    if not isinstance(rules, list):
        raise RuntimeError(f"权限规则文件 rules 必须是 JSON array: {rules_file}")

    normalized_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise RuntimeError(f"权限规则项必须是 JSON object: {rules_file}")

        path_prefix = normalize_permission_path_prefix(rule.get("path_prefix"))
        if not path_prefix:
            raise RuntimeError(f"权限规则 path_prefix 不能为空: {rules_file}")

        # 设置当前的rule来源，默认permission_rules_file
        normalized_rule = normalize_permission_metadata(rule)
        normalized_rule["permission_source"] = str(
            rule.get("permission_source") or "permission_rules_file"
        )
        normalized_rule["path_prefix"] = path_prefix
        normalized_rules.append(normalized_rule)

    default_policy = raw.get("default")
    if default_policy is not None and not isinstance(default_policy, dict):
        raise RuntimeError(f"权限规则文件 default 必须是 JSON object: {rules_file}")

    return {
        "rules": normalized_rules,
        "default": (
            normalize_permission_metadata(default_policy)
            if isinstance(default_policy, dict)
            else None
        ),
    }


def normalize_permission_path_prefix(value: object) -> str:
    """把规则里的 path_prefix 规范化成 POSIX 相对目录前缀。"""

    prefix = str(value or "").strip().replace("\\", "/").strip("/")
    return f"{prefix.lower()}/" if prefix else ""


def build_relative_permission_path(
    source_path: str,
    knowledge_base_dir: str,
) -> str:
    """计算文档相对知识库根目录的 POSIX 路径。"""

    source = Path(source_path)
    root = Path(knowledge_base_dir)

    try:
        relative = source.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        source_posix = normalize_source_path(source_path).lower().strip("/")
        root_posix = normalize_source_path(knowledge_base_dir).lower().strip("/")
        if source_posix.startswith(f"{root_posix}/"):
            return source_posix[len(root_posix) + 1 :]
        return source_posix

    return relative.as_posix().lower().strip("/")


def load_sidecar_permission_metadata(source_path: str) -> dict[str, Any]:
    """读取文档旁边的权限 sidecar metadata。

    例如 `combat-design.md.meta.json` 可以覆盖 `combat-design.md` 通过目录规则
    推断出的权限。这个函数只允许权限相关字段透传，避免 sidecar 中的无关字段污染
    chunk metadata。
    """

    sidecar_path = Path(f"{source_path}.meta.json")
    if not sidecar_path.exists():
        return {}

    raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"sidecar metadata 必须是 JSON object: {sidecar_path}")

    allowed_keys = {
        "visibility",
        "allowed_departments",
        "allowed_users",
        "permission_source",
    }
    return {
        key: value
        for key, value in raw.items()
        if key in allowed_keys
    }


def normalize_permission_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化权限 metadata。

    ES / Milvus filter 依赖 visibility、allowed_departments、allowed_users
    这些字段的稳定形状。如果这里不提前规范化，后续检索阶段可能出现 filter 表达式
    正确但 metadata 类型不匹配的问题。
    """

    visibility = str(metadata.get("visibility") or "public")
    if visibility not in {"public", "department", "restricted"}:
        raise RuntimeError(f"不支持的文档 visibility: {visibility}")

    return {
        "visibility": visibility,
        "allowed_departments": normalize_string_list(
            metadata.get("allowed_departments")
        ),
        "allowed_users": normalize_string_list(metadata.get("allowed_users")),
        "permission_source": str(metadata.get("permission_source") or "default_policy"),
    }


def normalize_string_list(value: object) -> list[str]:
    """把权限列表字段规范化为 list[str]。

    allowed_departments 和 allowed_users 都必须是 JSON array。这里不接受字符串
    自动拆分，目的是避免 `\"development,art\"` 这种含糊格式进入权限判断。
    """

    if value is None:
        return []

    if not isinstance(value, list):
        raise RuntimeError("权限列表字段必须是 JSON array")

    return [str(item).strip() for item in value if str(item).strip()]


def build_chunk_metadata(
    document_metadata: dict[str, Any],
    chunk_id: str,
    title: str,
    section_path: list[str],
    heading_level: int,
    section_index: int,
    chunk_index: int,
) -> dict[str, Any]:
    """构造 chunk 级 metadata。

    chunk metadata 以 document_metadata 为基础，再补充 chunk_id、标题路径、
    heading_level 和 chunk_index。这样 API sources、ES 查询和 Milvus 查询都能
    从单个 chunk 上拿到完整追溯信息和权限信息。
    """

    return {
        **document_metadata,
        "chunk_id": chunk_id,
        "title": title,
        "section_path": section_path,
        "heading_level": heading_level,
        "section_index": section_index,
        "chunk_index": chunk_index,
    }
