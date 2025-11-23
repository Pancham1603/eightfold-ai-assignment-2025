"""
Configuration management for the Company Research Assistant
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration"""
    
    # Project root directory
    BASE_DIR = Path(__file__).resolve().parent.parent
    
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Support multiple API keys (comma-separated: key1,key2,key3)
    _google_keys_str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_API_KEYS = [key.strip() for key in _google_keys_str.split(',') if key.strip()]
    GOOGLE_API_KEY = GOOGLE_API_KEYS[0] if GOOGLE_API_KEYS else ""
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
    PINECONE_REGION = os.getenv("PINECONE_REGION", "asia-southeast1")
    PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "company-research")
    PINECONE_DIMENSION = int(os.getenv("PINECONE_DIMENSION", "384"))  # all-MiniLM-L6-v2 embeddings
    
    AGENT_VERBOSE = os.getenv("AGENT_VERBOSE", "True").lower() == "true"
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))
    MAX_SEARCH_RESULTS = int(os.getenv('MAX_SEARCH_RESULTS', 10))
    SCRAPING_TIMEOUT = int(os.getenv('SCRAPING_TIMEOUT', 30))
    
    # Document ingestion settings
    EIGHTFOLD_DOCS_FOLDER = os.getenv("EIGHTFOLD_DOCS_FOLDER", str(BASE_DIR / "data" / "eightfold_reference"))
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
    CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
    
    # Account plan output settings
    ACCOUNT_PLANS_FOLDER = os.getenv("ACCOUNT_PLANS_FOLDER", str(BASE_DIR / "data" / "account_plans"))
    
    @classmethod
    def validate(cls):
        if not cls.GOOGLE_API_KEY:
            raise ValueError("Google API key must be configured")
        if not cls.PINECONE_API_KEY:
            raise ValueError("Pinecone API key must be configured")
        return True

config = Config()