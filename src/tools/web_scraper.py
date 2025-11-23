"""
Web scraping tools for company research with caching and async support
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
import logging
from urllib.parse import urljoin, urlparse
import time
import hashlib
import json
from pathlib import Path
import asyncio
import aiohttp
from ddgs import DDGS
from config.settings import config

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = Path(config.BASE_DIR) / "data" / "scrape_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Scraper logs directory
SCRAPER_LOGS_DIR = Path(config.BASE_DIR) / "data" / "scraper_logs"
SCRAPER_LOGS_DIR.mkdir(parents=True, exist_ok=True)


class CompanyWebScraper:
    """Scrapes company information from various web sources with caching"""
    
    def __init__(self):
        self.timeout = config.SCRAPING_TIMEOUT
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.cache_enabled = True
        self.current_company = None
    
    def _log_scraping_activity(self, company_name: str, url: str, status: str, details: str = ''):
        """Log scraping activity for a specific company"""
        if not company_name:
            return
        
        # Sanitize company name for filename
        safe_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in company_name)
        log_file = SCRAPER_LOGS_DIR / f"{safe_name}_scraper_log.json"
        
        log_entry = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'company': company_name,
            'url': url,
            'status': status,
            'details': details
        }
        
        try:
            # Load existing logs
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            else:
                logs = {'company': company_name, 'scraping_attempts': []}
            
            # Append new entry
            logs['scraping_attempts'].append(log_entry)
            
            # Save updated logs
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error logging scraping activity: {e}")
    
    def _get_cache_key(self, url: str) -> str:
        """Generate cache key from URL"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_cached(self, url: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached scrape result"""
        if not self.cache_enabled:
            return None
        
        cache_file = CACHE_DIR / f"{self._get_cache_key(url)}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                    logger.debug(f"Cache hit for {url}")
                    return cached
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
        return None
    
    def _set_cache(self, url: str, data: Dict[str, Any]) -> None:
        """Save scrape result to cache"""
        if not self.cache_enabled:
            return
        
        cache_file = CACHE_DIR / f"{self._get_cache_key(url)}.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            logger.debug(f"Cached result for {url}")
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    def scrape_company_website(self, company_name: str, url: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scrape company website for information
        
        Args:
            company_name: Name of the company
            url: Optional specific URL to scrape
        
        Returns:
            List of scraped data chunks
        """
        data_chunks = []
        self.current_company = company_name
        
        try:
            if not url:
                # Try to find company website
                self._log_scraping_activity(company_name, 'N/A', 'started', 'Starting website discovery')
                url = self._find_company_website(company_name)
            
            if not url:
                logger.warning(f"Could not find website for {company_name}")
                self._log_scraping_activity(company_name, 'N/A', 'failed', 'Could not find company website')
                return data_chunks
            
            # Scrape main page
            self._log_scraping_activity(company_name, url, 'attempting', 'Scraping main page')
            main_content = self._scrape_url(url)
            if main_content:
                self._log_scraping_activity(company_name, url, 'success', f'Scraped {len(main_content["text"])} chars from main page')
                data_chunks.append({
                    'content': main_content['text'],
                    'metadata': {
                        'url': url,
                        'title': main_content.get('title', ''),
                        'type': 'homepage'
                    }
                })
            else:
                self._log_scraping_activity(company_name, url, 'failed', 'Main page scraping returned no content')
            
            # Try to scrape about page
            about_urls = self._find_about_page(url)
            self._log_scraping_activity(company_name, url, 'info', f'Found {len(about_urls)} potential about pages')
            for about_url in about_urls[:2]:  # Limit to 2 about pages
                self._log_scraping_activity(company_name, about_url, 'attempting', 'Scraping about page')
                about_content = self._scrape_url(about_url)
                if about_content:
                    self._log_scraping_activity(company_name, about_url, 'success', f'Scraped {len(about_content["text"])} chars from about page')
                    data_chunks.append({
                        'content': about_content['text'],
                        'metadata': {
                            'url': about_url,
                            'title': about_content.get('title', ''),
                            'type': 'about'
                        }
                    })
                else:
                    self._log_scraping_activity(company_name, about_url, 'failed', 'About page scraping returned no content')
                time.sleep(1)  # Be polite
            
        except Exception as e:
            logger.error(f"Error scraping website for {company_name}: {e}")
            self._log_scraping_activity(company_name, url or 'N/A', 'error', f'Exception: {str(e)}')
        
        self._log_scraping_activity(company_name, 'N/A', 'completed', f'Scraped {len(data_chunks)} pages total')
        return data_chunks
    
    def _scrape_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Scrape a single URL with caching"""
        # Check cache first
        cached = self._get_cached(url)
        if cached:
            return cached
        
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()
            
            # Get title
            title = soup.find('title')
            title_text = title.get_text().strip() if title else ''
            
            # Get main content
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            result = {
                'text': text[:5000],  # Limit to 5000 chars per page
                'title': title_text,
                'url': url
            }
            
            # Cache the result
            self._set_cache(url, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None
    
    async def _scrape_url_async(self, session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
        """Async scrape a single URL with caching"""
        # Check cache first
        cached = self._get_cached(url)
        if cached:
            return cached
        
        try:
            async with session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=self.timeout)) as response:
                if response.status != 200:
                    logger.warning(f"HTTP {response.status} for {url}")
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Remove script and style elements
                for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                    script.decompose()
                
                # Get title
                title = soup.find('title')
                title_text = title.get_text().strip() if title else ''
                
                # Get main content
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = ' '.join(chunk for chunk in chunks if chunk)
                
                result = {
                    'text': text[:5000],
                    'title': title_text,
                    'url': url
                }
                
                # Cache the result
                self._set_cache(url, result)
                
                return result
                
        except Exception as e:
            logger.error(f"Async scraping error for {url}: {e}")
            return None
    
    async def scrape_urls_async(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape multiple URLs concurrently"""
        async with aiohttp.ClientSession() as session:
            tasks = [self._scrape_url_async(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out None and exceptions
            valid_results = []
            for result in results:
                if result and not isinstance(result, Exception):
                    valid_results.append(result)
            
            return valid_results
    
    def _find_company_website(self, company_name: str) -> Optional[str]:
        """Try to find company website using search"""
        try:
            # Simple heuristic - try common patterns
            domain_name = company_name.lower().replace(' ', '').replace(',', '').replace('.', '')
            possible_urls = [
                f"https://www.{domain_name}.com",
                f"https://{domain_name}.com",
                f"https://www.{domain_name}.io",
            ]
            
            for url in possible_urls:
                try:
                    self._log_scraping_activity(company_name, url, 'trying', 'Attempting to discover company website')
                    response = requests.head(url, timeout=5, allow_redirects=True)
                    if response.status_code == 200:
                        self._log_scraping_activity(company_name, url, 'found', f'Company website discovered (HTTP {response.status_code})')
                        return url
                    else:
                        self._log_scraping_activity(company_name, url, 'not_found', f'HTTP {response.status_code}')
                except Exception as e:
                    self._log_scraping_activity(company_name, url, 'failed', f'Connection error: {str(e)}')
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding website for {company_name}: {e}")
            return None
    
    def _find_about_page(self, base_url: str) -> List[str]:
        """Find about/company pages"""
        about_keywords = ['about', 'company', 'about-us', 'who-we-are']
        about_urls = []
        
        try:
            response = requests.get(base_url, headers=self.headers, timeout=self.timeout)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                if any(keyword in href for keyword in about_keywords):
                    full_url = urljoin(base_url, link['href'])
                    if full_url not in about_urls:
                        about_urls.append(full_url)
            
        except Exception as e:
            logger.error(f"Error finding about page: {e}")
        
        return about_urls


class CompanySearchTool:
    
    def __init__(self):
        self.ddgs = DDGS()
        self.scraper = CompanyWebScraper()
    
    def _log_search_activity(self, company_name: str, url: str, status: str, details: str = ''):
        """Log search activity for a specific company"""
        if not company_name:
            return
        
        # Use the scraper's logging method
        self.scraper._log_scraping_activity(company_name, url, status, details)
    
    def search_company_info(self, company_name: str, query: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for company information using DuckDuckGo
        
        Args:
            company_name: Name of the company
            query: Optional specific query (if None, uses default company information query)
            max_results: Maximum number of results to return
        
        Returns:
            List of search results with content
        """
        search_results = []
        self.scraper.current_company = company_name
        
        try:
            self._log_search_activity(company_name, 'DDGS', 'started', f'Starting search with query: {query or "default"}')
            search_results = self._ddgs_search(company_name, query, max_results)        
        except Exception as e:
            logger.error(f"Error searching for {company_name}: {e}")
            self._log_search_activity(company_name, 'DDGS', 'error', f'Search error: {str(e)}')
        
        self._log_search_activity(company_name, 'DDGS', 'completed', f'Returned {len(search_results)} results')
        return search_results
    
    def _ddgs_search(self, company_name: str, query: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        DuckDuckGo search with full content scraping from all results
        
        Args:
            company_name: Name of the company
            query: Optional custom search query
            max_results: Maximum number of results
        
        Returns:
            List of search results with scraped content
        """
        try:
            search_query = query or f"{company_name} company information"
            logger.info(f"DDGS search: {search_query}")
            
            results = self.ddgs.text(
                query=search_query,
                region="wt-wt",
                max_results=max_results,
                backend="auto"
            )
            
            urls_to_scrape = []
            metadata_map = {}
            
            for result in results:
                print(search_query.upper(), result)
                url = result.get('href', '')
                if url and url.startswith('http'):
                    urls_to_scrape.append(url)
                    metadata_map[url] = {
                        'title': result.get('title', ''),
                        'snippet': result.get('body', '')
                    }
                    self._log_search_activity(company_name, url, 'search_result', f'Title: {result.get("title", "N/A")}')
            
            logger.info(f"Found {len(urls_to_scrape)} URLs to scrape")
            self._log_search_activity(company_name, 'DDGS', 'info', f'Found {len(urls_to_scrape)} URLs from search results')
            
            scraped_results = []
            for url in urls_to_scrape:
                try:
                    self._log_search_activity(company_name, url, 'scraping', 'Attempting to scrape search result')
                    result = self.scraper._scrape_url(url)
                    if result:
                        scraped_results.append(result)
                        self._log_search_activity(company_name, url, 'scraped', f'Successfully scraped {len(result.get("text", ""))} chars')
                    else:
                        self._log_search_activity(company_name, url, 'failed', 'Scraping returned no content')
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Error scraping {url}: {e}")
                    self._log_search_activity(company_name, url, 'error', f'Scraping error: {str(e)}')
                    continue
            
            final_results = []
            for scraped in scraped_results:
                url = scraped['url']
                meta = metadata_map.get(url, {})
                
                final_results.append({
                    'content': scraped['text'],
                    'metadata': {
                        'url': url,
                        'title': meta.get('title', scraped.get('title', '')),
                        'snippet': meta.get('snippet', ''),
                        'type': 'search_result_full',
                        'scraped': True
                    }
                })
            
            logger.info(f"Successfully scraped {len(final_results)} complete pages")
            return final_results
            
        except Exception as e:
            logger.error(f"DDGS search error: {e}")
            return []


web_scraper = CompanyWebScraper()
search_tool = CompanySearchTool()
