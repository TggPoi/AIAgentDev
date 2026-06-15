from collections.abc import Mapping

from fast_app.evaluation.eval_case_models import RagEvalCase
from fast_app.evaluation.generation_eval_models import (
    GenerationCaseResult,
    GenerationCheck,
    GenerationDatasetReport,
)
from fast_app.schemas.rag_chat_schema import RagChatResponse


DEFAULT_REFUSAL_MARKERS = [
    "当前知识库中没有足够信息",
    "没有足够信息",
    "无法根据检索上下文",
]


def normalize_text(text: str) -> str:
    """把文本转换成适合规则匹配的形式。

    这里做两件事：
    - lower：减少英文大小写差异影响，例如 RRF / rrf。
    - split + join：减少换行和多空格对匹配的影响。
    """

    return " ".join(text.lower().split())


def check_expected_keywords(
    answer: str,
    expected_keywords: list[str],
) -> GenerationCheck:
    """检查 answer 是否覆盖可回答样例的关键点。"""

    # 先把 answer 归一化，避免换行、多个空格、英文大小写影响关键词匹配。
    normalized_answer = normalize_text(answer)

    # missing_keywords 表示“评测集要求出现，但 answer 没出现”的关键词。
    # 如果这个列表为空，说明 answer 覆盖了当前 case 预期的关键点。
    missing_keywords = [
        keyword
        for keyword in expected_keywords
        if keyword.lower() not in normalized_answer
    ]

    return GenerationCheck(
        name="expected_keywords",
        passed=not missing_keywords,
        message="回答覆盖了预期关键词" if not missing_keywords else "回答缺少预期关键词",
        detail={
            "expected_keywords": expected_keywords,
            "missing_keywords": missing_keywords,
        },
    )


def check_forbidden_keywords(
    answer: str,
    forbidden_keywords: list[str],
) -> GenerationCheck:
    """检查 answer 是否出现不该出现的词。

    这个规则常用于 no_answer 样例。
    例如天气问题不应该编造“晴天、下雨、温度”等具体事实。
    """

    # forbidden_keywords 通常用于发现“明显编造”。
    # 例如 no_answer_weather 不应该回答具体天气、温度。
    normalized_answer = normalize_text(answer)

    # found_keywords 表示 answer 中实际出现了哪些禁止词。
    # 只要出现一个，就说明这条检查失败。
    found_keywords = [
        keyword
        for keyword in forbidden_keywords
        if keyword.lower() in normalized_answer
    ]

    return GenerationCheck(
        name="forbidden_keywords",
        passed=not found_keywords,
        message="回答未出现禁止关键词" if not found_keywords else "回答出现禁止关键词",
        detail={
            "forbidden_keywords": forbidden_keywords,
            "found_keywords": found_keywords,
        },
    )


def check_no_answer_refusal(
    answer: str,
    refusal_markers: list[str] | None = None,
) -> GenerationCheck:
    """检查无答案问题是否明确拒答。

    当前拒答标志和 Qwen RAG prompt 中的保守回答保持一致。
    如果后续修改 prompt 中的拒答话术，这里的 marker 也要同步调整。
    """

    # refusal_markers 是“拒答话术”的候选列表。
    # 不直接要求 answer 完全等于某一句话，是为了允许模型有轻微表达差异。
    markers = refusal_markers or DEFAULT_REFUSAL_MARKERS
    normalized_answer = normalize_text(answer)

    # matched_markers 表示 answer 命中了哪些拒答标志。
    # no_answer 样例至少要命中一个拒答标志，才算明确拒答。
    matched_markers = [
        marker
        for marker in markers
        if marker.lower() in normalized_answer
    ]

    return GenerationCheck(
        name="no_answer_refusal",
        passed=bool(matched_markers),
        message="无答案问题已拒答" if matched_markers else "无答案问题没有明确拒答",
        detail={
            "refusal_markers": markers,
            "matched_markers": matched_markers,
        },
    )


def check_source_presence(response: RagChatResponse) -> GenerationCheck:
    """检查 response 是否带有 sources。

    对 answerable 样例来说，sources 是回答可追溯的基础。
    """

    # sources 非空不代表回答一定正确，但它是 RAG 回答可追溯的最低要求。
    # 如果 answerable 样例没有 sources，后续就无法判断回答依据来自哪里。
    return GenerationCheck(
        name="source_presence",
        passed=bool(response.sources),
        message="回答包含 sources" if response.sources else "回答没有 sources",
        detail={"source_count": len(response.sources)},
    )


