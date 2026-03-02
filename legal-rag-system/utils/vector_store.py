"""
Vector store utilities for creating and managing law and case databases.
"""

from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, DirectoryLoader
import os


class VectorStoreManager:
    """Manages vector databases for laws and cases."""

    def __init__(self, persist_directory="./vector_dbs"):
        self.persist_directory = persist_directory
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001"
        )

    def create_law_db(self, data_path="./data/laws"):
        """Create vector store from law documents."""
        print(f"Loading law documents from {data_path}...")

        # Load documents
        loader = DirectoryLoader(data_path, glob="**/*.txt", loader_cls=TextLoader)
        documents = loader.load()

        # Split into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200, separators=["\n\n", "\n", ".", " "]
        )
        chunks = text_splitter.split_documents(documents)

        if not chunks:
            raise ValueError(
                "No law chunks created. Please check that law documents are valid and not empty."
            )

        print(f"Created {len(chunks)} law chunks")

        # Create vector store
        law_db = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=f"{self.persist_directory}/law_db",
            collection_name="laws",
        )

        print("Law database created successfully!")
        return law_db

    def create_case_db(self, data_path="./data/cases"):
        """Create vector store from case documents."""
        print(f"Loading case documents from {data_path}...")

        # Load documents
        loader = DirectoryLoader(data_path, glob="**/*.txt", loader_cls=TextLoader)
        documents = loader.load()

        # Split into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800, chunk_overlap=150, separators=["\n\n", "\n", ".", " "]
        )
        chunks = text_splitter.split_documents(documents)

        if not chunks:
            raise ValueError(
                "No case chunks created. Please check that case documents are valid and not empty."
            )

        print(f"Created {len(chunks)} case chunks")

        # Create vector store
        case_db = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=f"{self.persist_directory}/case_db",
            collection_name="cases",
        )

        print("Case database created successfully!")
        return case_db

    def load_law_db(self):
        """Load existing law database."""
        import os

        law_db_path = f"{self.persist_directory}/law_db"
        if not os.path.exists(law_db_path):
            raise FileNotFoundError(
                f"Law database not found at {law_db_path}. Please run 'python ingest_data.py' first."
            )

        return Chroma(
            persist_directory=law_db_path,
            embedding_function=self.embeddings,
            collection_name="laws",
        )

    def load_case_db(self):
        """Load existing case database."""
        import os

        case_db_path = f"{self.persist_directory}/case_db"
        if not os.path.exists(case_db_path):
            raise FileNotFoundError(
                f"Case database not found at {case_db_path}. Please run 'python ingest_data.py' first."
            )

        return Chroma(
            persist_directory=case_db_path,
            embedding_function=self.embeddings,
            collection_name="cases",
        )
