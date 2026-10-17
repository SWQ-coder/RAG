"""
通用响应 Schema

【模块职责】
定义所有 API 的"统一返回信封"：
  - ResponseModel：固定结构 {code, message, data}，前端只需解析一种格式；
  - PageData：分页数据载体（总数 + 列表 + 页码 + 每页条数）。

【开发思路】
为什么强制统一响应格式？
  1. 前端 api/index.js 里拦截器直接把 res.data 作为返回值，后端格式统一
     就能少写很多分支判断；
  2. 全局异常处理器也返回同样结构，前端 catch 到的错误信息路径一致。
"""
from pydantic import BaseModel
from typing import Optional, Any, List


class ResponseModel(BaseModel):
    """统一 API 响应：code=状态码、message=提示信息、data=业务数据。"""
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None   # Any：不同接口塞不同类型的数据


class PageData(BaseModel):
    """分页返回结构：total 总条数 + items 当前页数据。"""
    total: int
    items: List[Any]
    page: int
    page_size: int
