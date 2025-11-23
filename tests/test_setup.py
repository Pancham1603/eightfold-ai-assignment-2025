"""
Basic setup verification tests
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_imports():
    """Test that all required packages are importable"""
    try:
        import flask
        import flask_cors
        import flask_socketio
        import langchain
        import pinecone
        import bs4
        import requests
        import networkx
        import aiohttp
        print("✓ All core packages imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def test_config():
    """Test that configuration is loadable"""
    try:
        from config.settings import config
        assert config is not None
        assert hasattr(config, 'GOOGLE_API_KEY')
        assert hasattr(config, 'PINECONE_API_KEY')
        assert hasattr(config, 'PINECONE_REGION')
        print("✓ Configuration loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Config error: {e}")
        return False

def test_vector_store():
    """Test that Pinecone vector store can be imported"""
    try:
        from src.vector_store.pinecone_store import PineconeGraphRAGStore, KnowledgeGraph
        # Test knowledge graph
        kg = KnowledgeGraph()
        kg.add_entity("test_company", "ORGANIZATION")
        kg.add_relationship("test_company", "test_product", "offers")
        assert "test_company" in kg.graph.nodes()
        print("✓ Pinecone vector store and knowledge graph loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Vector store error: {e}")
        return False

def test_spacy_ner():
    """Test spaCy NER availability"""
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
            doc = nlp("Apple Inc. is based in Cupertino, California.")
            entities = [(ent.text, ent.label_) for ent in doc.ents]
            assert len(entities) > 0
            print(f"✓ spaCy NER loaded successfully (found {len(entities)} entities)")
            return True
        except OSError:
            print("⚠ spaCy model not downloaded. Run: python -m spacy download en_core_web_sm")
            return True  # Don't fail, just warn
    except ImportError:
        print("⚠ spaCy not installed (will use rule-based extraction)")
        return True  # Don't fail, just warn

def test_async_scraping():
    """Test async scraping functionality"""
    try:
        import asyncio
        import aiohttp
        from src.tools.web_scraper import CompanyWebScraper
        
        scraper = CompanyWebScraper()
        assert hasattr(scraper, 'scrape_urls_async')
        assert scraper.cache_enabled == True
        print("✓ Async scraping with caching loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Async scraping error: {e}")
        return False

def test_tools():
    """Test that tools can be imported"""
    try:
        from src.tools.web_scraper import CompanyWebScraper, CompanySearchTool
        print("✓ Web scraper tools loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Tools error: {e}")
        return False

def test_agent():
    """Test that agent module can be imported"""
    try:
        from src.agents.research_agent import CompanyResearchAgent
        # Don't initialize to avoid requiring API key
        print("✓ Research agent module loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Agent error: {e}")
        return False

def test_flask_app():
    """Test that Flask app can be imported"""
    try:
        import app
        assert app.app is not None
        print("✓ Flask application loaded successfully")
        return True
    except Exception as e:
        print(f"✗ Flask app error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("Running Setup Verification Tests")
    print("=" * 50)
    print()
    
    tests = [
        ("Package Imports", test_imports),
        ("Configuration", test_config),
        ("Pinecone Vector Store", test_vector_store),
        ("spaCy NER", test_spacy_ner),
        ("Async Scraping", test_async_scraping),
        ("Web Scraper Tools", test_tools),
        ("Research Agent", test_agent),
        ("Flask Application", test_flask_app),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"Testing: {name}")
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            results.append(False)
        print()
    
    print("=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All tests passed! Setup is complete.")
        print()
        print("Next steps:")
        print("1. Add your OpenAI API key to .env file")
        print("2. Run: python app.py")
        print("3. Open: http://localhost:5000")
    else:
        print("✗ Some tests failed. Please check the errors above.")
        sys.exit(1)
    print("=" * 50)
