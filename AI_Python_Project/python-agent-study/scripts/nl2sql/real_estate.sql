CREATE SCHEMA IF NOT EXISTS business;
CREATE SCHEMA IF NOT EXISTS analytics;
SELECT set_config('app.scope_ids', '*', false);

CREATE TABLE IF NOT EXISTS business.projects (
    project_id text PRIMARY KEY,
    project_name text NOT NULL UNIQUE,
    address text NOT NULL,
    business_code text NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS business.buildings (
    building_id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES business.projects(project_id),
    building_name text NOT NULL,
    UNIQUE (project_id, building_name)
);
CREATE TABLE IF NOT EXISTS business.unit_types (
    unit_type_id text PRIMARY KEY,
    unit_type_name text NOT NULL UNIQUE,
    area_sqm numeric(8,2) NOT NULL CHECK (area_sqm > 0),
    room_count integer NOT NULL CHECK (room_count > 0),
    orientation text NOT NULL CHECK (orientation IN ('南', '东南', '西南', '东', '西', '北'))
);
CREATE TABLE IF NOT EXISTS business.units (
    unit_id text PRIMARY KEY,
    project_id text NOT NULL REFERENCES business.projects(project_id),
    building_id text NOT NULL REFERENCES business.buildings(building_id),
    unit_type_id text NOT NULL REFERENCES business.unit_types(unit_type_id),
    unit_no text NOT NULL,
    total_price_yuan numeric(14,2) NOT NULL CHECK (total_price_yuan > 0),
    inventory_status text NOT NULL CHECK (inventory_status IN ('可售', '已认购', '已售')),
    UNIQUE (building_id, unit_no)
);

TRUNCATE business.units, business.buildings, business.unit_types, business.projects CASCADE;
INSERT INTO business.projects VALUES
('re_p1', '云栖雅苑', '杭州市滨江区星河路88号', 'REA-YSY-001'),
('re_p2', '湖畔新城', '苏州市工业园区湖心大道16号', 'REA-HBXC-002'),
('re_p3', '中央公园府', '成都市高新区锦城路399号', 'REA-ZYGY-003');
INSERT INTO business.buildings VALUES
('re_b1', 're_p1', '1号楼'), ('re_b2', 're_p1', '2号楼'),
('re_b3', 're_p2', '1号楼'), ('re_b4', 're_p2', '2号楼'),
('re_b5', 're_p3', '1号楼'), ('re_b6', 're_p3', '2号楼');
INSERT INTO business.unit_types VALUES
('ut_01', '舒适两居', 78.00, 2, '南'),
('ut_02', '经典三居', 96.00, 3, '东南'),
('ut_03', '改善三居', 118.00, 3, '南'),
('ut_04', '宽景四居', 138.00, 4, '西南'),
('ut_05', '紧凑两居', 68.00, 2, '东'),
('ut_06', '花园四居', 156.00, 4, '南');
INSERT INTO business.units (
    unit_id, project_id, building_id, unit_type_id, unit_no,
    total_price_yuan, inventory_status
)
SELECT
    'unit_' || lpad(gs::text, 3, '0'),
    're_p' || (((gs - 1) / 24) + 1),
    're_b' || (((gs - 1) / 12) + 1),
    'ut_' || lpad((((gs - 1) % 6) + 1)::text, 2, '0'),
    (((gs - 1) % 12) / 2 + 1)::text || '0' || (((gs - 1) % 2) + 1)::text,
    1280000 + gs * 37000,
    (ARRAY['可售', '可售', '已认购', '已售'])[((gs - 1) % 4) + 1]
FROM generate_series(1, 72) AS gs;

ALTER TABLE business.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.projects FORCE ROW LEVEL SECURITY;
ALTER TABLE business.buildings ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.buildings FORCE ROW LEVEL SECURITY;
ALTER TABLE business.units ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.units FORCE ROW LEVEL SECURITY;
ALTER TABLE business.unit_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE business.unit_types FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS projects_scope ON business.projects;
CREATE POLICY projects_scope ON business.projects USING (
    '*' = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
    OR project_id = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
);
DROP POLICY IF EXISTS buildings_scope ON business.buildings;
CREATE POLICY buildings_scope ON business.buildings USING (
    '*' = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
    OR project_id = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
);
DROP POLICY IF EXISTS units_scope ON business.units;
CREATE POLICY units_scope ON business.units USING (
    '*' = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
    OR project_id = ANY(string_to_array(COALESCE(current_setting('app.scope_ids', true), ''), ','))
);
DROP POLICY IF EXISTS unit_types_read ON business.unit_types;
CREATE POLICY unit_types_read ON business.unit_types USING (
    COALESCE(current_setting('app.scope_ids', true), '') <> ''
);

CREATE OR REPLACE VIEW analytics.unit_inventory
WITH (security_invoker=true) AS
SELECT
    u.project_id,
    p.project_name,
    p.address,
    p.business_code,
    b.building_name,
    u.unit_no,
    t.unit_type_name,
    t.area_sqm,
    t.room_count,
    t.orientation,
    u.total_price_yuan,
    u.inventory_status
FROM business.units u
JOIN business.projects p ON p.project_id = u.project_id
JOIN business.buildings b ON b.building_id = u.building_id
JOIN business.unit_types t ON t.unit_type_id = u.unit_type_id;

CREATE OR REPLACE VIEW analytics.project_inventory_summary
WITH (security_invoker=true) AS
SELECT
    u.project_id,
    p.project_name,
    u.inventory_status,
    count(*) AS unit_count,
    round(avg(t.area_sqm), 2) AS average_area_sqm,
    round(avg(u.total_price_yuan), 2) AS average_total_price_yuan,
    min(u.total_price_yuan) AS minimum_total_price_yuan,
    max(u.total_price_yuan) AS maximum_total_price_yuan
FROM business.units u
JOIN business.projects p ON p.project_id = u.project_id
JOIN business.unit_types t ON t.unit_type_id = u.unit_type_id
GROUP BY u.project_id, p.project_name, u.inventory_status;

COMMENT ON VIEW analytics.unit_inventory IS '房地产房源库存明细；每行一套房源；project_id 是 RLS 作用域；可按 project_id 与 project_inventory_summary 连接。';
COMMENT ON COLUMN analytics.unit_inventory.project_id IS '楼盘范围 ID；敏感内部业务编号，必须本地标记化；仅作维度，不聚合。';
COMMENT ON COLUMN analytics.unit_inventory.project_name IS '楼盘名称；敏感实体，必须本地标记化；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.address IS '楼盘地址；敏感实体，必须本地标记化；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.business_code IS '楼盘内部业务编码；敏感实体，必须本地标记化；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.building_name IS '楼栋名称；敏感实体，必须本地标记化；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.unit_no IS '房号；敏感实体，必须本地标记化；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.unit_type_name IS '户型名称；维度字段；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.area_sqm IS '建筑面积，单位平方米；可平均、最小、最大，不建议求和；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.room_count IS '卧室数量，单位间；可计数或平均；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.orientation IS '主要朝向；枚举为南、东南、西南、东、西、北；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.total_price_yuan IS '房源总价，单位人民币元；敏感数值；可平均、最小、最大或求和；空值不允许。';
COMMENT ON COLUMN analytics.unit_inventory.inventory_status IS '库存状态；枚举为可售、已认购、已售；空值不允许。';
COMMENT ON VIEW analytics.project_inventory_summary IS '楼盘库存汇总；每行是一个楼盘和库存状态；project_id 是 RLS 作用域；可与 unit_inventory 按 project_id 连接。';
COMMENT ON COLUMN analytics.project_inventory_summary.project_id IS '楼盘范围 ID；敏感内部业务编号，必须本地标记化。';
COMMENT ON COLUMN analytics.project_inventory_summary.project_name IS '楼盘名称；敏感实体，必须本地标记化。';
COMMENT ON COLUMN analytics.project_inventory_summary.inventory_status IS '库存状态维度；枚举为可售、已认购、已售。';
COMMENT ON COLUMN analytics.project_inventory_summary.unit_count IS '当前楼盘和状态的房源数量，单位套；可以求和。';
COMMENT ON COLUMN analytics.project_inventory_summary.average_area_sqm IS '平均建筑面积，单位平方米；已经是平均值，不应再次求和。';
COMMENT ON COLUMN analytics.project_inventory_summary.average_total_price_yuan IS '平均房源总价，单位人民币元；敏感数值；已经是平均值，不应再次求和。';
COMMENT ON COLUMN analytics.project_inventory_summary.minimum_total_price_yuan IS '最低房源总价，单位人民币元；敏感数值；不可求和。';
COMMENT ON COLUMN analytics.project_inventory_summary.maximum_total_price_yuan IS '最高房源总价，单位人民币元；敏感数值；不可求和。';

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE nl2sql_real_estate_test TO nl2sql_real_estate_reader;
REVOKE USAGE ON SCHEMA business FROM nl2sql_real_estate_reader;
GRANT USAGE ON SCHEMA analytics TO nl2sql_real_estate_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO nl2sql_real_estate_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO nl2sql_real_estate_reader;
