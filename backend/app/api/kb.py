"""
知识库管理 API

【模块职责】
知识库的增删改查（CRUD）接口，路由前缀 /api/kb：
  GET    /api/kb         分页+关键词查询列表
  POST   /api/kb         创建知识库
  GET    /api/kb/{id}    查询单个（附带向量统计）
  PUT    /api/kb/{id}    更新
  DELETE /api/kb/{id}    删除（连带清理向量集合）

【开发思路】
1. API 层只做三件事：参数校验（Query/Depends）→ 调用 ORM/Service → 组装统一响应。
   业务逻辑（向量清理等）放在 service 层，避免 API 层膨胀；
2. 分页统一用 page/page_size + offset/limit 模式，并返回 PageData 结构，
   前端列表组件可以复用同一套分页逻辑。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models import KnowledgeBase, KBStatus
from app.schemas import KBCreate, KBUpdate, KBOut, ResponseModel, PageData
from app.services.vector_store import vector_service
from loguru import logger

# prefix 统一加 /api/kb；tags 用于 Swagger 文档分组
router = APIRouter(prefix="/api/kb", tags=["知识库"])


@router.get("", response_model=ResponseModel)
def list_kbs(
    # Query(...) 声明查询参数并附带校验规则：page>=1、page_size 1~100
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,          # 可选：按名称模糊搜索
    db: Session = Depends(get_db),          # 依赖注入：请求级数据库会话
):
    """分页查询知识库列表，支持名称关键词模糊搜索。"""
    # 先构造基础查询，关键词存在时追加 LIKE 过滤（%xxx% 前后通配）
    query = db.query(KnowledgeBase)
    if keyword:
        query = query.filter(KnowledgeBase.name.like(f"%{keyword}%"))
    # count() 用于前端分页组件的 total；order_by 新库在前
    total = query.count()
    items = query.order_by(KnowledgeBase.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    # 统一信封：data 里放分页结构；model_validate 把 ORM 对象转成 Schema
    return ResponseModel(data=PageData(
        total=total, items=[KBOut.model_validate(i) for i in items],
        page=page, page_size=page_size
    ))


@router.post("", response_model=ResponseModel)
def create_kb(body: KBCreate, db: Session = Depends(get_db)):
    """创建知识库：请求体已由 Pydantic 校验，直接映射为 ORM 对象入库。"""
    kb = KnowledgeBase(**body.model_dump())   # Schema → dict → ORM 字段
    db.add(kb)                                 # 加入会话（待提交）
    db.commit()                                # 提交事务，写库
    db.refresh(kb)                             # 刷新出数据库生成的 id/时间戳
    return ResponseModel(data=KBOut.model_validate(kb))


@router.get("/{kb_id}", response_model=ResponseModel)
def get_kb(kb_id: int, db: Session = Depends(get_db)):
    """查询单个知识库，额外附上向量数量统计（来自 ChromaDB）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    # 业务元数据在 MySQL，向量统计在 ChromaDB——两种存储在此合并返回
    stats = vector_service.get_kb_stats(kb_id)
    data = KBOut.model_validate(kb).model_dump()
    data.update(stats)   # 把 {"vector_count": N} 合并进返回体
    return ResponseModel(data=data)


@router.put("/{kb_id}", response_model=ResponseModel)
def update_kb(kb_id: int, body: KBUpdate, db: Session = Depends(get_db)):
    """部分更新知识库：只更新请求体中非空的字段。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    # exclude_none=True：排除值为 None 的字段，实现"只改传了的字段"
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(kb, k, v)
    db.commit()
    db.refresh(kb)
    return ResponseModel(data=KBOut.model_validate(kb))


@router.delete("/{kb_id}", response_model=ResponseModel)
def delete_kb(kb_id: int, db: Session = Depends(get_db)):
    """删除知识库：先清理 ChromaDB 向量集合，再删 MySQL 记录（级联删文档/会话）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    # 先删向量：MySQL 记录删了但向量还在会变成"幽灵数据"
    vector_service.delete_kb(kb_id)
    db.delete(kb)
    db.commit()
    return ResponseModel(message="删除成功")
