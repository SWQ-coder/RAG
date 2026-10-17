"""
文档解析服务 - 支持 PDF/Word/Excel/TXT/图片(OCR) 等格式

【模块职责】
把各种格式的文件（PDF/Word/Excel/纯文本/图片）统一"抽"成纯文本，
输出为 LangChain 的 Document 对象列表 + 元信息，供后续分块向量化使用。
这是 RAG 流水线的第一步：文件 → 文本。

【开发思路】
1. 为什么要统一成 Document 列表？
   LangChain 的 Document 是 ({page_content, metadata}) 结构，
   后续 RecursiveCharacterTextSplitter、ChromaDB 入库都直接消费这个结构，
   解析器做格式适配，下游就不需要再关心文件格式差异。
2. 为什么 PaddleOCR 用懒加载（lazy load）？
   PaddleOCR 初始化要加载模型，非常重且慢；只有遇到图片/扫描 PDF 才需要，
   所以放到第一次使用时才 import + 实例化，避免拖慢整个系统启动。
3. 解析失败策略：能解析出文本就返回；完全解析不出就返回空内容占位
   Document（如"[OCR不可用]"），保证流程不中断、状态机有明确结果。
"""
import os
import io
import chardet
from pathlib import Path
from typing import List, Optional, Tuple
from loguru import logger

# LangChain document loaders（其实这里只用到 Document 数据结构）
from langchain_core.documents import Document


