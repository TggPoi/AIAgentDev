# 1. 检查 ES 状态
GET /

# 2. 查看已安装插件
GET /_cat/plugins?v

# 3. 原生 standard 分词
POST /_analyze
{
  "analyzer": "standard",
  "text": "Elasticsearch RAG 混合检索知识库"
}

# 4. IK 细粒度分词（索引入库用）
POST /_analyze
{
  "analyzer": "ik_max_word",
  "text": "Elasticsearch RAG 混合检索知识库"
}

# 5. IK 智能分词（搜索查询用）
POST /_analyze
{
  "analyzer": "ik_smart",
  "text": "Elasticsearch RAG 混合检索知识库"
}