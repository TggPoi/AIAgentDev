# 01. 数据库与 PostgreSQL 基础

## 1. 先建立整体认识

数据库用于持久化保存数据。应用程序退出、Node.js 进程重启或电脑重启后，数据仍然可以保留。

PostgreSQL 是一个关系型数据库管理系统。关系型数据库的核心组织方式是表。

可以把当前工程理解为：

```text
PostgreSQL 服务
  └── 数据库 hello_pg
        └── schema public
              ├── 表 users
              ├── 表 conversations
              └── 表 messages
```

这些概念的含义：

| 概念 | 含义 | 当前工程示例 |
| --- | --- | --- |
| PostgreSQL 服务 | 正在运行的数据库进程，可以管理多个数据库 | Docker 容器 `pg_vector_db` |
| 数据库 | 一组相互关联的数据对象 | `hello_pg` |
| schema | 数据库内的命名空间 | 默认使用 `public` |
| 表 table | 按固定结构保存同类数据 | `users` |
| 列 column | 一类属性 | `users.name` |
| 行 row | 一条具体记录 | 某一个用户 |
| SQL | 操作数据库的语言 | `SELECT * FROM users;` |

## 2. Docker 在工程中做了什么

[`docker-compose.yml`](../docker-compose.yml) 描述了两个容器：

```text
postgres 容器
  └── 运行 PostgreSQL + pgvector

pgadmin 容器
  └── 提供浏览器中的数据库管理界面
```

