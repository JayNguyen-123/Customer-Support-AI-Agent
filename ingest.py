import os
import time
from pathlib import Path
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

def scan_and_load_source_directory(data_dir: str):
    """Scans raw file folders and reads PDF and Text structures into clean document arrays."""
    documents = []
    path = Path(data_dir)

    if not path.exists():
        print(f"📁 Directory '{data_dir}' not found. Initializing storage directory...")
        path.mkdir(parents=True, exist_ok=True)
        return documents

    for file_path in path.iterdir():
        if file_path.is_file():
            suffix = file_path.suffix.lower()
            try:
                if suffix == ".txt":
                    print(f"📄 Loading Technical Text Manual: {file_path.name}")
                    loader = TextLoader(str(file_path), encoding="utf-8")
                    documents.extend(loader.load())
                elif suffix == ".pdf":
                    print(f"📕 Loading Engineering PDF Manual: {file_path.name}")
                    loader = PyPDFLoader(str(file_path))
                    documents.extend(loader.load())
            except Exception as e:
                print(f"⚠️ Failed to parse asset structure for {file_path.name}: {str(e)}")

    return documents

def build_production_knowledge_base(ttl_days: int = 7):
    """Chunks documents and saves them to Chroma with persistent TTL expiration metadata hooks."""
    data_directory = "./knowledge_source"
    persist_directory = "./chroma_db"

    # 1. Read files out of the workspace source folder
    raw_documents = scan_and_load_source_directory(data_directory)

    if not raw_documents:
        print(f"💡 The directory '{data_directory}' is empty. Drop text or PDF manuals here.")
        return

    # 2. Slice documents into semantic, overlapping chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len
    )
    semantic_chunks = text_splitter.split_documents(raw_documents)

    # 3. Calculate temporal TTL cache ceilings
    current_epoch = int(time.time())
    seconds_in_a_day = 86400
    expiration_epoch = current_epoch + (ttl_days * seconds_in_a_day)

    # 4. Inject absolute tracking metadata keys into every single split chunk
    for chunk in semantic_chunks:
        chunk.metadata["ingested_at"] = current_epoch
        chunk.metadata["expires_at"] = expiration_epoch

    print(f"🧩 Processed {len(semantic_chunks)} chunks. Setting cache expiration epoch to: {expiration_epoch}")

    # 5. Generate high-dimensional vector embeddings and serialize to local disk
    print("🛰️ Generating neural embeddings and writing data to persistent Chroma indices...")
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    # `Chroma.from_documents(...)` *adds* to the persisted collection rather
    # than replacing it, so re-running this script (e.g. after editing a
    # manual in knowledge_source/) previously just piled up duplicate,
    # increasingly-stale embeddings of the old content alongside the new --
    # every retrieval from then on would mix current and outdated chunks.
    # Clearing the collection first makes re-ingestion idempotent: each run
    # reflects exactly what's currently in knowledge_source/.
    existing_store = Chroma(persist_directory=persist_directory, embedding_function=embeddings)
    existing_ids = existing_store.get(include=[])["ids"]
    if existing_ids:
        print(f"🧹 Clearing {len(existing_ids)} previously-ingested chunk(s) before re-ingesting...")
        existing_store.delete(ids=existing_ids)

    Chroma.from_documents(
        documents=semantic_chunks,
        embedding=embeddings,
        persist_directory=persist_directory
    )
    print("✅ Knowledge base built. Chroma index is fully primed and searchable.")

if __name__ == "__main__":
    # Fallback configuration parameter check to enable straightforward terminal testing runs
    if "OPENAI_API_KEY" not in os.environ:
        print("⚠️ Environment Warning: OPENAI_API_KEY is currently unassigned in this shell context.")
    build_production_knowledge_base(ttl_days=7)