def check_source_citation(response: RagChatResponse) -> GenerationCheck:
    """检查 answer 是否引用了 sources 中的 id。

    这只是轻量引用检查：
    - 能证明 answer 里出现了 source id。
    - 不能证明引用内容一定真的支持 answer。
    """

    # 当前 Prompt 要求模型尽量引用文档 id。
    # 这里检查 answer 文本中是否出现了 sources 里的 id。
    cited_source_ids = [
        source.id
        for source in response.sources
        if source.id in response.answer
    ]

    return GenerationCheck(
        name="source_citation",
        passed=bool(cited_source_ids),
        message="回答引用了 source id" if cited_source_ids else "回答没有引用 source id",
        detail={
            "source_ids": [source.id for source in response.sources],
            "cited_source_ids": cited_source_ids,
        },
    )


def evaluate_generation_case(
    eval_case: RagEvalCase,
    response: RagChatResponse,
) -> GenerationCaseResult:
    """评测单条 case 的生成结果。

    answerable 样例关注：
    - 是否覆盖预期关键词
    - 是否有 sources
    - 是否引用 source id

    no_answer 样例关注：
    - 是否明确拒答
    - 是否避免出现禁止关键词
    """

    # checks 保存这条 case 的所有规则检查结果。
    # 最终 passed = 所有检查都通过。
    checks: list[GenerationCheck] = []

    if eval_case.case_type == "answerable":
        # answerable 表示知识库应该能回答。
        # 所以这里要求 answer 覆盖关键点，并且能回溯到 sources。
        checks.append(
            check_expected_keywords(
                answer=response.answer,
                expected_keywords=eval_case.expected_answer_keywords,
            )
        )
        checks.append(check_source_presence(response))
        checks.append(check_source_citation(response))

    if eval_case.case_type == "no_answer":
        # no_answer 表示知识库不应该有答案。
        # 所以这里不检查 expected keywords，而是检查“是否拒答”和“是否避免编造具体事实”。
        checks.append(check_no_answer_refusal(response.answer))
        checks.append(
            check_forbidden_keywords(
                answer=response.answer,
                forbidden_keywords=eval_case.forbidden_answer_keywords,
            )
        )

    # 这条 case 的生成评测是否通过，由所有规则检查共同决定。
    # 只要其中一个 check 失败，整条 case 就失败。
    passed = all(check.passed for check in checks)

    return GenerationCaseResult(
        case_id=eval_case.id,
        question=eval_case.question,
        case_type=eval_case.case_type,
        passed=passed,
        answer_length=len(response.answer),
        source_count=len(response.sources),
        checks=checks,
    )


def evaluate_generation_dataset(
    cases: list[RagEvalCase],
    responses_by_case_id: Mapping[str, RagChatResponse],
) -> GenerationDatasetReport:
    """聚合多条 case 的生成评测结果。

    responses_by_case_id 由外层提供。
    这样 generation_metrics 不依赖具体 Pipeline，也不负责调用 LLM。
    """

    # results 保存所有“有 response 的 case”的生成评测结果。
    # 如果某个 case 没有 response，说明外层还没有执行这条请求，这里先跳过。
    results: list[GenerationCaseResult] = []

    for eval_case in cases:
        response = responses_by_case_id.get(eval_case.id)

        if response is None:
            continue

        # 单条 case 的规则判断交给 evaluate_generation_case。
        # dataset 层只负责循环和汇总，不重复写规则。
        results.append(
            evaluate_generation_case(
                eval_case=eval_case,
                response=response,
            )
        )

    # evaluated_case_count 是实际参与生成评测的 case 数量。
    # 它可能小于 len(cases)，因为 responses_by_case_id 里可能没有覆盖全部 case。
    evaluated_case_count = len(results)

    # passed_case_count / failed_case_count 用于快速判断这批生成结果整体是否合格。
    passed_case_count = sum(1 for result in results if result.passed)
    failed_case_count = evaluated_case_count - passed_case_count

    # pass_rate 是生成评测通过率。
    # 如果 evaluated_case_count 为 0，不能除以 0，所以返回 0.0。
    pass_rate = (
        passed_case_count / evaluated_case_count
        if evaluated_case_count
        else 0.0
    )

    return GenerationDatasetReport(
        case_count=len(cases),
        evaluated_case_count=evaluated_case_count,
        passed_case_count=passed_case_count,
        failed_case_count=failed_case_count,
        pass_rate=pass_rate,
        results=results,
    )
