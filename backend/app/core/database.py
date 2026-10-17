"""
数据库连接模块

【模块职责】
创建全局 SQLAlchemy 引擎（Engine）、会话工厂（SessionLocal）和 ORM 基类（Base），
并提供两个对外函数：
  - get_db：FastAPI 依赖注入用，每个请求一个 Session，用后自动关闭；
  - init_db：应用启动时根据 ORM 模型自动建表。

【开发思路】
1. 为什么用连接池（QueuePool）？
   RAG 系统的 API 处理是"短连接高频"模式（每次上传、每次问答都要读写 MySQL），
   若每个请求都新建 TCP 连接，开销大且 MySQL 有最大连接数限制。
   连接池复用已建立的连接，pool_pre_ping 在取连接时先探活，避免拿到已断开的
   旧连接（MySQL wait_timeout 默认 8 小时会断开空闲连接）。
2. 为什么 get_db 用 yield 生成器？
   这是 FastAPI 依赖注入的标准写法：请求进入时创建 Session，响应结束后
   finally 自动关闭；异常时回滚，保证数据一致性。
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings
from loguru import logger

# ── 创建引擎 ──────────────────────────────────────────────────
# poolclass=QueuePool：显式指定队列式连接池（SQLAlchemy 默认也用它，这里明示意图）；
# pool_size / max_overflow：池内常驻 10 个，峰值额外最多 20 个；
# pool_pre_ping=True：每次取连接前先执行轻量探测，自动丢弃失效连接；
# pool_recycle=3600：连接闲置超过 1 小时强制重建，规避 MySQL 的 8 小时断连问题；
# echo=DEBUG：开发时打印 SQL，便于调试，生产关闭。
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.DEBUG,
)

# ── 会话工厂 ──────────────────────────────────────────────────
# autocommit=False：手动 commit，避免隐式提交导致事务边界模糊；
# autoflush=False：查询前不自动把待提交变更刷入库，由业务代码显式控制。
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# ORM 模型基类：所有模型（KnowledgeBase/Document/...）都继承它，
# init_db 才能统一收集表结构。
Base = declarative_base()


def get_db():
    """
    FastAPI 依赖注入的数据库会话工厂。
    用法：def xxx(body, db: Session = Depends(get_db)):
    每次请求：创建会话 → yield 给业务逻辑 → 请求结束 finally 关闭。
    异常时先 rollback 再抛出，避免脏数据残留在会话里。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """
    初始化数据库表。
    在 main.py 的 lifespan 启动阶段调用一次：
    导入所有模型模块（让它们注册到 Base.metadata），然后 create_all 自动建表。
    create_all 只创建不存在的表，已有表不会被修改——所以后续字段变更
    需要用 Alembic 迁移（项目依赖里已包含 alembic）。
    """
    from app.models import knowledge_base, document, conversation
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized")
