"""
Main Company Research Agent using DeepAgent Architecture
Orchestrates multiple specialized sub-agents for comprehensive account planning
"""

from typing import Dict, Any, List, Optional, Callable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from config.settings import config
from src.vector_store.pinecone_store import vector_store
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from src.agents.sub_agents import (
    PineconeRetrieverTool,
    CompanyOverviewAgent,
    ProductFitAgent,
    GoalsAgent,
    DeptMappingAgent,
    SynergyAgent,
    PricingAgent,
    ROIAgent,
    AdditionalDataRequestAgent,
    invoke_llm_with_fallback  # Import the fallback function
)
from src.tools.web_scraper import web_scraper, search_tool
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class DeepAgentOrchestrator:
    """
    Main orchestrator for company research using specialized sub-agents
    
    This implements a simplified DeepAgent pattern where:
    - Main agent coordinates the overall research workflow
    - Specialized sub-agents handle specific analysis tasks
    - Pinecone memory provides shared context
    - All agents can leverage web search for enhanced information
    """
    
    def __init__(self):
        """Initialize the main research agent with all sub-agents"""
        
        # Initialize LLM
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.7,
        )
        
        # Initialize Pinecone retriever tool
        self.retriever_tool_wrapper = PineconeRetrieverTool(vector_store)
        self.retriever_tool = self.retriever_tool_wrapper.get_tool()
        
        # Initialize all specialized sub-agents
        self.sub_agents = {
            'overview': CompanyOverviewAgent(self.llm, self.retriever_tool),
            'product_fit': ProductFitAgent(self.llm, self.retriever_tool),
            'goals': GoalsAgent(self.llm, self.retriever_tool),
            'dept_mapping': DeptMappingAgent(self.llm, self.retriever_tool),
            'synergy': SynergyAgent(self.llm, self.retriever_tool),
            'pricing': PricingAgent(self.llm, self.retriever_tool),
            'roi': ROIAgent(self.llm, self.retriever_tool),
            'additional_data': AdditionalDataRequestAgent(self.llm, self.retriever_tool),
        }
        
        # Memory (Pinecone vector store)
        self.memory = vector_store
        
        logger.info("DeepAgent Orchestrator initialized with 8 specialized sub-agents (including AdditionalDataRequestAgent)")
    
    def process_prompt(self, user_prompt: str) -> Dict[str, Any]:
        """
        Process user prompt using Gemini to extract structured information.
        Handles different user types: confused, efficient, chatty, and edge cases.
        
        Args:
            user_prompt: Raw user input/prompt
        
        Returns:
            Dictionary with company_name, additional_data_requested, references_given, 
            associated_companies, user_type, and needs_clarification
        """
        logger.info(f"Processing prompt with Gemini: {user_prompt[:100]}...")
        
        system_prompt = """You are an AI assistant that extracts structured information from user prompts for company research.

Analyze the user's prompt and extract the following information in JSON format:
{
    "company_name": "Primary company name mentioned (extract exactly as mentioned, empty string if unclear/not found)",
    "additional_data_requested": "Any specific additional data or analysis requested beyond standard analysis (empty string if none)",
    "references_given": "Any reference data, context, or background information provided by user (empty string if none)",
    "associated_companies": ["List of other company names mentioned for comparison or context (empty array if none)"],
    "user_type": "confused|efficient|chatty|edge_case|standard",
    "needs_clarification": true/false,
    "edge_case_type": "personal_info|confidential_data|off_topic|none"
}

USER TYPE DETECTION:
- **confused**: Vague/uncertain language ("I think...", "umm...", "not sure", "maybe", "I need help with a company but...")
- **efficient**: Direct, concise, specific instructions ("Research X. Focus on Y.", short and to-the-point)
- **chatty**: Long messages with tangents, personal stories, multiple unrelated topics
- **edge_case**: Requests for personal employee info, confidential financials, or completely off-topic
- **standard**: Normal, clear research request

EDGE CASE TYPES:
- **personal_info**: Asking about CTO's pets, favorite food, hobbies, personal life
- **confidential_data**: Exact funding runway, undisclosed financials, private metrics
- **off_topic**: Weather, recipes, jokes, unrelated to company research
- **none**: Not an edge case

NEEDS CLARIFICATION:
- Set to true if company name is vague, uncertain, or not clearly mentioned
- Set to false if company name is clear and research intent is obvious

Rules:
- Extract PRIMARY company name - the main subject of research
- If company name unclear or user seems confused, set needs_clarification=true
- For edge cases requesting inappropriate info, still try to extract company name if mentioned
- Return ONLY valid JSON, no other text

Examples:

User: "Apple Inc"
Response: {"company_name": "Apple Inc", "additional_data_requested": "", "references_given": "", "associated_companies": [], "user_type": "standard", "needs_clarification": false, "edge_case_type": "none"}

User: "Hi... I need some help with a company but I'm not really sure what I'm looking for."
Response: {"company_name": "", "additional_data_requested": "", "references_given": "", "associated_companies": [], "user_type": "confused", "needs_clarification": true, "edge_case_type": "none"}

User: "Research Atrium Health. Focus only on strategic alignment with Eightfold's talent acquisition suite. Keep it short."
Response: {"company_name": "Atrium Health", "additional_data_requested": "Focus on strategic alignment with Eightfold's talent acquisition suite, concise output", "references_given": "", "associated_companies": [], "user_type": "efficient", "needs_clarification": false, "edge_case_type": "none"}

User: "Hey there! So I've been thinking about this company called Bluewave Systems—funny name, right? Reminds me of my beach trip last year. Anyway, they seem interesting."
Response: {"company_name": "Bluewave Systems", "additional_data_requested": "", "references_given": "", "associated_companies": [], "user_type": "chatty", "needs_clarification": false, "edge_case_type": "none"}

User: "Tell me what pets the CTO of Hypernova AI has and what her favorite food is."
Response: {"company_name": "Hypernova AI", "additional_data_requested": "", "references_given": "", "associated_companies": [], "user_type": "edge_case", "needs_clarification": false, "edge_case_type": "personal_info"}

User: "Umm... I think it's called Veritas Cloud. I want to know if Eightfold could work with them?"
Response: {"company_name": "Veritas Cloud", "additional_data_requested": "Partnership potential with Eightfold AI", "references_given": "", "associated_companies": [], "user_type": "confused", "needs_clarification": false, "edge_case_type": "none"}
"""
        
        try:
            # Create prompt as a single string
            full_prompt = f"""{system_prompt}

User Input: {user_prompt}"""
            
            # Use fallback mechanism for API key rotation
            response_text = invoke_llm_with_fallback(full_prompt).strip()
            
            # Extract JSON from response (handle cases where LLM adds extra text)
            json_match = re.search(r'\{[^\{\}]*(?:\{[^\{\}]*\}[^\{\}]*)*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                parsed = json.loads(json_str)
            else:
                parsed = json.loads(response_text)
            
            # Validate and set defaults
            result = {
                'company_name': parsed.get('company_name', '').strip(),
                'additional_data_requested': parsed.get('additional_data_requested', '').strip(),
                'references_given': parsed.get('references_given', '').strip(),
                'associated_companies': parsed.get('associated_companies', []),
                'user_type': parsed.get('user_type', 'standard'),
                'needs_clarification': parsed.get('needs_clarification', False),
                'edge_case_type': parsed.get('edge_case_type', 'none')
            }
            
            # Fallback: if no company name extracted, try to extract from prompt directly
            if not result['company_name']:
                # Simple extraction - take first capitalized sequence
                words = user_prompt.split()
                for i, word in enumerate(words):
                    if word and word[0].isupper():
                        # Take up to 3 words for company name
                        result['company_name'] = ' '.join(words[i:min(i+3, len(words))])
                        break
            
            logger.info(f"Extracted: company={result['company_name']}, user_type={result['user_type']}, needs_clarification={result['needs_clarification']}, edge_case={result['edge_case_type']}")
            return result
            
        except Exception as e:
            logger.error(f"Error processing prompt: {e}")
            # Fallback - treat entire prompt as company name
            return {
                'company_name': user_prompt.strip(),
                'additional_data_requested': '',
                'references_given': '',
                'associated_companies': [],
                'user_type': 'standard',
                'needs_clarification': True,
                'edge_case_type': 'none'
            }
    
    def gather_company_data(self, company_name: str, additional_context: str = '') -> Dict[str, Any]:
        """
        Gather initial data about the company using web search and scraping
        First checks if sufficient data already exists in vector store
        
        Args:
            company_name: Name of the company to research
            additional_context: Additional context or reference data to enhance search
        
        Returns:
            Dictionary with gathered data statistics
        """
        logger.info(f"Gathering data for {company_name}...")
        if additional_context:
            logger.info(f"Using additional context: {additional_context[:100]}...")
        
        try:
            # Step 1: Check if we already have sufficient data
            data_check = self.memory.has_sufficient_company_data(company_name, min_docs=10)
            
            if data_check['has_data'] and not data_check['should_scrape']:
                logger.info(f"✓ Using existing data for {company_name} ({data_check['doc_count']} documents, quality: {data_check['quality_score']:.2f})")
                return {
                    'success': True,
                    'search_results': 0,
                    'website_pages': 0,
                    'total_documents': data_check['doc_count'],
                    'used_existing_data': True,
                    'quality_score': data_check['quality_score']
                }
            
            # Step 2: Insufficient data - proceed with web scraping
            logger.info(f"📡 Scraping web for {company_name} (existing: {data_check['doc_count']} docs, quality: {data_check['quality_score']:.2f})")
            
            search_queries = [
                f"{company_name} company overview business model products services",
                f"{company_name} strategic goals expansion plans growth initiatives",
                f"{company_name} leadership team executives stakeholders",
                f"{company_name} annual report financial results workforce",
                f"{company_name} company culture employee experience hiring"
            ]
            
            all_results = []
            for query in search_queries:
                try:
                    results = search_tool.search_company_info(company_name, query=query, max_results=5)
                    if results:
                        all_results.extend(results)
                        logger.info(f"Query '{query}': found {len(results)} results")
                except Exception as e:
                    logger.warning(f"Error searching '{query}': {e}")
                    continue
            
            if all_results:
                self.memory.add_company_data(
                    company_name,
                    all_results,
                    source="web_search"
                )
                logger.info(f"Added {len(all_results)} search results to vector store")
            
            website_results = web_scraper.scrape_company_website(company_name)
            
            if website_results:
                self.memory.add_company_data(
                    company_name,
                    website_results,
                    source="website_scrape"
                )
                logger.info(f"Added {len(website_results)} website pages to vector store")
            
            return {
                'success': True,
                'search_results': len(all_results),
                'website_pages': len(website_results) if website_results else 0,
                'total_documents': len(all_results) + (len(website_results) if website_results else 0),
                'used_existing_data': False
            }
            
        except Exception as e:
            logger.error(f"Error gathering company data: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def run_agent_parallel(
        self, 
        agent_key: str, 
        agent_name: str, 
        company_name: str, 
        references: str = '',
        additional_data_requested: str = '', 
        associated_companies: List[str] = None
    ) -> Dict[str, Any]:
        """
        Run a single agent (helper for parallel execution)
        
        Args:
            agent_key: Agent key (e.g., 'overview')
            agent_name: Human-readable agent name
            company_name: Company to analyze
            references: Reference information provided by user
            additional_data_requested: Specific data request for AdditionalDataRequestAgent
            associated_companies: List of associated companies for comparison
        
        Returns:
            Dictionary with agent analysis result
        """
        try:
            logger.info(f"Running {agent_name} for {company_name}...")
            agent = self.sub_agents[agent_key]
            
            # Special handling for AdditionalDataRequestAgent - needs extra parameters
            if agent_key == 'additional_data':
                analysis = agent.analyze(
                    company_name, 
                    additional_data_requested, 
                    associated_companies or [],
                    references
                )
            else:
                # All other agents get references parameter
                analysis = agent.analyze(company_name, references)
            
            return {
                'agent_key': agent_key,
                'name': agent_name,
                'content': analysis,
                'status': 'success'
            }
        except Exception as e:
            logger.error(f"Error in {agent_name}: {e}")
            return {
                'agent_key': agent_key,
                'name': agent_name,
                'content': f"Error: {str(e)}",
                'status': 'error'
            }
    
    def get_retrieved_documents(self) -> Dict[str, List[Dict]]:
        """Get all documents retrieved during agent execution"""
        return self.retriever_tool_wrapper.retrieved_docs
    
    def reset_retrieved_documents(self):
        """Reset tracked documents for a new research session"""
        self.retriever_tool_wrapper.retrieved_docs = {
            'eightfold': [],
            'target': []
        }
    
    def generate_account_plan(
        self,
        company_name: str,
        gather_data: bool = True,
        agents_to_run: Optional[List[str]] = None,
        references: str = '',
        additional_data_requested: str = '',
        associated_companies: List[str] = None,
        parallel: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive account plan for a company
        
        Args:
            company_name: Name of the target company
            gather_data: Whether to gather fresh data first (default: True)
            agents_to_run: List of agent keys to run, or None for all agents
            references: Reference information provided by user
            additional_data_requested: Specific data request for AdditionalDataRequestAgent
            associated_companies: List of associated companies for comparison
            parallel: Whether to run agents in parallel (default: True)
            progress_callback: Optional callback function for progress updates
        
        Returns:
            Dictionary containing all agent analyses
        """
        logger.info(f"Generating account plan for {company_name} (parallel={parallel})")
        
        # Step 1: Gather company data if requested
        if gather_data:
            # Build additional context from references
            additional_context = ''
            if references:
                additional_context += f"Reference Information: {references}\n\n"
            if additional_data_requested:
                additional_context += f"Additional Analysis Requested: {additional_data_requested}\n\n"
                
            data_stats = self.gather_company_data(company_name, additional_context)
            if not data_stats.get('success'):
                logger.warning(f"Data gathering had issues: {data_stats.get('error')}")
        
        # Step 2: Determine which agents to run
        if agents_to_run is None:
            agents_to_run = list(self.sub_agents.keys())
            # Only include additional_data agent if there's an actual request
            if not additional_data_requested or not additional_data_requested.strip():
                if 'additional_data' in agents_to_run:
                    agents_to_run.remove('additional_data')
        
        # Step 3: Prepare results structure
        results = {
            'company_name': company_name,
            'timestamp': datetime.now().isoformat(),
            'analyses': {}
        }
        
        agent_sequence = [
            ('overview', 'Company Overview & Value Proposition'),
            ('product_fit', 'Product-Goal Alignment'),
            ('goals', 'Long-term Strategic Goals'),
            ('dept_mapping', 'Departments & Decision Makers'),
            ('synergy', 'Partnership Synergies'),
            ('pricing', 'Pricing & Packaging Recommendation'),
            ('roi', 'ROI & Business Impact Projections'),
            ('additional_data', 'Additional Data Request'),
        ]
        
        # Filter to only agents requested
        agents_to_execute = [(k, n) for k, n in agent_sequence if k in agents_to_run]
        
        # Step 4: Run agents (parallel or sequential)
        if parallel and len(agents_to_execute) > 1:
            logger.info(f"Running {len(agents_to_execute)} agents in parallel...")
            
            with ThreadPoolExecutor(max_workers=min(8, len(agents_to_execute))) as executor:
                # Submit all agent tasks
                future_to_agent = {
                    executor.submit(
                        self.run_agent_parallel, 
                        agent_key, 
                        agent_name, 
                        company_name, 
                        references, 
                        additional_data_requested,
                        associated_companies
                    ): (agent_key, agent_name)
                    for agent_key, agent_name in agents_to_execute
                }
                
                # Collect results as they complete
                for future in as_completed(future_to_agent):
                    agent_key, agent_name = future_to_agent[future]
                    try:
                        result = future.result()
                        results['analyses'][result['agent_key']] = {
                            'name': result['name'],
                            'content': result['content'],
                            'status': result['status']
                        }
                        logger.info(f"✓ Completed {agent_name}")
                        
                        if progress_callback:
                            progress_callback({
                                'agent_key': agent_key,
                                'agent_name': agent_name,
                                'status': result['status'],
                                'content': result['content']
                            })
                            
                    except Exception as e:
                        logger.error(f"Exception in {agent_name}: {e}")
                        results['analyses'][agent_key] = {
                            'name': agent_name,
                            'content': f"Error: {str(e)}",
                            'status': 'error'
                        }
                        
                        if progress_callback:
                            progress_callback({
                                'agent_key': agent_key,
                                'agent_name': agent_name,
                                'status': 'error',
                                'error': str(e)
                            })
        else:
            # Sequential execution (original behavior)
            logger.info(f"Running {len(agents_to_execute)} agents sequentially...")
            for agent_key, agent_name in agents_to_execute:
                try:
                    logger.info(f"Running {agent_name}...")
                    agent = self.sub_agents[agent_key]
                    
                    # Special handling for AdditionalDataRequestAgent
                    if agent_key == 'additional_data':
                        analysis = agent.analyze(
                            company_name, 
                            additional_data_requested,
                            associated_companies or [],
                            references
                        )
                    else:
                        # All other agents get references parameter
                        analysis = agent.analyze(company_name, references)
                    
                    results['analyses'][agent_key] = {
                        'name': agent_name,
                        'content': analysis,
                        'status': 'success'
                    }
                    
                    logger.info(f"✓ Completed {agent_name}")
                    
                    if progress_callback:
                        progress_callback({
                            'agent_key': agent_key,
                            'agent_name': agent_name,
                            'status': 'success',
                            'content': analysis
                        })
                    
                except Exception as e:
                    logger.error(f"Error in {agent_name}: {e}")
                    results['analyses'][agent_key] = {
                        'name': agent_name,
                        'content': f"Error: {str(e)}",
                        'status': 'error'
                    }
                    
                    if progress_callback:
                        progress_callback({
                            'agent_key': agent_key,
                            'agent_name': agent_name,
                            'status': 'error',
                            'error': str(e)
                        })
        
        return results
    
    def get_account_plan_summary(self, account_plan: Dict[str, Any]) -> str:
        """
        Generate a concise summary of the account plan
        
        Args:
            account_plan: Full account plan from generate_account_plan()
        
        Returns:
            Summary text
        """
        company = account_plan['company_name']
        timestamp = account_plan['timestamp']
        analyses = account_plan['analyses']
        
        summary = f"""
{'='*80}
ACCOUNT PLAN SUMMARY: {company}
Generated: {timestamp}
{'='*80}

Analyses Completed: {len([a for a in analyses.values() if a['status'] == 'success'])}/{len(analyses)}

"""
        
        for agent_key in ['overview', 'product_fit', 'goals', 'dept_mapping', 'synergy', 'pricing', 'roi', 'additional_data']:
            if agent_key in analyses:
                analysis = analyses[agent_key]
                status = "✓" if analysis['status'] == 'success' else "✗"
                summary += f"{status} {analysis['name']}\n"
        
        return summary


class AccountPlanDashboard:
    """
    Dashboard generator for creating comprehensive account plan reports
    """
    
    @staticmethod
    def generate_markdown(account_plan: Dict[str, Any], output_file: Optional[str] = None) -> str:
        """
        Generate markdown-formatted account plan dashboard
        
        Args:
            account_plan: Account plan from DeepAgentOrchestrator
            output_file: Optional file path to save the markdown
        
        Returns:
            Markdown content
        """
        company = account_plan['company_name']
        timestamp = account_plan['timestamp']
        analyses = account_plan['analyses']
        
        # Build markdown document
        md_content = f"""# Account Plan: {company}

**Generated:** {timestamp}  
**Powered by:** Eightfold AI Research Agent

---

## Executive Summary

This comprehensive account plan analyzes **{company}** to identify opportunities for Eightfold AI's talent intelligence platform. The analysis covers company overview, product fit, strategic goals, organizational structure, partnership synergies, pricing recommendations, and ROI projections.

---

"""
        
        # Add each analysis section
        sections = [
            ('overview', '## 1. Company Overview & Value Proposition'),
            ('product_fit', '## 2. Product-Goal Alignment'),
            ('goals', '## 3. Long-term Strategic Goals'),
            ('dept_mapping', '## 4. Departments & Decision Makers'),
            ('synergy', '## 5. Partnership Synergies'),
            ('pricing', '## 6. Pricing & Packaging Recommendation'),
            ('roi', '## 7. ROI & Business Impact Projections'),
            ('additional_data', '## 8. Additional Data Request'),
        ]
        
        for agent_key, section_title in sections:
            if agent_key in analyses:
                analysis = analyses[agent_key]
                
                md_content += f"{section_title}\n\n"
                
                if analysis['status'] == 'success':
                    md_content += f"{analysis['content']}\n\n"
                    md_content += "---\n\n"
                else:
                    md_content += f"*Analysis unavailable: {analysis['content']}*\n\n"
                    md_content += "---\n\n"
        
        # Add footer
        md_content += f"""
## Next Steps

1. **Review & Validate**: Review this analysis with the sales team and validate key assumptions
2. **Customize Pitch**: Use insights to customize the sales pitch and demo for {company}
3. **Identify Champions**: Reach out to recommended departments and personas
4. **Prepare ROI Materials**: Use ROI projections to build business case materials
5. **Schedule Discovery**: Set up initial discovery call with key stakeholders

---

*This account plan was automatically generated by Eightfold AI's Company Research Agent.*  
*For questions or updates, please contact the account team.*
"""
        
        # Save to file if requested
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                logger.info(f"Account plan saved to {output_file}")
            except Exception as e:
                logger.error(f"Error saving account plan: {e}")
        
        return md_content
    
    @staticmethod
    def generate_json(account_plan: Dict[str, Any]) -> str:
        """
        Generate JSON-formatted account plan for programmatic use
        
        Args:
            account_plan: Account plan from DeepAgentOrchestrator
        
        Returns:
            JSON string
        """
        return json.dumps(account_plan, indent=2, ensure_ascii=False)
    
    @staticmethod
    def generate_html(account_plan: Dict[str, Any]) -> str:
        """
        Generate HTML-formatted account plan dashboard
        
        Args:
            account_plan: Account plan from DeepAgentOrchestrator
        
        Returns:
            HTML content
        """
        company = account_plan['company_name']
        timestamp = account_plan['timestamp']
        analyses = account_plan['analyses']
        
        # Convert markdown content to HTML-friendly format
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Account Plan: {company}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
        }}
        .header .meta {{
            opacity: 0.9;
            margin-top: 10px;
        }}
        .section {{
            background: white;
            padding: 25px;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            color: #667eea;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-top: 0;
        }}
        .section-content {{
            white-space: pre-wrap;
            font-family: 'Georgia', serif;
        }}
        .error {{
            color: #d32f2f;
            font-style: italic;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Account Plan: {company}</h1>
        <div class="meta">
            <strong>Generated:</strong> {timestamp}<br>
            <strong>Powered by:</strong> Eightfold AI Research Agent
        </div>
    </div>
"""
        
        # Add sections
        sections = [
            ('overview', 'Company Overview & Value Proposition'),
            ('product_fit', 'Product-Goal Alignment'),
            ('goals', 'Long-term Strategic Goals'),
            ('dept_mapping', 'Departments & Decision Makers'),
            ('synergy', 'Partnership Synergies'),
            ('pricing', 'Pricing & Packaging Recommendation'),
            ('roi', 'ROI & Business Impact Projections'),
            ('additional_data', 'Additional Data Request'),
        ]
        
        for agent_key, section_title in sections:
            if agent_key in analyses:
                analysis = analyses[agent_key]
                
                html_content += f"""
    <div class="section">
        <h2>{section_title}</h2>
        <div class="section-content">
"""
                
                if analysis['status'] == 'success':
                    # Escape HTML and preserve formatting
                    content = analysis['content'].replace('<', '&lt;').replace('>', '&gt;')
                    html_content += content
                else:
                    html_content += f'<span class="error">Analysis unavailable: {analysis["content"]}</span>'
                
                html_content += """
        </div>
    </div>
"""
        
        html_content += f"""
    <div class="footer">
        <p>This account plan was automatically generated by Eightfold AI's Company Research Agent.</p>
        <p>For questions or updates, please contact the account team.</p>
    </div>
</body>
</html>
"""
        
        return html_content


# Global instance
main_agent = DeepAgentOrchestrator()
dashboard = AccountPlanDashboard()