YAML 使用缩进表达层级。缩进更深的配置属于上一级配置。例如，[`POSTGRES_USER`](../docker-compose.yml#L8) 属于 [`postgres.environment`](../docker-compose.yml#L7)，不会影响 `pgadmin` 容器。

下面的表格逐项解释当前文件。点击“源码”链接可以直接打开对应配置。

### 2.1 顶层 services

| 配置项 | 当前值 | 作用 | 对应代码 |
| --- | --- | --- | --- |
| `services` | - | 定义由 Docker Compose 管理的服务。一个服务通常对应一个容器。当前文件包含 `postgres` 和 `pgadmin`。 | [源码 L1](../docker-compose.yml#L1) |

### 2.2 postgres 服务

| 配置项 | 当前值 | 作用 | 对应代码 |
| --- | --- | --- | --- |
| `services.postgres` | - | 定义 PostgreSQL 服务。Compose 启动时会根据这个配置创建数据库容器。服务名是 `postgres`。同一 Compose 网络中的其他容器可以使用 `postgres:5432` 访问数据库。 | [源码 L3](../docker-compose.yml#L3) |
| `services.postgres.image` | `pgvector/pgvector:pg16` | 指定容器镜像。该镜像基于 PostgreSQL 16，并包含 pgvector 扩展文件。SQL 中仍然需要执行 `CREATE EXTENSION vector` 才会在数据库中启用扩展。 | [源码 L4](../docker-compose.yml#L4) |
| `services.postgres.container_name` | `pg_vector_db` | 显式指定容器名称。因此可以执行 `docker exec -it pg_vector_db ...`。如果不配置，Compose 会自动生成名称。 | [源码 L5](../docker-compose.yml#L5) |
| `services.postgres.restart` | `always` | Docker 守护进程运行时，如果容器退出，会尝试重新启动容器。Docker Desktop 重启后也会尝试恢复该容器。 | [源码 L6](../docker-compose.yml#L6) |
| `services.postgres.environment` | - | 向 PostgreSQL 容器传入环境变量。下面三个变量用于首次初始化数据库。 | [源码 L7](../docker-compose.yml#L7) |
| `POSTGRES_USER` | `user` | 首次初始化时创建的数据库用户。Node.js 和 `psql` 可以使用该用户登录。 | [源码 L8](../docker-compose.yml#L8) |
| `POSTGRES_PASSWORD` | `123456` | 为 `POSTGRES_USER` 设置密码。这里只适合本地学习。真实项目不应在仓库中硬编码密码。 | [源码 L9](../docker-compose.yml#L9) |
| `POSTGRES_DB` | `hello_pg` | 首次初始化时创建的数据库。进入 `psql` 时使用 `-d hello_pg`。 | [源码 L10](../docker-compose.yml#L10) |
| `services.postgres.ports` | - | 声明主机与容器之间的端口映射。 | [源码 L11](../docker-compose.yml#L11) |
| `postgres` 端口映射 | `"5432:5432"` | 左侧 `5432` 是 Windows 主机端口，右侧 `5432` 是容器端口。因此 Windows 中的 Node.js 使用 `localhost:5432` 访问数据库。 | [源码 L12](../docker-compose.yml#L12) |
| `services.postgres.volumes` | - | 声明 PostgreSQL 容器使用的挂载目录。左侧是主机路径，右侧是容器路径。 | [源码 L13](../docker-compose.yml#L13) |
| PostgreSQL 数据目录挂载 | `${DOCKER_VOLUME_DIRECTORY:-.}/volumes/postgres:/var/lib/postgresql/data` | 将数据库文件保存到主机目录。默认实际路径是当前工程的 `volumes/postgres`。容器删除并重新创建后，数据仍然保留。 | [源码 L14](../docker-compose.yml#L14) |
| 初始化脚本目录挂载 | `./init-scripts:/docker-entrypoint-initdb.d` | 将工程中的 `init-scripts` 挂载到 PostgreSQL 初始化目录。该目录中的 SQL 只会在数据目录为空、数据库首次初始化时自动执行。 | [源码 L15](../docker-compose.yml#L15) |
| `services.postgres.healthcheck` | - | 定义数据库健康检查。Compose 会定期执行下面的命令，并显示容器是否 `healthy`。 | [源码 L16](../docker-compose.yml#L16) |
| `healthcheck.test` | `pg_isready -U user -d hello_pg` | 使用 PostgreSQL 自带的 `pg_isready` 检查数据库是否已经可以接受连接。`CMD-SHELL` 表示通过容器中的 shell 执行命令字符串。 | [源码 L17](../docker-compose.yml#L17) |
| `healthcheck.interval` | `5s` | 每隔 5 秒检查一次。 | [源码 L18](../docker-compose.yml#L18) |
| `healthcheck.timeout` | `5s` | 单次检查超过 5 秒仍未完成，则本次检查视为失败。 | [源码 L19](../docker-compose.yml#L19) |
| `healthcheck.retries` | `5` | 连续失败 5 次后，将容器标记为 `unhealthy`。 | [源码 L20](../docker-compose.yml#L20) |

### 2.3 pgadmin 服务

| 配置项 | 当前值 | 作用 | 对应代码 |
| --- | --- | --- | --- |
| `services.pgadmin` | - | 定义 pgAdmin 服务。pgAdmin 是 PostgreSQL 的图形化管理工具，不是数据库本身。 | [源码 L23](../docker-compose.yml#L23) |
| `services.pgadmin.container_name` | `pgadmin` | 显式指定容器名称。 | [源码 L24](../docker-compose.yml#L24) |
| `services.pgadmin.image` | `dpage/pgadmin4:latest` | 使用 pgAdmin 4 镜像。`latest` 会随时间变化。为了让环境可重复，正式项目通常固定具体版本标签。 | [源码 L25](../docker-compose.yml#L25) |
| `services.pgadmin.user` | `root` | 让 pgAdmin 在容器中使用 `root` 用户运行。当前 Windows 本地绑定挂载环境需要它创建 `sessions` 等目录。这是本地开发兼容配置，不建议直接用于生产环境。 | [源码 L26](../docker-compose.yml#L26) |
| `services.pgadmin.environment` | - | 向 pgAdmin 容器传入初始化配置。 | [源码 L27](../docker-compose.yml#L27) |
| `PGADMIN_DEFAULT_EMAIL` | `admin@admin.com` | 首次启动 pgAdmin 时创建的登录邮箱。 | [源码 L28](../docker-compose.yml#L28) |
| `PGADMIN_DEFAULT_PASSWORD` | `admin` | pgAdmin 登录密码。这里只适合本地学习。 | [源码 L29](../docker-compose.yml#L29) |
| `services.pgadmin.volumes` | - | 声明 pgAdmin 数据目录挂载。 | [源码 L30](../docker-compose.yml#L30) |
| pgAdmin 数据目录挂载 | `${DOCKER_VOLUME_DIRECTORY:-.}/volumes/pgadmin:/var/lib/pgadmin` | 将 pgAdmin 的配置、会话等数据保存到当前工程的 `volumes/pgadmin`。 | [源码 L31](../docker-compose.yml#L31) |
| `services.pgadmin.healthcheck` | - | 定义 pgAdmin 页面健康检查。 | [源码 L32](../docker-compose.yml#L32) |
| `healthcheck.test` | `curl -f http://localhost:80/login` | 在 pgAdmin 容器内部请求登录页面。`CMD` 表示按参数列表直接执行命令；`curl -f` 会在 HTTP 错误状态时返回失败。 | [源码 L33](../docker-compose.yml#L33) |
| `healthcheck.interval` | `30s` | 每隔 30 秒检查一次。 | [源码 L34](../docker-compose.yml#L34) |
| `healthcheck.timeout` | `20s` | 单次检查最多等待 20 秒。 | [源码 L35](../docker-compose.yml#L35) |
| `healthcheck.retries` | `3` | 连续失败 3 次后，将容器标记为 `unhealthy`。 | [源码 L36](../docker-compose.yml#L36) |
| `services.pgadmin.ports` | - | 声明 pgAdmin 页面端口映射。 | [源码 L37](../docker-compose.yml#L37) |
| `pgadmin` 端口映射 | `"8088:80"` | Windows 主机的 `8088` 映射到容器的 `80`。因此浏览器访问 `http://localhost:8088/`。 | [源码 L38](../docker-compose.yml#L38) |
| `services.pgadmin.depends_on` | - | 声明当前服务依赖哪些其他服务。 | [源码 L39](../docker-compose.yml#L39) |
| `depends_on` 列表项 | `postgres` | Compose 会先启动 `postgres`，再启动 `pgadmin`。当前简写形式不保证 PostgreSQL 已经通过健康检查，只保证容器启动顺序。 | [源码 L40](../docker-compose.yml#L40) |

### 2.4 网络配置

| 配置项 | 当前值 | 作用 | 对应代码 |
| --- | --- | --- | --- |
| `networks` | - | 定义 Compose 使用的网络。 | [源码 L42](../docker-compose.yml#L42) |
| `networks.default` | - | 覆盖两个服务默认接入的网络。因为服务没有单独声明 `networks`，它们都会接入该默认网络。 | [源码 L43](../docker-compose.yml#L43) |
| `networks.default.name` | `common-network` | 指定 Docker 中真实的网络名称。接入同一个网络的容器可以通过服务名互相访问。 | [源码 L44](../docker-compose.yml#L44) |
| `networks.default.external` | `true` | 表示网络已经在本工程之外创建。Compose 会复用它，不会负责创建或删除它。如果该网络不存在，`docker compose up` 会失败。 | [源码 L45](../docker-compose.yml#L45) |

### 2.5 路径变量与端口写法

`${DOCKER_VOLUME_DIRECTORY:-.}` 表示：

- 如果设置了 `DOCKER_VOLUME_DIRECTORY` 环境变量，就使用它指定的目录。
- 如果没有设置，就使用 `.`，也就是当前工程目录。

因此，在没有设置该环境变量时：

```text
${DOCKER_VOLUME_DIRECTORY:-.}/volumes/postgres
```

实际表示：

```text
D:\AI_Agent_Project\pgsql-test\volumes\postgres
```

端口和挂载目录都使用“左侧主机，右侧容器”的写法：

```text
主机端口:容器端口
主机目录:容器目录
```

例如：

```text
5432:5432
./volumes/postgres:/var/lib/postgresql/data
```

### 2.6 两种访问数据库的主机名

从 Windows 主机上的 Node.js 程序访问 PostgreSQL：

```text
localhost:5432
```

从同一个 Docker 网络中的 `pgadmin` 容器访问 PostgreSQL：

```text
postgres:5432
```

这里的 `postgres` 来自服务名 [`services.postgres`](../docker-compose.yml#L3)，不是容器名 `pg_vector_db`。

## 3. 使用 psql 连接数据库

`psql` 是 PostgreSQL 自带的命令行客户端。它适合学习 SQL，也适合排查问题。

在 PowerShell 中执行：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg
```

参数含义：

| 参数 | 含义 |
| --- | --- |
| `docker exec -it pg_vector_db` | 在运行中的容器内打开交互式命令 |
| `psql` | 启动 PostgreSQL 命令行客户端 |
| `-U user` | 使用数据库用户 `user` |
| `-d hello_pg` | 连接数据库 `hello_pg` |

进入 `psql` 后执行：

```sql
SELECT version();
SELECT current_database();
SELECT current_schema();
```

SQL 语句通常以分号 `;` 结束。

## 4. 常用 psql 元命令

以反斜杠开头的命令是 `psql` 命令，不是 SQL。

```text
\l                  查看数据库列表
\dt                 查看当前 schema 的表
\d users            查看 users 表结构
\d conversations    查看 conversations 表结构
\d messages         查看 messages 表结构
\dx                 查看已安装扩展
\q                  退出 psql
```

当前工程中，执行 `\dt` 应看到：

```text
users
conversations
messages
```

## 5. 理解表、行和列

查询用户表：

```sql
SELECT * FROM users;
```

如果表中已有数据，结果类似：

```text
 id | name |          created_at
----+------+-------------------------------
  1 | 张三 | 2026-06-01 12:00:00+00
```

其中：

- `users` 是表。
- `id`、`name`、`created_at` 是列。
- `1 | 张三 | ...` 是一行数据。

只查询指定列：

```sql
SELECT id, name FROM users;
```

使用条件过滤：

```sql
SELECT id, name
FROM users
WHERE id = 1;
```

## 6. 主键是什么

当前三张表都有 `id`：

```sql
id SERIAL PRIMARY KEY
```

主键用于唯一标识一条记录。

例如，两个用户都可以叫“张三”，但它们的 `id` 不会相同：

```text
id = 1, name = 张三
id = 2, name = 张三
```

`SERIAL` 会让 PostgreSQL 自动生成递增整数。插入用户时，可以不手动填写 `id`。

## 7. schema 是什么

如果 SQL 中只写：

```sql
SELECT * FROM users;
```

通常等价于：

```sql
SELECT * FROM public.users;
```

`public` 是默认 schema。小型学习工程可以先使用默认 schema。

## 本章练习

进入 `psql`，依次完成：

```sql
SELECT current_database();
SELECT current_schema();
SELECT * FROM users;
SELECT id, name FROM users ORDER BY id;
```

再执行：

```text
\dt
\d users
\dx
```

## 完成标准

你应该能够回答：

1. PostgreSQL 服务、数据库、schema 和表分别是什么。
2. 当前工程的数据库名称是什么。
3. 如何进入和退出 `psql`。
4. `users.id` 为什么需要设置为主键。

下一章：[02. SQL CRUD 与约束](./02-sql-crud-and-constraints.md)
