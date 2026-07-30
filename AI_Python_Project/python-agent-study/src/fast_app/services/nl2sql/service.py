from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from fast_app.core.config import Settings
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.db.nl2sql_tables import Nl2SqlQueryAuditTable
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import (
    Nl2SqlDisabledError,
    Nl2SqlExecutionError,
    Nl2SqlRepairableSqlError,
    Nl2SqlSensitiveReportForbiddenError,
)
from fast_app.services.nl2sql.authorization import Nl2SqlAuthorizationService
from fast_app.services.nl2sql.catalog import SchemaCatalog
from fast_app.services.nl2sql.models import (
    DatasetAuthorization,
    DatasetDefinition,
    Nl2SqlDatasetItem,
    Nl2SqlQueryResult,
    SqlGenerationResult,
)
from fast_app.services.nl2sql.registry import DatasetRegistry
from fast_app.services.nl2sql.sql_policy import SqlPolicy, ValidatedSql


class Nl2SqlService:
    """授权、标记化、SQL 模型、AST、RLS 执行和安全审计的单一入口。"""

    def __init__(
        self,
        settings: Settings,
        registry: DatasetRegistry,
        session: AsyncSession,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._session = session
        self._authorization = Nl2SqlAuthorizationService(session)
        self._catalog = SchemaCatalog()
        self._policy = SqlPolicy()

    async def list_datasets(
        self, user: CurrentUserContext
    ) -> list[Nl2SqlDatasetItem]:
        if not self._settings.nl2sql_enabled:
            return []
        visible: list[Nl2SqlDatasetItem] = []
        for dataset in self._registry.enabled():
            try:
                await self._authorization.authorize(user, dataset)
            except Exception:
                continue
            visible.append(
                Nl2SqlDatasetItem(
                    dataset_id=dataset.dataset_id,
                    name=dataset.name,
                    domain=dataset.domain,
                    privacy_classification=dataset.privacy_classification,
                    report_supported=dataset.report_supported,
                )
            )
        return visible

    async def authorize_action(
        self,
        *,
        user: CurrentUserContext,
        dataset_id: str,
        action: str,
    ) -> tuple[DatasetDefinition, DatasetAuthorization]:
        if not self._settings.nl2sql_enabled:
            raise Nl2SqlDisabledError("NL2SQL 功能未启用")
        dataset = self._registry.get(dataset_id)
        if action == "report" and not dataset.report_supported:
            raise Nl2SqlSensitiveReportForbiddenError(
                "敏感房地产 Dataset 禁止进入外部模型报告链路"
            )
        return dataset, await self._authorization.authorize(user, dataset)

    async def query(
        self,
        *,
        user: CurrentUserContext,
        dataset_id: str,
        question: str,
        max_rows: int | None = None,
    ) -> Nl2SqlQueryResult:
        started = perf_counter()
        try:
            return await self._query_impl(
                user=user,
                dataset_id=dataset_id,
                question=question,
                max_rows=max_rows,
            )
        except Exception as exc:
            # 失败审计宁可少记也不越过隐私边界：原始问题、参数、数据库错误
            # 和结果行一律不保存。成功路径会保存标记化问题和参数化 SQL。
            try:
                self._session.add(
                    Nl2SqlQueryAuditTable(
                        query_id=str(uuid4()),
                        user_id=user.user_id,
                        dataset_id=dataset_id,
                        tokenized_question="[REDACTED]",
                        parameterized_sql="",
                        sql_hash=hashlib.sha256(b"").hexdigest(),
                        status="failed",
                        execution_ms=round((perf_counter() - started) * 1000),
                        row_count=0,
                        error_code=str(
                            getattr(exc, "error_code", type(exc).__name__)
                        )[:128],
                        request_id=get_request_id(),
                        trace_id=get_trace_id(),
                    )
                )
                await self._session.commit()
            except Exception:
                await self._session.rollback()
            raise

    async def _query_impl(
        self,
        *,
        user: CurrentUserContext,
        dataset_id: str,
        question: str,
        max_rows: int | None = None,
    ) -> Nl2SqlQueryResult:
        """执行一轮完整 NL2SQL 查询。

        这里是模块的主编排函数：先得到服务端可信的 Dataset/Scope，再按隐私等级
        准备模型输入，随后让模型生成参数化 SQL。模型不接触数据库连接；真正的
        AST 校验、参数绑定、RLS 查询、结果序列化、总结和审计都由后端完成。
        """

        # 第一道边界同时检查功能权限和 Dataset Grant。客户端只能选择 dataset_id，
        # 不能把自己的 project_id/scope_ids 塞进请求来扩大查询范围。
        dataset, authorization = await self.authorize_action(
            user=user, dataset_id=dataset_id, action="query"
        )
        query_id = str(uuid4())
        row_limit = min(max_rows or self._settings.nl2sql_default_max_rows, 500)
        pool = await self._registry.pool(dataset)
        tokenized_question = question
        # Vault 只活在当前 Python 调用栈中，不写 TaskPlan、审计、日志或模型 Prompt。
        # 房地产占位符由模型原样引用，真实值直到数据库执行前才在本地取回。
        vault: dict[str, Any] = {}
        async with pool.acquire() as connection:
            if dataset.privacy_classification == "sensitive":
                tokenized_question, vault = await self._tokenize_sensitive_question(
                    connection=connection,
                    dataset=dataset,
                    authorization=authorization,
                    question=question,
                )
            catalog = await self._catalog.load(
                connection,
                dataset,
                logical_names=dataset.privacy_classification == "sensitive",
            )

        # 业务查询 SQL 并没有固定在 Python 代码里。模型根据本次问题、允许查询的
        # analytics 视图、字段 COMMENT、关系和同义词动态生成 SqlGenerationResult。
        generation = await self._generate_sql(
            dataset=dataset,
            catalog=catalog,
            question=tokenized_question,
        )
        attempts = 1
        try:
            result = await self._execute_generation(
                pool=pool,
                dataset=dataset,
                authorization=authorization,
                generation=generation,
                vault=vault,
                max_rows=row_limit,
            )
        except (
            Nl2SqlRepairableSqlError,
            asyncpg.PostgresSyntaxError,
            asyncpg.UndefinedColumnError,
            asyncpg.DatatypeMismatchError,
        ) as exc:
            attempts = 2
            generation = await self._generate_sql(
                dataset=dataset,
                catalog=catalog,
                question=tokenized_question,
                repair_category=type(exc).__name__,
            )
            try:
                result = await self._execute_generation(
                    pool=pool,
                    dataset=dataset,
                    authorization=authorization,
                    generation=generation,
                    vault=vault,
                    max_rows=row_limit,
                )
            except asyncpg.QueryCanceledError:
                raise Nl2SqlExecutionError("数据库查询超时") from None
            except asyncpg.PostgresError:
                raise Nl2SqlExecutionError("数据库拒绝了该只读查询") from None
        except asyncpg.QueryCanceledError:
            raise Nl2SqlExecutionError("数据库查询超时") from None
        except asyncpg.PostgresError:
            raise Nl2SqlExecutionError("数据库拒绝了该只读查询") from None

        validated, records, execution_ms = result
        rows, warnings = _serialize_records(records[:row_limit])
        truncated = len(records) > row_limit
        if truncated:
            warnings.append(f"结果超过 {row_limit} 行，响应已截断")
        markdown_table = _to_markdown_table(rows)
        if dataset.privacy_classification == "sensitive":
            # 房地产真实结果绝不进入第二次外部模型调用，只允许本地模板使用
            # row_count/truncated 等后端提供的有限字段生成结论。
            summary = _fill_sensitive_summary(
                generation.summary_template,
                vault=vault,
                row_count=len(rows),
                truncated=truncated,
            )
        else:
            summary = await self._summarize_game_result(
                question=question,
                parameterized_sql=validated.parameterized_sql,
                rows=rows,
            )

        response = Nl2SqlQueryResult(
            query_id=query_id,
            request_id=get_request_id(),
            trace_id=get_trace_id(),
            dataset_id=dataset.dataset_id,
            parameterized_sql=validated.parameterized_sql,
            columns=list(rows[0]) if rows else list(records[0].keys()) if records else [],
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution_ms=execution_ms,
            attempt_count=attempts,
            summary=summary,
            warnings=warnings,
            markdown_table=markdown_table,
        )
        self._session.add(
            Nl2SqlQueryAuditTable(
                query_id=query_id,
                user_id=user.user_id,
                dataset_id=dataset.dataset_id,
                tokenized_question=tokenized_question,
                parameterized_sql=validated.parameterized_sql,
                sql_hash=hashlib.sha256(
                    validated.parameterized_sql.encode("utf-8")
                ).hexdigest(),
                status="completed",
                execution_ms=execution_ms,
                row_count=len(rows),
                error_code=None,
                request_id=get_request_id(),
                trace_id=get_trace_id(),
            )
        )
        await self._session.commit()
        return response

    async def _tokenize_sensitive_question(
        self,
        *,
        connection: asyncpg.Connection,
        dataset: DatasetDefinition,
        authorization: DatasetAuthorization,
        question: str,
    ) -> tuple[str, dict[str, Any]]:
        """把房地产问题中的真实实体和值替换为带类型的请求级占位符。

        返回值由两部分组成：可发送给外部 SQL 模型的标记化问题，以及只保存在
        本地内存的 Vault。这里固定的是敏感实体目录的读取契约，不是最终业务查询
        SQL；最终 SELECT 仍由模型按问题动态生成。
        """

        async with connection.transaction(readonly=True):
            # 本地目录必须覆盖所有实体；否则用户写出未授权楼盘名时，该名称会
            # 因当前 Scope 查不到而原样进入外部模型。这里只识别并标记化，
            # 后续真实查询仍严格使用 authorization.scope_ids 执行。
            await _set_scope(connection, ("*",))
            records = await connection.fetch(
                """
                SELECT DISTINCT
                    project_name,
                    building_name,
                    address,
                    project_id,
                    business_code,
                    unit_no,
                    unit_type_name,
                    orientation,
                    inventory_status
                FROM analytics.unit_inventory
                """
            )
        aliases: dict[str, tuple[str, Any]] = {}
        for record in records:
            for key, value in record.items():
                if value is None or len(str(value)) < 1:
                    continue
                aliases[str(value)] = (key.upper(), value)
                if key == "orientation":
                    aliases[f"{value}向"] = ("ORIENTATION", value)
        tokenized = question
        vault: dict[str, Any] = {}
        token_counters: dict[str, int] = {}
        for alias in sorted(aliases, key=len, reverse=True):
            if alias not in tokenized:
                continue
            kind, actual_value = aliases[alias]
            token_counters[kind] = token_counters.get(kind, 0) + 1
            token = f"__{kind}_{token_counters[kind]}__"
            tokenized = tokenized.replace(alias, token)
            vault[token] = actual_value
        room_numbers = {"二": 2, "两": 2, "三": 3, "四": 4}
        for match in list(re.finditer(r"[二两三四](?=居)", tokenized)):
            value = match.group(0)
            token_counters["ROOM_COUNT"] = token_counters.get("ROOM_COUNT", 0) + 1
            token = f"__ROOM_COUNT_{token_counters['ROOM_COUNT']}__"
            tokenized = tokenized.replace(value, token, 1)
            vault[token] = room_numbers[value]
        # Python 的 ``\w`` 会把中文也视为单词字符；价格常紧邻“低于/元”，
        # 因此这里只排除 ASCII 标识符和小数点邻接。
        for match in list(
            re.finditer(
                r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_.])",
                tokenized,
            )
        ):
            value = match.group(0)
            token_counters["NUMBER"] = token_counters.get("NUMBER", 0) + 1
            token = f"__NUMBER_{token_counters['NUMBER']}__"
            tokenized = tokenized.replace(value, token, 1)
            vault[token] = Decimal(value) if "." in value else int(value)
        return tokenized, vault

    async def _generate_sql(
        self,
        *,
        dataset: DatasetDefinition,
        catalog: str,
        question: str,
        repair_category: str | None = None,
    ) -> SqlGenerationResult:
        """让外部模型生成受 Pydantic 约束的参数化 SQL，而不授予数据库访问权。"""

        model = ChatOpenAI(
            name=f"nl2sql.{dataset.domain}.sql_generation.model",
            model=self._settings.nl2sql_model_name or self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=self._settings.nl2sql_model_temperature,
            timeout=self._settings.nl2sql_model_timeout_seconds,
            max_retries=0,
            **(
                {"extra_body": {"enable_thinking": False}}
                if (self._settings.nl2sql_model_name or self._settings.llm_model_name)
                .lower()
                .startswith("qwen")
                else {}
            ),
        ).with_structured_output(
            SqlGenerationResult, method="function_calling"
        ).with_config(run_name=f"nl2sql.{dataset.domain}.sql_generation")
        privacy_rule = (
            "问题中的 __PROJECT_NAME_N__、__INVENTORY_STATUS_N__、"
            "__ORIENTATION_N__、__ROOM_COUNT_N__、__NUMBER_N__ 等是带语义但不可还原"
            "的占位符。SQL 必须按占位符类型选择对应字段并使用 :pN 参数；"
            "parameters 的值只能原样引用这些占位符，绝不猜测真实值。"
            if dataset.privacy_classification == "sensitive"
            else "所有来自问题的过滤值都必须放进 parameters，并在 SQL 中用 :pN 引用。"
        )
        repair = (
            f"\n上一次 SQL 的后端错误类别为 {repair_category}。只修复该类错误，不扩展查询范围。"
            if repair_category
            else ""
        )
        response = await asyncio.wait_for(
            model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是 PostgreSQL NL2SQL 生成器。只输出一条 SELECT/CTE；"
                            "显式列名，禁止 SELECT *、系统表、写操作、SET、set_config/current_setting。"
                            "只使用给定视图和字段。summary_template 不得声称未查询的事实。"
                        )
                    ),
                    HumanMessage(
                        content=f"{catalog}\n\n规则：{privacy_rule}{repair}\n\n问题：{question}"
                    ),
                ]
            ),
            timeout=self._settings.nl2sql_model_timeout_seconds,
        )
        return (
            response
            if isinstance(response, SqlGenerationResult)
            else SqlGenerationResult.model_validate(response)
        )

    async def _execute_generation(
        self,
        *,
        pool: asyncpg.Pool,
        dataset: DatasetDefinition,
        authorization: DatasetAuthorization,
        generation: SqlGenerationResult,
        vault: dict[str, Any],
        max_rows: int,
    ) -> tuple[ValidatedSql, list[asyncpg.Record], int]:
        """真正执行SQL语句的函数；在本地完成视图映射、Vault 回填、安全校验和受 RLS 保护的只读查询。"""

        sql = generation.parameterized_sql
        if dataset.privacy_classification == "sensitive":
            for logical, physical in dataset.logical_view_mapping.items():
                sql = re.sub(rf"\b{re.escape(logical)}\b", physical, sql)
        parameters = dict(generation.parameters)
        if dataset.privacy_classification == "sensitive":
            for name, value in parameters.items():
                if not isinstance(value, str) or value not in vault:
                    raise Nl2SqlExecutionError("敏感 Dataset 的模型参数不是受信占位符")
                parameters[name] = vault[value]
        validated = self._policy.validate(
            sql,
            allowed_views=dataset.allowed_views,
            max_rows=max_rows,
            parameters=parameters,
        )
        # SqlPolicy 已把模型使用的 ``:p1`` 命名参数按出现顺序转换成 asyncpg 的
        # ``$1`` 位置参数；这里只按同一顺序取真实值，SQL 文本不会拼接用户输入。
        ordered_values = [parameters[name] for name in validated.parameter_order]
        started = perf_counter()
        async with pool.acquire() as connection:
            async with connection.transaction(readonly=True):
                await connection.execute("SET LOCAL statement_timeout = '8s'")
                await connection.execute("SET LOCAL lock_timeout = '1s'")
                await connection.execute("SET LOCAL search_path = analytics, pg_catalog")
                await _set_scope(connection, authorization.scope_ids)
                records = await connection.fetch(validated.asyncpg_sql, *ordered_values)
        return validated, records, round((perf_counter() - started) * 1000)

    async def _summarize_game_result(
        self,
        *,
        question: str,
        parameterized_sql: str,
        rows: list[dict[str, Any]],
    ) -> str:
        model = ChatOpenAI(
            name="nl2sql.game.result_summary.model",
            model=self._settings.nl2sql_model_name or self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.1,
            timeout=self._settings.nl2sql_model_timeout_seconds,
            max_retries=0,
            **(
                {"extra_body": {"enable_thinking": False}}
                if (self._settings.nl2sql_model_name or self._settings.llm_model_name)
                .lower()
                .startswith("qwen")
                else {}
            ),
        )
        response = await asyncio.wait_for(
            model.ainvoke(
                [
                    SystemMessage(content="只根据给定游戏资产查询结果生成简洁中文结论，不补充外部事实。"),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "question": question,
                                "parameterized_sql": parameterized_sql,
                                "rows": rows,
                            },
                            ensure_ascii=False,
                        )
                    ),
                ]
            ),
            timeout=self._settings.nl2sql_model_timeout_seconds,
        )
        return str(getattr(response, "content", response)).strip()


