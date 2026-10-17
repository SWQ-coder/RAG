"""
配置管理模块

【模块职责】
集中管理整个后端的所有可配置项：数据库连接、Ollama 模型地址、向量库、
上传限制、RAG 分块/检索参数、缓存参数、日志参数等。

【开发思路】
为什么用 pydantic-settings 而不是写死常量或直接读 os.environ？
  1. 所有配置集中在一个类里，代码中通过 `settings.XXX` 引用，改配置只需改一处；
  2. 自动支持 .env 文件（Config.env_file = ".env"），部署时改环境变量即可，
     不用动代码；默认值写在类属性里，不配 .env 也能跑起来；
  3. 启动时（模块导入时）自动调用 ensure_dirs() 创建上传/向量/日志目录，
     避免后续写文件时因目录不存在而报错——这是"导入即准备"的典型用法。
"""
from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    # Application（应用基本信息）
    APP_NAME: str = "Enterprise RAG System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True          # 开发模式开关（控制热重载、SQL echo）
    SECRET_KEY: str = "your-secret-key"

    # Server（服务监听配置）
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database（MySQL 连接；SQLAlchemy 连接串格式：驱动://用户:密码@主机:端口/库名）
    DATABASE_URL: str = "mysql+pymysql://root:password@localhost:3306/rag_db"
    DATABASE_POOL_SIZE: int = 10       # 连接池常驻连接数
    DATABASE_MAX_OVERFLOW: int = 20    # 连接池最多超额数（峰值时再开 20 个）

    # Ollama（本地大模型运行时；Embedding 与 LLM 都走它的 HTTP 接口）
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_LLM_MODEL: str = "qwen2.5:7b"          # 对话生成模型
    OLLAMA_EMBEDDING_MODEL: str = "qwen3-embedding-0.6b"  # 文本向量化模型

    # Vector Store（ChromaDB 持久化向量库）
    CHROMA_PERSIST_DIR: str = "./chroma_db"        # 向量数据落盘目录
    CHROMA_COLLECTION_NAME: str = "rag_documents"  # 集合名（每个知识库实际是 kb_{id}）

    # File Upload（上传限制）
    UPLOAD_DIR: str = "./uploads"      # 上传文件保存目录
    MAX_FILE_SIZE: int = 104857600     # 100MB，单文件大小上限
    ALLOWED_EXTENSIONS: str = "pdf,doc,docx,txt,xls,xlsx,jpg,jpeg,png,gif,bmp"

    # RAG Config（检索增强生成的核心调参区）
    CHUNK_SIZE: int = 512              # 文档分块大小（字符数）：越小检索越精准但上下文越碎
    CHUNK_OVERLAP: int = 64            # 相邻块重叠字符数：保持跨块语义连贯
    TOP_K: int = 8                      # 向量召回数量（先多召回）
    RERANK_TOP_K: int = 5               # 重排后保留数量（进 Prompt 的块数）
    RETRIEVAL_SCORE_THRESHOLD: float = 0.1  # 相似度最低阈值（过滤噪声块）
    MAX_CONTEXT_LENGTH: int = 6000      # 拼接给 LLM 的上下文最大字符数（防超长）

    # Cache（缓存参数）
    QUERY_CACHE_TTL: int = 300          # 查询结果缓存有效期（秒）
    QUERY_CACHE_MAX_SIZE: int = 500     # 查询缓存最大条数
    EMBEDDING_CACHE_MAX_SIZE: int = 2000  # Embedding 向量缓存最大条数

    # Async Worker（异步嵌入并发控制）
    EMBEDDING_CONCURRENCY: int = 3      # 同时进行的 embedding 请求数（信号量）
    EMBED_BATCH_SIZE: int = 20          # 每批 embed 的文本数（减少调用次数）

    # Logging（日志开关）
    LOG_DIR: str = "./logs"
    LOG_RETRIEVAL: bool = True          # 开启检索日志
    LOG_PROMPT: bool = True             # 开启 prompt 日志
    LOG_LEVEL: str = "INFO"

    @property
    def allowed_extensions_list(self) -> List[str]:
        """把逗号分隔的扩展名字符串转成小写列表，供 is_supported_file 判断。"""
        return [ext.strip().lower() for ext in self.ALLOWED_EXTENSIONS.split(",")]

    def ensure_dirs(self):
        """确保运行所需目录存在（幂等操作，已存在则不报错）。"""
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
        os.makedirs(self.CHROMA_PERSIST_DIR, exist_ok=True)
        os.makedirs(self.LOG_DIR, exist_ok=True)

    class Config:
        env_file = ".env"        # 启动时从 backend/.env 读取覆盖默认值
        case_sensitive = True    # 环境变量名大小写敏感（与字段名严格一致）


# 模块级单例：整个进程共享同一份配置；
# 立即调用 ensure_dirs() 保证目录在写日志/存文件前就已存在。
settings = Settings()
settings.ensure_dirs()