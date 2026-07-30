CREATE SCHEMA IF NOT EXISTS business;
CREATE SCHEMA IF NOT EXISTS analytics;
SELECT set_config('app.scope_ids', '*', false);

CREATE TABLE IF NOT EXISTS business.projects (
    project_id text PRIMARY KEY,
    project_name text NOT NULL UNIQUE,
    genre text NOT NULL
);
CREATE TABLE IF NOT EXISTS business.asset_categories (
    category_code text PRIMARY KEY,
    category_name text NOT NULL UNIQUE,
    model_asset boolean NOT NULL
);
CREATE TABLE IF NOT EXISTS business.assets (
    asset_id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES business.projects(project_id),
    category_code text NOT NULL REFERENCES business.asset_categories(category_code),
    asset_name text NOT NULL,
    cost_yuan numeric(12,2) NOT NULL CHECK (cost_yuan >= 0),
    usage_scenario text NOT NULL,
    license_status text NOT NULL CHECK (license_status IN ('已授权', '待确认', '仅内部使用')),
    polygon_count integer,
    UNIQUE (project_id, asset_name),
    CHECK (
        (category_code = 'model' AND polygon_count IS NOT NULL AND polygon_count > 0)
        OR (category_code <> 'model' AND polygon_count IS NULL)
    )
);

TRUNCATE business.assets, business.asset_categories, business.projects CASCADE;
INSERT INTO business.projects VALUES
('game_p1', '星港远征', '科幻策略'), ('game_p2', '山海旅人', '国风冒险'), ('game_p3', '极速街区', '竞速');
INSERT INTO business.asset_categories VALUES
('model', '3D模型', true), ('texture', '贴图材质', false), ('audio', '音频', false),
('ui', 'UI组件', false), ('vfx', '特效', false);
INSERT INTO business.assets (
    asset_id, project_id, category_code, asset_name, cost_yuan,
    usage_scenario, license_status, polygon_count
)
SELECT
    'asset_' || lpad(gs::text, 3, '0'),
    'game_p' || (((gs - 1) / 15) + 1),
    (ARRAY['model', 'texture', 'audio', 'ui', 'vfx'])[((gs - 1) % 5) + 1],
    (ARRAY['角色', '场景', '载具', '道具', '界面'])[((gs - 1) % 5) + 1] || '资产' || lpad(gs::text, 2, '0'),
    800 + gs * 275,
    (ARRAY['主城展示', '战斗关卡', '剧情演出', '活动界面', '环境氛围'])[((gs - 1) % 5) + 1],
    (ARRAY['已授权', '已授权', '待确认', '仅内部使用'])[((gs - 1) % 4) + 1],
    CASE WHEN ((gs - 1) % 5) = 0 THEN 8000 + gs * 1200 ELSE NULL END
FROM generate_series(1, 45) AS gs;

ALTER TABLE business.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.projects FORCE ROW LEVEL SECURITY;
ALTER TABLE business.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.assets FORCE ROW LEVEL SECURITY;
ALTER TABLE business.asset_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.asset_categories FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS projects_scope ON business.projects;
CREATE POLICY projects_scope ON business.projects USING (
    '*' = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
    OR project_id = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
);
DROP POLICY IF EXISTS assets_scope ON business.assets;
CREATE POLICY assets_scope ON business.assets USING (
    '*' = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
    OR project_id = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
);
DROP POLICY IF EXISTS categories_read ON business.asset_categories;
CREATE POLICY categories_read ON business.asset_categories USING (
    COALESCE(current_setting('app.scope_ids', true), '') <> ''
);

CREATE OR REPLACE VIEW analytics.asset_catalog
WITH (security_invoker=true) AS
SELECT
    a.project_id,
    p.project_name,
    a.asset_id,
    a.asset_name,
    a.cost_yuan,
    c.category_name,
    a.usage_scenario,
    a.license_status,
    a.polygon_count
FROM business.assets a
JOIN business.projects p ON p.project_id = a.project_id
JOIN business.asset_categories c ON c.category_code = a.category_code;

CREATE OR REPLACE VIEW analytics.project_asset_summary
WITH (security_invoker=true) AS
SELECT
    a.project_id,
    p.project_name,
    c.category_name,
    count(*) AS asset_count,
    sum(a.cost_yuan) AS total_cost_yuan,
    round(avg(a.cost_yuan), 2) AS average_cost_yuan,
    round(avg(a.polygon_count), 0) AS average_polygon_count
FROM business.assets a
JOIN business.projects p ON p.project_id = a.project_id
JOIN business.asset_categories c ON c.category_code = a.category_code
GROUP BY a.project_id, p.project_name, c.category_name;

COMMENT ON VIEW analytics.asset_catalog IS '游戏资产目录明细；每行一个资产；project_id 是 RLS 作用域；可按 project_id 与 project_asset_summary 连接。';
COMMENT ON COLUMN analytics.asset_catalog.project_id IS '游戏项目范围 ID；维度字段；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.project_name IS '游戏项目名称；非敏感维度；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.asset_id IS '资产稳定 ID；维度字段；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.asset_name IS '资产名称；非敏感维度；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.cost_yuan IS '资产采购或制作费用，单位人民币元；可求和、平均、最小或最大；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.category_name IS '资产类别；枚举为3D模型、贴图材质、音频、UI组件、特效；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.usage_scenario IS '推荐应用场景，例如主城展示、战斗关卡、剧情演出、活动界面、环境氛围；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.license_status IS '授权状态；枚举为已授权、待确认、仅内部使用；空值不允许。';
COMMENT ON COLUMN analytics.asset_catalog.polygon_count IS '模型面数，单位面；只有3D模型有值，其他类别为空；可平均、最小或最大，不建议求和。';
COMMENT ON VIEW analytics.project_asset_summary IS '游戏项目资产汇总；每行是一个项目和资产类别；project_id 是 RLS 作用域；可与 asset_catalog 按 project_id 连接。';
COMMENT ON COLUMN analytics.project_asset_summary.project_id IS '游戏项目范围 ID；维度字段。';
COMMENT ON COLUMN analytics.project_asset_summary.project_name IS '游戏项目名称；非敏感维度。';
COMMENT ON COLUMN analytics.project_asset_summary.category_name IS '资产类别维度。';
COMMENT ON COLUMN analytics.project_asset_summary.asset_count IS '当前项目和类别的资产数量，单位个；可以求和。';
COMMENT ON COLUMN analytics.project_asset_summary.total_cost_yuan IS '当前项目和类别的资产总费用，单位人民币元；可求和。';
COMMENT ON COLUMN analytics.project_asset_summary.average_cost_yuan IS '当前项目和类别的平均资产费用，单位人民币元；已经是平均值，不应再次求和。';
COMMENT ON COLUMN analytics.project_asset_summary.average_polygon_count IS '当前项目模型资产的平均面数，单位面；非模型类别为空；不可求和。';

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE nl2sql_game_test TO nl2sql_game_reader;
REVOKE USAGE ON SCHEMA business FROM nl2sql_game_reader;
GRANT USAGE ON SCHEMA analytics TO nl2sql_game_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO nl2sql_game_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO nl2sql_game_reader;
