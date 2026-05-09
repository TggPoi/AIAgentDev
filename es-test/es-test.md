# Elasticsearch 基础操作

# 1. 查看所有索引
GET /_cat/indices?v&h=health,status,index,docs.count

# 2. 创建索引
PUT /article
{
  "mappings": {
    "properties": {
      "title": {
        "type": "text"
      },
      "content": {
        "type": "text"
      },
      "author": {
        "type": "keyword"
      },
      "createTime": {
        "type": "date"
      },
      "viewCount": {
        "type": "integer"
      }
    }
  }
}

# 3. 查看索引结构
GET /article/_mapping

# 4. 查看索引配置
GET /article/_settings

# 5. 删除索引
DELETE /article

# ==========================
# 文档 增删改查
# ==========================

# 1. 新增文档（自动生成 ID）
POST /article/_doc
{
  "title": "Elasticsearch 全文检索入门",
  "content": "ES 基于倒排索引与 BM25 实现全文搜索，适用于文本检索场景",
  "author": "后端开发",
  "createTime": "2026-04-26",
  "viewCount": 128
}

# 2. 新增文档（指定自定义 ID）
PUT /article/_doc/1001
{
  "title": "RAG 混合检索实战",
  "content": "ES 负责关键词检索，Milvus 负责向量语义检索，结合使用效果更佳",
  "author": "AI开发",
  "createTime": "2026-04-26",
  "viewCount": 256
}

# 3. 根据 ID 查询单条
GET /article/_doc/1001

# 4. 查询全部文档
GET /article/_search
{
  "query": {
    "match_all": {}
  }
}

# 5. 全文分词检索（text 字段）
GET /article/_search
{
  "query": {
    "match": {
      "content": "RAG 向量 检索"
    }
  }
}

# 6. 精确匹配查询（keyword 字段）
GET /article/_search
{
  "query": {
    "term": {
      "author": "AI开发"
    }
  }
}

# 7. 只返回指定字段
GET /article/_search
{
  "_source": ["title", "author"],
  "query": {
    "match_all": {}
  }
}

# 8. 分页 + 排序
GET /article/_search
{
  "from": 0,
  "size": 10,
  "sort": [
    {"viewCount": "desc"}
  ],
  "query": {
    "match_all": {}
  }
}

# 9. 局部更新文档（推荐）
POST /article/_update/1001
{
  "doc": {
    "viewCount": 999,
    "title": "RAG 混合检索高级实战"
  }
}

# 10. 全量覆盖更新
PUT /article/_doc/1001
{
  "title": "全量覆盖测试",
  "content": "原始内容被替换",
  "author": "测试用户",
  "createTime": "2026-04-26",
  "viewCount": 66
}

# 11. 根据 ID 删除文档
DELETE /article/_doc/1001

# 12. 条件批量删除
POST /article/_delete_by_query
{
  "query": {
    "match": {
      "author": "后端开发"
    }
  }
}

# 13. 统计文档总数
GET /article/_count

# 14. 清空索引数据（保留表结构）
POST /article/_delete_by_query
{
  "query": {
    "match_all": {}
  }
}
