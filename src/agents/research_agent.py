"""
LangChain agent for company research using Google Gemini
"""

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from typing import Dict, Any, List, Annotated
import logging
from config.settings import config
from src.tools.web_scraper import web_scraper, search_tool
from src.vector_store.pinecone_store import vector_store

logger = logging.getLogger(__name__)


class CompanyResearchAgent:
    """AI Agent for researching companies using Google Gemini"""
    
    def __init__(self):
        """Initialize the research agent with Gemini"""
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.7,
            convert_system_message_to_human=True  
        )
        
        # Define research tools as decorators
        self.tools = self._create_tools()
        
        # Create agent using langgraph
        self.agent_executor = create_agent(
            self.llm,
            self.tools,
            system_prompt="You are a helpful company research assistant. Use the available tools to gather comprehensive information about companies. Always cite your sources and provide structured, actionable insights."
        )
        
        logger.info("Company Research Agent initialized with Google Gemini")
    
    def _create_tools(self) -> List:
        """Create tools for the agent"""
        
        @tool
        def search_company_info(company_name: str) -> str:
            """Search the web for information about a company. Use this to find recent news, company overview, products, and general information."""
            try:
                results = search_tool.search_company_info(
                    company_name, 
                    query=f"{company_name} company overview products services business model",
                    max_results=10
                )
                
                if not results:
                    return f"No search results found for {company_name}"
                
                # Store in vector DB
                vector_store.add_company_data(
                    company_name,
                    results,
                    source="web_search"
                )
                
                # Return summary
                summary = f"Found {len(results)} search results for {company_name}:\n\n"
                for idx, result in enumerate(results[:3], 1):
                    content = result['content'][:200]
                    url = result['metadata'].get('url', 'N/A')
                    summary += f"{idx}. {content}... (Source: {url})\n\n"
                
                return summary
                
            except Exception as e:
                logger.error(f"Search error: {e}")
                return f"Error searching for {company_name}: {str(e)}"
        
        @tool
        def scrape_company_website(company_name: str) -> str:
            """Scrape a company's official website for detailed information AND search results. Use this to get comprehensive data from both the company's website and top search results about them."""
            try:
                # First, scrape the company website
                website_results = web_scraper.scrape_company_website(company_name)
                
                # Also get top search results
                search_results = search_tool.search_company_info(
                    company_name,
                    query=f"{company_name} company information news products",
                    max_results=10
                )
                
                # Combine both results
                all_results = []
                summary_parts = []
                
                if website_results:
                    all_results.extend(website_results)
                    summary_parts.append(f"Scraped {len(website_results)} pages from company website")
                else:
                    summary_parts.append("Could not find or scrape company website")
                
                if search_results:
                    all_results.extend(search_results)
                    summary_parts.append(f"Scraped {len(search_results)} top search results")
                else:
                    summary_parts.append("No search results found")
                
                if not all_results:
                    return f"Could not gather any data for {company_name}"
                
                # Store combined data in vector DB
                vector_store.add_company_data(
                    company_name,
                    all_results,
                    source="comprehensive_scraping"
                )
                
                # Return summary
                summary = f"Successfully gathered {len(all_results)} total data sources for {company_name}:\n\n"
                summary += " | ".join(summary_parts) + "\n\n"
                
                # Show samples from each source type
                for result in all_results[:5]:  # Show first 5 samples
                    page_type = result['metadata'].get('type', 'page')
                    content = result['content'][:200]
                    source = result['metadata'].get('url', 'N/A')
                    summary += f"- [{page_type}] {content}... (Source: {source})\n\n"
                
                return summary
                
            except Exception as e:
                logger.error(f"Scraping error: {e}")
                return f"Error scraping data for {company_name}: {str(e)}"
        
        @tool
        def retrieve_stored_data(query: str, company_name: str = None) -> str:
            """Retrieve previously stored information about a company from the knowledge base. Use this to access historical research data. Always provide company_name parameter."""
            try:
                results = vector_store.search_company_data(query, k=5)
                
                if not results:
                    return "No stored data found for this query. Use search_company_info to gather new data."
                
                # Validate data quality using Gemini LLM
                # Concatenate all results for validation
                all_content = "\n\n".join([doc.page_content[:500] for doc in results])
                
                # Extract company name from query if not provided
                if not company_name:
                    # Try to extract from metadata
                    company_name = results[0].metadata.get('company_name', 'Unknown Company')
                
                is_meaningful = vector_store.validate_data_quality(all_content, company_name)
                
                if not is_meaningful:
                    logger.warning(f"Stored data for {company_name} is low quality or placeholder. Triggering new search.")
                    return f"Stored data for {company_name} is incomplete or under construction. Use search_company_info to gather fresh data from the web."
                
                # Data is meaningful, return it
                summary = f"Found {len(results)} relevant documents with meaningful information:\n\n"
                for idx, doc in enumerate(results, 1):
                    source = doc.metadata.get('source', 'unknown')
                    content = doc.page_content[:200]
                    summary += f"{idx}. [{source}] {content}...\n\n"
                
                return summary
                
            except Exception as e:
                logger.error(f"Retrieval error: {e}")
                return f"Error retrieving data: {str(e)}"
        
        @tool
        def get_company_context(company_name: str) -> str:
            """Get comprehensive context about a company from all stored sources PLUS insights from similar companies in the same industry. Use this to get enriched market research."""
            try:
                # Use enriched context that includes category-based insights
                context = vector_store.get_enriched_company_context(
                    company_name,
                    max_docs=10,
                    include_category_context=True
                )
                
                # Validate the context quality
                is_meaningful = vector_store.validate_data_quality(context[:1000], company_name)
                
                if not is_meaningful:
                    logger.warning(f"Context for {company_name} is low quality. Triggering new search.")
                    return f"Stored context for {company_name} is incomplete (website under construction or limited info). Use scrape_company_website to get fresh data."
                
                return context
                
            except Exception as e:
                logger.error(f"Context retrieval error: {e}")
                return f"Error getting context for {company_name}: {str(e)}"
        
        @tool
        def get_industry_insights(industry_category: str) -> str:
            """Get market research and insights for a specific industry category. Use this to understand industry trends, common business models, and market analysis. Available categories: TECHNOLOGY_SOFTWARE, FINANCE_FINTECH, HEALTHCARE_MEDICAL, ECOMMERCE_RETAIL, MANUFACTURING_INDUSTRIAL, MARKETING_ADVERTISING, EDUCATION_EDTECH, CONSULTING_SERVICES, REAL_ESTATE_CONSTRUCTION, TELECOMMUNICATIONS, ENERGY_UTILITIES, TRANSPORTATION_LOGISTICS, MEDIA_ENTERTAINMENT, HOSPITALITY_TRAVEL, AGRICULTURE_FOOD."""
            try:
                from src.vector_store.pinecone_store import INDUSTRY_CATEGORIES
                
                category_upper = industry_category.upper().replace(' ', '_')
                
                if category_upper not in INDUSTRY_CATEGORIES:
                    available = ', '.join(INDUSTRY_CATEGORIES.keys())
                    return f"Invalid category. Available categories: {available}"
                
                insights = vector_store.get_category_context([category_upper], max_docs=5)
                return insights
                
            except Exception as e:
                logger.error(f"Industry insights error: {e}")
                return f"Error getting industry insights: {str(e)}"
        
        return [
            search_company_info,
            scrape_company_website,
            retrieve_stored_data,
            get_company_context,
            get_industry_insights
        ]
    
    def research_company(self, company_name: str, specific_query: str = None) -> Dict[str, Any]:
        """
        Research a company and return comprehensive information
        
        Args:
            company_name: Name of the company to research
            specific_query: Optional specific question about the company
        
        Returns:
            Dictionary with research results
        """
        try:
            if specific_query:
                query = f"Research {company_name} and answer: {specific_query}"
            else:
                query = f"Provide a comprehensive analysis of {company_name} including their business model, products/services, recent news, and key information for a sales team."
            
            logger.info(f"Starting research for: {company_name}")
            
            # Create the input message
            messages = [HumanMessage(content=query)]
            
            # Run the agent
            result = self.agent_executor.invoke({"messages": messages})
            
            # Extract the final response
            final_message = result["messages"][-1]
            output = final_message.content if hasattr(final_message, 'content') else str(final_message)
            
            return {
                'company_name': company_name,
                'query': query,
                'result': output,
                'success': True
            }
            
        except Exception as e:
            logger.error(f"Research error for {company_name}: {e}")
            return {
                'company_name': company_name,
                'query': specific_query or "general research",
                'result': f"Error during research: {str(e)}",
                'success': False
            }


# Global instance
research_agent = CompanyResearchAgent()
