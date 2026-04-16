from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import (
    DirectoryLoader,
    PyPDFLoader,
    TextLoader,
    UnstructuredWordDocumentLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.app.config import settings
from src.app.services.retriever import get_embeddings


def _load_documents(docs_dir: Path):
    loaded_docs = []

    pdf_loader = DirectoryLoader(
        str(docs_dir),
        glob="**/*.pdf",
        loader_cls=PyPDFLoader,
        silent_errors=True,
        show_progress=True,
        use_multithreading=True,
    )
    loaded_docs.extend(pdf_loader.load())

    md_loader = DirectoryLoader(
        str(docs_dir),
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        silent_errors=True,
        show_progress=True,
        use_multithreading=True,
    )
    loaded_docs.extend(md_loader.load())

    docx_loader = DirectoryLoader(
        str(docs_dir),
        glob="**/*.docx",
        loader_cls=UnstructuredWordDocumentLoader,
        silent_errors=True,
        show_progress=True,
        use_multithreading=True,
    )
    loaded_docs.extend(docx_loader.load())

    return loaded_docs


def main() -> None:
    docs_dir = Path("docs")
    if not docs_dir.exists():
        raise FileNotFoundError("docs/ 目录不存在, 请先创建并放入 pdf/md/docx 文档")

    docs = _load_documents(docs_dir)
    if not docs:
        raise RuntimeError("未加载到文档, 请检查 docs/ 下是否存在 pdf/md/docx 文件")

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    for doc in chunks:
        source = doc.metadata.get("source", "")
        doc.metadata["source"] = Path(source).name if source else "unknown"

    vectorstore = Chroma(
        collection_name=settings.collection_name,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )
    vectorstore.add_documents(chunks)

    print(f"文档加载: {len(docs)}")
    print(f"切片入库: {len(chunks)}")
    print(f"Chroma目录: {settings.chroma_persist_dir}")


if __name__ == "__main__":
    main()