class DocumentParser:
    """通用文档解析器：按扩展名分派到具体解析函数。"""

    # 扩展名 → 文件大类 的映射表（get_file_type 据此分类）
    SUPPORTED_TYPES = {
        "pdf": ["pdf"],
        "word": ["doc", "docx"],
        "excel": ["xls", "xlsx"],
        "text": ["txt", "md", "csv", "json", "xml", "html", "htm"],
        "image": ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"],
    }

    def __init__(self):
        self._ocr = None  # lazy load：PaddleOCR 实例，首次需要时才创建

    def _get_ocr(self):
        """懒加载 PaddleOCR：import 失败（未安装）时降级为不可用，不抛异常。"""
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                self._ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
                logger.info("PaddleOCR initialized")
            except ImportError:
                logger.warning("PaddleOCR not available, image parsing disabled")
        return self._ocr

    def get_file_type(self, filename: str) -> str:
        """按扩展名返回文件大类：pdf/word/excel/text/image，未知返回 unknown。"""
        ext = Path(filename).suffix.lower().lstrip(".")
        for ftype, exts in self.SUPPORTED_TYPES.items():
            if ext in exts:
                return ftype
        return "unknown"

    def parse(self, file_path: str, filename: str = None) -> Tuple[List[Document], dict]:
        """
        解析入口：按文件类型分派到具体解析器，统一返回 (documents, metadata)。
        - documents: LangChain Document 列表（每个元素 = 一页/一个Sheet/整个文件的内容）
        - metadata:  解析统计（总字符数、页数等），供上游写入 doc.meta_info
        """
        filename = filename or os.path.basename(file_path)
        ext = Path(filename).suffix.lower().lstrip(".")
        file_type = self.get_file_type(filename)

        logger.info(f"Parsing file: {filename} (type={file_type})")

        try:
            # 分派：每种格式一个私有方法，主流程保持"表驱动"的简洁
            if file_type == "pdf":
                docs = self._parse_pdf(file_path)
            elif file_type == "word":
                docs = self._parse_word(file_path)
            elif file_type == "excel":
                docs = self._parse_excel(file_path)
            elif file_type == "text":
                docs = self._parse_text(file_path)
            elif file_type == "image":
                docs = self._parse_image(file_path)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            # 汇总统计：总字符数会存进文档记录，用于"文档处理了多少内容"的体检
            total_chars = sum(len(d.page_content) for d in docs)
            meta = {
                "filename": filename,
                "file_type": file_type,
                "ext": ext,
                "page_count": len(docs),   # 对 PDF 是页数、对 Excel 是 Sheet 数
                "total_chars": total_chars,
            }
            logger.info(f"Parsed {len(docs)} pages, {total_chars} chars from {filename}")
            return docs, meta

        except Exception as e:
            # 解析失败向上抛，由 DocumentService 捕获并置 FAILED 状态
            logger.error(f"Error parsing {filename}: {e}")
            raise

    def _parse_pdf(self, file_path: str) -> List[Document]:
        """解析 PDF 文件，文本页直接提取，图片页用 OCR"""
        from pypdf import PdfReader
        docs = []
        reader = PdfReader(file_path)

        # 逐页处理：每页一个 Document，metadata 记录页码（回答溯源时用"第N页"）
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()

            # 如果文本为空，尝试 OCR：扫描件/图片型 PDF 没有文本层，
            # 需要渲染成图片再做文字识别（fitz = PyMuPDF，dpi=200 保证清晰度）
            if not text:
                try:
                    import fitz  # PyMuPDF fallback
                    pdf_doc = fitz.open(file_path)
                    pdf_page = pdf_doc[i]
                    pix = pdf_page.get_pixmap(dpi=200)
                    img_bytes = pix.tobytes("png")
                    text = self._ocr_bytes(img_bytes)
                    pdf_doc.close()
                except Exception:
                    pass

            if text:
                # 每页生成一个 Document：page_content 是文本，metadata 带页码
                docs.append(Document(
                    page_content=text,
                    metadata={"source": file_path, "page": i + 1}
                ))

        # 兜底：整份 PDF 一页都没解析出内容，返回一个空占位 Document，
        # 避免返回空列表导致上游流程分支异常
        return docs if docs else [Document(page_content="", metadata={"source": file_path})]

    def _parse_word(self, file_path: str) -> List[Document]:
        """解析 Word 文档 (.doc/.docx)"""
        ext = Path(file_path).suffix.lower()
        if ext == ".docx":
            # .docx：段落文本 + 表格内容都要提取（表格常用 `|` 连接各单元格，保留结构）
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            # 合并表格内容：每个单元格用 | 分隔，避免表格内容丢失
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        paragraphs.append(row_text)
            content = "\n".join(paragraphs)
        else:
            # .doc（旧格式）无法用 python-docx 读，退到 docx2txt；
            # 若它也失败，给出明确占位文案而不是静默返回空（方便排查）
            try:
                import docx2txt
                content = docx2txt.process(file_path)
            except Exception:
                content = f"[无法解析 .doc 文件: {file_path}]"

        return [Document(page_content=content, metadata={"source": file_path})]

    def _parse_excel(self, file_path: str) -> List[Document]:
        """解析 Excel 文件 (.xls/.xlsx)：每个 Sheet 一个 Document。"""
        import openpyxl
        docs = []
        ext = Path(file_path).suffix.lower()

        if ext == ".xlsx":
            # read_only=True 流式读，省内存；data_only=True 取计算后的值而非公式
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    # 单元格统一转字符串；全空行跳过，减少无效内容
                    row_data = [str(cell) if cell is not None else "" for cell in row]
                    if any(cell.strip() for cell in row_data):
                        rows.append(" | ".join(row_data))
                content = f"[Sheet: {sheet_name}]\n" + "\n".join(rows)
                docs.append(Document(
                    page_content=content,
                    metadata={"source": file_path, "sheet": sheet_name}
                ))
            wb.close()
        else:
            # .xls（老格式）：用 xlrd 读取，按行列遍历同样拼成文本
            import xlrd
            wb = xlrd.open_workbook(file_path)
            for sheet in wb.sheets():
                rows = []
                for rx in range(sheet.nrows):
                    row_data = [str(sheet.cell_value(rx, cx)) for cx in range(sheet.ncols)]
                    rows.append(" | ".join(row_data))
                content = f"[Sheet: {sheet.name}]\n" + "\n".join(rows)
                docs.append(Document(
                    page_content=content,
                    metadata={"source": file_path, "sheet": sheet.name}
                ))

        return docs

    def _parse_text(self, file_path: str) -> List[Document]:
        """
        解析纯文本文件，自动检测编码。
        为什么手动检测编码？txt/md 可能以 GBK/UTF-8/UTF-16 存储，
        直接用 utf-8 解码会乱码或抛异常；chardet 探测后按检测结果解码，
        解码失败再退回 utf-8+replace（不中断流程）。
        """
        with open(file_path, "rb") as f:
            raw = f.read()

        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"

        try:
            content = raw.decode(encoding, errors="replace")
        except Exception:
            content = raw.decode("utf-8", errors="replace")

        return [Document(page_content=content, metadata={"source": file_path})]

    def _parse_image(self, file_path: str) -> List[Document]:
        """使用 PaddleOCR 解析图片：整张图识别成文本。"""
        ocr = self._get_ocr()
        if ocr is None:
            # OCR 不可用（未安装 paddleocr）时降级占位，让状态机走到完成而不是失败
            return [Document(page_content="[OCR不可用，无法解析图片]", metadata={"source": file_path})]

        try:
            # ocr.ocr 返回结构：[[ [框, (文本, 置信度)], ... ], ...]
            result = ocr.ocr(file_path, cls=True)
            text_lines = []
            if result:
                for line in result:
                    if line:
                        for item in line:
                            if item and len(item) >= 2:
                                text_lines.append(item[1][0])  # 取识别出的文本
            content = "\n".join(text_lines) if text_lines else "[图片中未识别到文字]"
        except Exception as e:
            logger.error(f"OCR error: {e}")
            content = f"[OCR解析失败: {str(e)}]"

        return [Document(page_content=content, metadata={"source": file_path, "ocr": True})]

    def _ocr_bytes(self, img_bytes: bytes) -> str:
        """
        对图片字节数据（如 PDF 渲染出的页面图）进行 OCR。
        与 _parse_image 的区别：输入是内存字节而非磁盘路径，
        用于 PDF 图片页场景——先把 PDF 页面渲染成 PNG 再识别。
        """
        ocr = self._get_ocr()
        if ocr is None:
            return ""
        try:
            # 字节 → PIL Image → numpy 数组（PaddleOCR 接受 ndarray 输入）
            import numpy as np
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            img_array = np.array(img)
            result = ocr.ocr(img_array, cls=True)
            lines = []
            if result:
                for line in result:
                    if line:
                        for item in line:
                            if item and len(item) >= 2:
                                lines.append(item[1][0])
            return "\n".join(lines)
        except Exception as e:
            # OCR 失败返回空串（调用方 PDF 逻辑会跳过该页），不中断整体解析
            logger.error(f"OCR bytes error: {e}")
            return ""


# 全局解析器单例：整个进程复用同一个实例（PaddleOCR 模型只加载一次）
parser = DocumentParser()