async def _set_scope(
    connection: asyncpg.Connection,
    scope_ids: tuple[str, ...],
) -> None:
    await connection.fetchval(
        "SELECT set_config('app.scope_ids', $1, true)",
        ",".join(scope_ids),
    )


def _serialize_records(
    records: list[asyncpg.Record],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, Decimal):
                row[key] = str(value)
            elif isinstance(value, (date, datetime)):
                row[key] = value.isoformat()
            elif isinstance(value, UUID):
                row[key] = str(value)
            elif isinstance(value, str) and len(value) > 2000:
                row[key] = value[:2000]
                warning = f"字段 {key} 的长文本已截断到 2000 字符"
                if warning not in warnings:
                    warnings.append(warning)
            else:
                row[key] = value
        rows.append(row)
    return rows, warnings


def _fill_sensitive_summary(
    template: str,
    *,
    vault: dict[str, Any],
    row_count: int,
    truncated: bool,
) -> str:
    """在本地回填敏感查询结论，只允许后端掌握的有限模板字段。"""

    result = template
    for token, value in vault.items():
        result = result.replace(token, str(value))
    unknown_fields = re.findall(r"\{([^{}]+)\}", result)
    if any(item not in {"row_count", "truncated"} for item in unknown_fields):
        result = "查询返回 {row_count} 行结果。"
    return result.replace("{row_count}", str(row_count)).replace(
        "{truncated}", "是" if truncated else "否"
    )


def _to_markdown_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_查询无结果_"
    columns = list(rows[0])

    def cell(value: Any) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(cell(row.get(column)) for column in columns) + " |"
        for row in rows
    )
    return "\n".join(lines)


__all__ = ["Nl2SqlService"]
