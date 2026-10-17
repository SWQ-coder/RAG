"""
文档管理 API - 上传、导入、删除、查询

【模块职责】
文档的完整生命周期管理，路由前缀 /api/doc：
  - 上传文件（UploadFile 多文件）、本地路径导入（扫描服务器目录）
  - 分页查询、删除、失败重试（reprocess）
所有耗时的解析+向量化处理都交给 FastAPI BackgroundTasks 异步执行，
接口立即返回，前端轮询状态。

【开发思路】
1. 为什么用 BackgroundTasks 而不是线程/进程池？
   FastAPI 内置的后台任务在响应返回后执行，够用且简单；真正的耗时点
   （文档解析、embedding）本身用 run_in_executor 做了异步化，不会阻塞
   事件循环。
2. 为什么上传要改名（uuid 前缀）？
   不同用户可能上传同名文件，直接用原名会互相覆盖；加 8 位随机前缀
   保证磁盘文件名唯一，同时把原始文件名单独存到 filename 字段用于展示。
3. 为什么先存记录再提交、最后统一 add_task？
   先把所有文档记录写入 MySQL（拿到自增 id），再逐个派发后台任务，
   任务里通过 doc_id 查记录——避免任务执行时记录还没落库。
"""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.config import settings
from app.models import Document, KnowledgeBase, DocStatus
from app.schemas import DocOut, LocalPathImport, ResponseModel, PageData
from app.services.document import doc_service
from loguru import logger

router = APIRouter(prefix="/api/doc", tags=["文档"])


@router.get("", response_model=ResponseModel)
def list_docs(
    # kb_id 必填（Query(...) 省略号表示没有默认值），限定只看某知识库的文档
    kb_id: int = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,   # 按状态过滤（pending/processing/completed/failed）
    keyword: Optional[str] = None,  # 按文件名模糊搜索
    db: Session = Depends(get_db),
):
    """分页查询某知识库的文档列表，支持状态和关键词过滤。"""
    # 基础查询先按 kb_id 过滤，再叠加可选条件
    query = db.query(Document).filter(Document.kb_id == kb_id)
    if status:
        query = query.filter(Document.status == status)
    if keyword:
        query = query.filter(Document.filename.like(f"%{keyword}%"))
    total = query.count()
    items = query.order_by(Document.created_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ResponseModel(data=PageData(
        total=total, items=[DocOut.model_validate(i) for i in items],
        page=page, page_size=page_size
    ))


@router.post("/upload", response_model=ResponseModel)
async def upload_files(
    background_tasks: BackgroundTasks,
    kb_id: int = Form(...),            # multipart 表单字段
    files: List[UploadFile] = File(...),  # 支持一次传多个文件
    db: Session = Depends(get_db),
):
    """上传文件到指定知识库（保存磁盘 + 建记录，解析向量化交给后台）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    doc_ids = []
    for f in files:
        # 扩展名白名单校验，非法类型直接 400 拒绝
        if not doc_service.is_supported_file(f.filename):
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {f.filename}")

        # 生成唯一文件名防止冲突：8位随机hex + 原文件名，
        # 避免同知识库内同名文件互相覆盖（原始名存 filename 字段展示）
        ext = Path(f.filename).suffix
        unique_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
        dest_path = doc_service.get_upload_path(kb_id, unique_name)

        # 读取文件内容并检查大小上限（100MB），超限拒绝
        content = await f.read()
        if len(content) > settings.MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件过大: {f.filename}")

        # 写入磁盘（uploads/kb_{id}/ 目录下）
        with open(dest_path, "wb") as out:
            out.write(content)

        # 创建文档记录：初始状态 PENDING（待处理），file_type 由扩展名判定
        # 注意这里先 db.flush() 拿到自增 id，后面后台任务按 id 处理
        # （下面一行是开发期残留的无效代码：DocumentService 没有 parser 属性，
        #   hasattr 恒为 False 只产出未使用的 "unknown"，真正的类型判定在下一行）
        file_type = doc_service.parser.get_file_type(f.filename) if hasattr(doc_service, 'parser') else "unknown"
        from app.services.parser import parser as p
        doc = Document(
            kb_id=kb_id,
            filename=f.filename,
            file_path=dest_path,
            file_type=p.get_file_type(f.filename),
            file_size=len(content),
            source_type="upload",
            status=DocStatus.PENDING,
        )
        db.add(doc)
        db.flush()
        doc_ids.append(doc.id)

    # 所有记录一次性提交
    db.commit()

    # 后台异步处理：注意把 db 也传进去——BackgroundTasks 里会用新的
    # 上下文继续操作，这是 FastAPI 后台任务的常见用法
    for doc_id in doc_ids:
        background_tasks.add_task(doc_service.process_document, db, doc_id)

    return ResponseModel(
        message=f"成功上传 {len(doc_ids)} 个文件，正在后台处理中",
        data={"doc_ids": doc_ids}
    )


@router.post("/import-path", response_model=ResponseModel)
async def import_from_local_path(
    background_tasks: BackgroundTasks,
    body: LocalPathImport,
    db: Session = Depends(get_db),
):
    """从服务器本地路径导入文件（整目录扫描或单文件）。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == body.kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    try:
        # 路径校验放在后台任务内部（import_from_path 里），
        # 这里 add_task 本身不执行，所以 try 捕获的是任务派发期的同步错误
        background_tasks.add_task(
            doc_service.import_from_path,
            db, body.kb_id, body.path, body.recursive
        )
        return ResponseModel(message=f"正在导入路径: {body.path}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{doc_id}", response_model=ResponseModel)
def get_doc(doc_id: int, db: Session = Depends(get_db)):
    """查询单个文档详情。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return ResponseModel(data=DocOut.model_validate(doc))


@router.delete("/{doc_id}", response_model=ResponseModel)
def delete_doc(doc_id: int, db: Session = Depends(get_db)):
    """删除文档：清理向量 + 删除磁盘文件 + 删除数据库记录。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc_service.delete_document(db, doc_id)
    return ResponseModel(message="删除成功")


@router.post("/{doc_id}/reprocess", response_model=ResponseModel)
async def reprocess_doc(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """重新处理失败的文档：状态复位为 PENDING 后重新派发后台任务。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 清掉失败状态与错误信息，让文档走一遍新的处理流程
    doc.status = DocStatus.PENDING
    doc.error_msg = None
    db.commit()
    background_tasks.add_task(doc_service.process_document, db, doc_id)
    return ResponseModel(message="已重新提交处理")
