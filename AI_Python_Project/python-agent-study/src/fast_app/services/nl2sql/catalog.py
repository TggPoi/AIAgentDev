from __future__ import annotations

import asyncpg

from fast_app.services.nl2sql.models import DatasetDefinition


class SchemaCatalog:
    """从 PostgreSQL COMMENT 和白名单视图组装构造 外部大模型 可阅读的 Schema。"""

    async def load(
        self,
        connection: asyncpg.Connection,
        dataset: DatasetDefinition,
        *,
        logical_names: bool,
    ) -> str:
        """生成本次 SQL 模型唯一可见的数据库结构说明。

        查询对象先受 dataset.allowed_views 限制，再从系统目录读取字段类型和
        COMMENT；业务关系与同义词来自可信 Dataset 配置。模型不会获得连接 URL、
        未授权表结构或平台主库 Schema。
        """

        rows = await connection.fetch(
            """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                pg_catalog.col_description(pc.oid, c.ordinal_position) AS column_comment,
                pg_catalog.obj_description(pc.oid, 'pg_class') AS view_comment
            FROM information_schema.columns c
            JOIN pg_catalog.pg_namespace pn ON pn.nspname = c.table_schema
            JOIN pg_catalog.pg_class pc
              ON pc.relnamespace = pn.oid AND pc.relname = c.table_name
            WHERE c.table_schema = 'analytics'
              AND (c.table_schema || '.' || c.table_name) = ANY($1::text[])
            ORDER BY c.table_name, c.ordinal_position
            """,
            list(dataset.allowed_views),
        )
        grouped: dict[str, list[asyncpg.Record]] = {}
        for row in rows:
            grouped.setdefault(f"{row['table_schema']}.{row['table_name']}", []).append(row)

        physical_to_logical = {
            physical: logical for logical, physical in dataset.logical_view_mapping.items()
        }
        # 敏感 Dataset 使用逻辑视图名，避免物理命名细节进入外部 Prompt；执行前
        # 再由后端映射回白名单中的 analytics 物理视图。
        lines = [
            "只能查询以下视图。字段 COMMENT 是业务事实；不得猜测未列出的表、列或指标。",
        ]
        # 格式化文本，把数据库的 COMMENT 和字段类型信息组装为可阅读的文本格式 传给大模型，避免模型凭经验猜测表结构。
        for physical, columns in grouped.items():
            name = physical_to_logical.get(physical, physical) if logical_names else physical
            lines.append(f"\nVIEW {name}")
            lines.append(f"COMMENT: {_metadata_text(columns[0]['view_comment'])}")
            for column in columns:
                lines.append(
                    f"- {column['column_name']} {column['data_type']} "
                    f"nullable={column['is_nullable']}: "
                    f"{_metadata_text(column['column_comment'])}"
                )
        lines.append("\n可用关系：")
        lines.extend(f"- {_metadata_text(item)}" for item in dataset.relationships)
        if dataset.synonyms:
            lines.append("\n业务同义词：")
            lines.extend(
                f"- {_metadata_text(key, 200)}: "
                f"{', '.join(_metadata_text(value, 200) for value in values[:20])}"
                for key, values in dataset.synonyms.items()
            )
        return "\n".join(lines)

    async def load_logical_fields(
        self,
        connection: asyncpg.Connection,
        dataset: DatasetDefinition,
    ) -> set[str]:
        """读取白名单视图的逻辑字段，供 TaskPlan 保存前校验。"""

        rows = await connection.fetch(
            """
            SELECT lower(c.column_name) AS column_name
            FROM information_schema.columns c
            WHERE (c.table_schema || '.' || c.table_name) = ANY($1::text[])
            ORDER BY c.table_name, c.ordinal_position
            """,
            list(dataset.allowed_views),
        )
        return {str(row["column_name"]) for row in rows}


def _metadata_text(value: object, max_chars: int = 1_000) -> str:
    """限制不可信 Dataset metadata 的单项长度并移除控制字符。"""

    text = " ".join(str(value or "无").split())
    return text[:max_chars]


__all__ = ["SchemaCatalog"]
