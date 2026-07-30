from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from fast_app.services.exceptions import Nl2SqlRepairableSqlError, Nl2SqlUnsafeSqlError


_FORBIDDEN_FUNCTIONS = {
    "current_setting",
    "dblink",
    "lo_export",
    "lo_import",
    "pg_read_binary_file",
    "pg_read_file",
    "pg_sleep",
    "set_config",
}
_ALLOWED_FUNCTIONS = {
    "abs",
    "avg",
    "ceil",
    "coalesce",
    "count",
    "cast",
    "date_trunc",
    "floor",
    "greatest",
    "least",
    "lower",
    "max",
    "min",
    "nullif",
    "round",
    "row_number",
    "sum",
    "upper",
}
_NAMED_PARAMETER = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class ValidatedSql:
    parameterized_sql: str
    asyncpg_sql: str
    parameter_order: tuple[str, ...]


class SqlPolicy:
    """真正决定“能不能执行大模型生成的SQL” ；PostgreSQL AST 白名单、行数限制和 bind 参数转换。"""

    def validate(
        self,
        sql: str,
        *,
        allowed_views: tuple[str, ...],
        max_rows: int,
        parameters: dict[str, object],
    ) -> ValidatedSql:
        """把模型 SQL 收敛成可执行的只读语句。

        校验基于 SQLGlot AST，而不是在字符串里搜索 ``DROP`` 等关键词。AST 能
        区分表、CTE、函数、LIMIT 和命令类型，避免别名、大小写或嵌套查询绕过规则。
        """

        # 第一阶段：必须能够按 PostgreSQL 方言解析成且仅解析成一棵语句树。
        try:
            statements = parse(sql, read="postgres")
        except ParseError as exc:
            raise Nl2SqlRepairableSqlError("SQL 语法无法解析") from exc
        if len(statements) != 1:
            raise Nl2SqlUnsafeSqlError("只允许单条 SQL")
        tree = statements[0]
        if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise Nl2SqlUnsafeSqlError("只允许 SELECT 查询")
        if any(
            tree.find(kind) is not None
            for kind in (
                exp.Insert,
                exp.Update,
                exp.Delete,
                exp.Create,
                exp.Drop,
                exp.Alter,
                exp.Command,
                exp.Copy,
                exp.Transaction,
            )
        ):
            raise Nl2SqlUnsafeSqlError("SQL 包含禁止的写入或控制命令")
        if any(
            not isinstance(star.parent, exp.Count)
            for star in tree.find_all(exp.Star)
        ):
            raise Nl2SqlUnsafeSqlError("禁止 SELECT *，必须显式列出字段")

        # CTE 名是本条查询内部产生的临时结果，不需要出现在 Dataset 白名单；
        # CTE 内真正读取的物理表/视图仍会在下面逐个接受 allowed_views 校验。
        cte_names = {
            cte.alias_or_name.lower()
            for cte in tree.find_all(exp.CTE)
            if cte.alias_or_name
        }
        allowed = {item.lower() for item in allowed_views}
        for table in tree.find_all(exp.Table):
            name = table.name.lower()
            if name in cte_names:
                continue
            qualified = (
                f"{table.db}.{table.name}".lower() if table.db else table.name.lower()
            )
            if qualified not in allowed:
                raise Nl2SqlUnsafeSqlError(f"SQL 引用了非白名单对象: {qualified}")

        for function in tree.find_all(exp.Func):
            name = (
                function.name.lower()
                if isinstance(function, exp.Anonymous)
                else function.sql_name().lower()
            )
            if name in _FORBIDDEN_FUNCTIONS or (
                isinstance(function, exp.Anonymous)
                and name not in _ALLOWED_FUNCTIONS
            ):
                raise Nl2SqlUnsafeSqlError(f"SQL 使用了非白名单函数: {name}")

        # 额外读取一行只用于判断 truncated；响应仍最多返回 max_rows 行。
        fetch_limit = min(max_rows, 500) + 1
        limit = tree.args.get("limit")
        if limit is None:
            tree = tree.limit(fetch_limit)
        else:
            expression = limit.expression
            if isinstance(expression, exp.Placeholder):
                name = expression.name
                value = parameters.get(name)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise Nl2SqlUnsafeSqlError("LIMIT 参数必须是正整数")
                if value > fetch_limit:
                    tree.set(
                        "limit",
                        exp.Limit(expression=exp.Literal.number(fetch_limit)),
                    )
                    parameters = {key: item for key, item in parameters.items() if key != name}
            elif isinstance(expression, exp.Literal) and expression.is_int:
                if int(expression.this) > fetch_limit:
                    tree.set(
                        "limit",
                        exp.Limit(expression=exp.Literal.number(fetch_limit)),
                    )
            else:
                raise Nl2SqlUnsafeSqlError("LIMIT 必须是整数常量或受控参数")

        # 默认 emitter 保留 ``:name``；PostgreSQL emitter 会改成 psycopg
        # ``%(name)s``，不适用于 asyncpg 的位置参数协议。
        normalized = tree.sql()
        parameter_order: list[str] = []

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in parameters:
                raise Nl2SqlUnsafeSqlError(f"SQL 参数缺失: {name}")
            if name not in parameter_order:
                parameter_order.append(name)
            return f"${parameter_order.index(name) + 1}"

        asyncpg_sql = _NAMED_PARAMETER.sub(replace, normalized)
        # 参数集合必须与 SQL 实际引用完全一致：缺参和模型凭空附带的多余参数
        # 都拒绝，防止“校验的是一组值、执行的又是另一组值”。
        if set(parameters) != set(parameter_order):
            raise Nl2SqlUnsafeSqlError("模型返回了 SQL 未使用的参数")
        return ValidatedSql(
            parameterized_sql=normalized,
            asyncpg_sql=asyncpg_sql,
            parameter_order=tuple(parameter_order),
        )


__all__ = ["SqlPolicy", "ValidatedSql"]
