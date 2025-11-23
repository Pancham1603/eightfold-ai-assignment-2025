"""
Specialized Sub-Agents for Company Research and Account Planning
Each agent focuses on a specific aspect of company analysis
"""

from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from config.settings import config
import logging

logger = logging.getLogger(__name__)

# Import web search tool
try:
    from src.tools.web_scraper import search_tool
except ImportError:
    search_tool = None
    logger.warning("Web scraper not available for agents")

# Global variable to track last successful API key index
_last_successful_key_index = 0


def invoke_llm_with_fallback(prompt: str, max_retries: int = None) -> str:
    """
    Invoke Gemini with automatic key fallback on errors.
    Remembers the last successful key and tries it first for future requests.
    
    Args:
        prompt: The prompt to send to the LLM
        max_retries: Maximum number of API keys to try (default: all available keys)
    
    Returns:
        LLM response content
    """
    global _last_successful_key_index
    
    if not config.GOOGLE_API_KEYS:
        raise ValueError("No Google API keys configured")
    
    if max_retries is None:
        max_retries = len(config.GOOGLE_API_KEYS)
    
    last_error = None
    
    # Create ordered list of keys to try: start with last successful, then others
    num_keys = len(config.GOOGLE_API_KEYS)
    key_indices_to_try = [_last_successful_key_index]
    
    # Add all other indices in order
    for i in range(num_keys):
        if i != _last_successful_key_index:
            key_indices_to_try.append(i)
    
    # Limit to max_retries
    key_indices_to_try = key_indices_to_try[:max_retries]
    
    for attempt, api_key_index in enumerate(key_indices_to_try):
        api_key = config.GOOGLE_API_KEYS[api_key_index]
        
        try:
            llm = ChatGoogleGenerativeAI(
                model=config.GEMINI_MODEL,
                google_api_key=api_key,
                temperature=0.7
            )
            response = llm.invoke(prompt)
            
            # Update last successful key index
            _last_successful_key_index = api_key_index
            
            logger.info(f"Successfully used API key {api_key_index + 1} (marked as preferred for next request)")
            return response.content
        except Exception as e:
            last_error = e
            logger.warning(f"API key {api_key_index + 1} failed: {e}")
            if attempt < len(key_indices_to_try) - 1:
                next_key_index = key_indices_to_try[attempt + 1]
                logger.info(f"Trying next API key ({next_key_index + 1})...")
                continue
    
    logger.error(f"All API keys exhausted. Last error: {last_error}")
    raise last_error


class PineconeRetrieverTool:
    """Tool for retrieving context from Pinecone vector store"""
    
    def __init__(self, vector_store):
        """
        Initialize retriever tool
        
        Args:
            vector_store: PineconeGraphRAGStore instance
        """
        self.vector_store = vector_store
        self.retrieved_docs = {
            'eightfold': [],
            'target': []
        }
    
    def get_tool(self):
        """Get the LangChain tool for Pinecone retrieval"""
        vector_store = self.vector_store
        retrieved_docs = self.retrieved_docs
        
        @tool
        def pinecone_retriever(query: str, company_name: str, include_eightfold: bool = True) -> str:
            """
            Retrieve relevant context from the knowledge base for a company.
            
            Args:
                query: The specific question or topic to search for
                company_name: Name of the target company to research
                include_eightfold: Whether to include Eightfold AI reference context (default: True)
            
            Returns:
                Retrieved context from vector store including company data and Eightfold reference
            """
            try:
                if include_eightfold:
                    # Get both company and Eightfold context
                    results = vector_store.retrieve_company_with_eightfold_context(
                        company_name=company_name,
                        query=query,
                        company_docs=5,
                        eightfold_docs=3
                    )
                    
                    # Track retrieved documents
                    for idx, doc in enumerate(results.get('eightfold_docs', [])):
                        doc_info = {
                            'title': doc.metadata.get('title', doc.metadata.get('source', 'Eightfold Document')),
                            'text': doc.page_content[:200] + '...',
                            'source': doc.metadata.get('source', 'Vector Store'),
                            'document_type': doc.metadata.get('document_type', 'reference'),
                            'score': 1.0 - (idx * 0.1),  # Simulated relevance
                            'query': query
                        }
                        # Avoid duplicates
                        if not any(d['title'] == doc_info['title'] for d in retrieved_docs['eightfold']):
                            retrieved_docs['eightfold'].append(doc_info)
                    
                    for idx, doc in enumerate(results.get('company_docs', [])):
                        doc_info = {
                            'title': doc.metadata.get('title', doc.metadata.get('source', f'{company_name} Document')),
                            'text': doc.page_content[:200] + '...',
                            'source': doc.metadata.get('source', 'Vector Store'),
                            'url': doc.metadata.get('url', ''),
                            'score': 1.0 - (idx * 0.1),  # Simulated relevance
                            'query': query
                        }
                        # Avoid duplicates
                        if not any(d['title'] == doc_info['title'] for d in retrieved_docs['target']):
                            retrieved_docs['target'].append(doc_info)
                    
                    context = f"""
=== TARGET COMPANY: {company_name} ===
{results['company_context']}

=== EIGHTFOLD AI REFERENCE ===
{results['eightfold_context']}
"""
                    return context
                else:
                    # Get only company context
                    company_context = vector_store.get_enriched_company_context(
                        company_name=company_name,
                        max_docs=5,
                        include_category_context=True
                    )
                    return f"=== {company_name} ===\n{company_context}"
                    
            except Exception as e:
                logger.error(f"Error in pinecone_retriever: {e}")
                return f"Error retrieving context: {str(e)}"
        
        return pinecone_retriever


class CompanyOverviewAgent:
    """
    Agent for analyzing company overview and identifying value opportunities
    Role: Corporate Analyst
    """
    
    PROMPT = """You are a corporate research analyst for Eightfold AI, a leading talent intelligence platform.

Your mission: Analyze {company_name} and identify how Eightfold can provide value to them.

Using the retrieved documents about {company_name} and Eightfold AI's capabilities, provide:

1. **Company Summary** (2-3 paragraphs)
   - Primary products/services and business model
   - Target market and customer base
   - Industry position and market size
   - Recent developments or strategic initiatives

2. **Key Challenges & Needs** (bullet points)
   - Workforce/talent challenges mentioned or implied
   - Growth objectives requiring hiring
   - DEI (Diversity, Equity, Inclusion) initiatives
   - Skills gaps or transformation needs
   - Retention or employee experience issues

3. **Eightfold Value Proposition** (3-5 specific points)
   - How Eightfold's talent intelligence can address their needs
   - Specific features/capabilities that align (e.g., talent acquisition AI, skills intelligence, workforce planning)
   - Expected impact on their business objectives
   - Examples or analogies from similar companies (if available)

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases like "Okay, here's", "I'm ready to", "Let me analyze", etc.
- Begin directly with your first heading or content
- Provide a well-structured analysis with clear sections and actionable insights
- Be specific about HOW Eightfold helps, not just what Eightfold does

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "CompanyOverviewAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze company overview and value opportunities"""
        try:
            # Retrieve context
            context = self.retriever_tool.invoke({
                "query": f"company overview business model products services strategic goals challenges",
                "company_name": company_name,
                "include_eightfold": True
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            # Generate analysis with API key fallback
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response_content = invoke_llm_with_fallback(prompt)
            
            return response_content
            
        except Exception as e:
            logger.error(f"Error in SynergyAgent: {e}")
            return f"Error analyzing synergies: {str(e)}"


class ProductFitAgent:
    """
    Agent for mapping Eightfold products to company goals
    Role: Product Strategist
    """
    
    PROMPT = """You are an AI product strategist and expert on Eightfold AI's talent intelligence platform.

Your mission: Determine how Eightfold's product offerings align with {company_name}'s stated goals and needs.

**Eightfold AI Product Suite:**
- Talent Acquisition: AI-powered recruiting, candidate matching, diversity hiring
- Talent Management: Internal mobility, skills development, career pathing
- Workforce Planning: Skills intelligence, workforce analytics, strategic planning
- Talent Flex: Contingent workforce management
- Resource Management: Project staffing and resource allocation

Using the retrieved context about {company_name} and Eightfold's capabilities:

1. **Goal-Product Mapping** (for each major company goal)
   Structure each goal as a clear, standalone statement without repetitive prefixes:
   
   ### [Goal Statement - e.g., "Increase Revenue Through Market Expansion"]
   - **Relevant Eightfold Product(s)**: [which products help]
   - **How It Helps**: [specific capabilities and features]
   - **Expected Outcome**: [measurable impact]
   
   (Repeat for each goal - NO "Company Goal:" prefix needed)

2. **Feature-Fit Examples**
   Organize by priority level:
   
   **High Priority:**
   - [Feature example 1]
   - [Feature example 2]
   
   **Medium Priority:**
   - [Feature example 1]
   - [Feature example 2]
   
   **Low Priority:**
   - [Feature example 1]

3. **Implementation Priority**
   - Rank which products should be implemented first based on company's immediate needs
   - Justify the priority based on business impact and urgency

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases like "Okay", "I'm ready", "Let me", etc.
- Begin directly with your first heading or content

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "ProductFitAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze product-goal alignment"""
        try:
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"company goals objectives strategic priorities product needs technology requirements talent acquisition HR",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response = self.llm.invoke(prompt)
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error in ProductFitAgent: {e}")
            return f"Error analyzing product fit: {str(e)}"


class GoalsAgent:
    """
    Agent for extracting and analyzing long-term company goals
    Role: Strategic Advisor
    """
    
    PROMPT = """You are a strategic business advisor specializing in workforce planning and organizational development.

Your mission: Identify {company_name}'s long-term strategic objectives and their workforce implications.

Using the retrieved context (annual reports, press releases, company statements):

1. **Long-Term Strategic Goals** (next 2-5 years)
   Structure each goal as a clear heading without repetitive prefixes:
   
   ### [Clear Goal Description - e.g., "Expand into Asian Markets by 2027"]
   - **Timeline**: [target date or timeframe]
   - **Workforce Implications**: [hiring needs, skills required, organizational changes]
   - **Relevance to HR/Talent**: [why this matters for talent strategy]
   - **Source**: [cite where this was found]
   
   (Repeat for each goal - NO "Goal Statement:" prefix needed)

2. **Growth Indicators**
   - Market expansion plans (new regions, products, segments)
   - Headcount growth projections
   - Skills transformation initiatives
   - Technology adoption plans

3. **Talent Strategy Alignment**
   - How these goals translate to talent acquisition needs
   - Critical roles that will be needed
   - Skills gaps that must be addressed
   - Organizational changes required

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases
- Begin directly with your first heading or content
- Present goals in priority order (most critical first) with clear workforce implications for each

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "GoalsAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze long-term goals and workforce implications"""
        try:
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"long-term goals strategic objectives growth plans expansion roadmap future vision annual report workforce planning",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response = self.llm.invoke(prompt)
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error in GoalsAgent: {e}")
            return f"Error analyzing goals: {str(e)}"


class DeptMappingAgent:
    """
    Agent for identifying key departments and decision-makers
    Role: Organizational Structure Specialist
    """
    
    PROMPT = """You are an organizational consultant and B2B sales strategist.

Your mission: Identify the key departments, roles, and decision-makers at {company_name} who would be stakeholders for Eightfold AI's talent intelligence platform.

Using the retrieved context about {company_name}:

1. **Primary Stakeholder Departments** (ranked by importance)
   For each department:
   - Department Name: [e.g., Human Resources, Talent Acquisition]
   - Key Personas: [e.g., "Chief People Officer", "VP of Talent Acquisition"]
   - Why This Department: [pain points Eightfold solves for them]
   - Engagement Strategy: [how to approach them]

2. **Decision-Maker Hierarchy**
   - Economic Buyer: [who controls budget - typically CHRO, CFO]
   - Technical Evaluator: [who assesses the platform - usually TA leaders, HR tech]
   - End Users: [who will use it daily - recruiters, hiring managers]
   - Champion Opportunity: [who might advocate internally]

3. **Entry Points** (ranked by feasibility)
   - Best entry point department/role and why
   - Alternative entry points
   - Red flags or gatekeepers to be aware of

4. **Company Size Context**
   - Estimated employee count
   - HR team size (estimated)
   - Geographic distribution
   - Org structure complexity (centralized vs. distributed)

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases
- Begin directly with your first heading or content

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "DeptMappingAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze departments and decision-makers"""
        try:
            context = self.retriever_tool.invoke({
                "query": f"company size employees leadership team executives HR department organizational structure",
                "company_name": company_name,
                "include_eightfold": True
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response = self.llm.invoke(prompt)
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error in DeptMappingAgent: {e}")
            return f"Error mapping departments: {str(e)}"


class SynergyAgent:
    """
    Agent for analyzing partnership synergies
    Role: Business Development Expert
    """
    
    PROMPT = """You are a business development expert specializing in strategic partnerships in the HR technology space.

Your mission: Analyze synergies between Eightfold AI and {company_name}, identifying mutual value creation opportunities.

Using the retrieved context:

1. **Capability Synergies**
   - {company_name}'s Strengths: [what they do well]
   - Eightfold's Strengths: [AI talent intelligence]
   - Complementary Fit: [how they enhance each other]
   - Integration Opportunities: [technical or business integration points]

2. **Strategic Alignment**
   - Shared Market Focus: [common target customers, industries]
   - Aligned Objectives: [similar business goals or missions]
   - Cultural Fit: [values, innovation approach]

3. **Value Multipliers**
   - How Eightfold amplifies {company_name}'s capabilities
   - How {company_name}'s success grows with Eightfold
   - Network effects and ecosystem benefits

4. **Competitive Positioning**
   - How this partnership strengthens both against competitors
   - Unique value proposition of the combination

5. **Case Analogies** (if applicable)
   - Similar companies that have benefited from talent intelligence
   - Industry success stories
   - Benchmark data or reference customers

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases
- Begin directly with your first heading or content

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "SynergyAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze partnership synergies"""
        try:
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"company capabilities core competencies competitive advantages market position partnerships collaboration opportunities",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response = self.llm.invoke(prompt)
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error in SynergyAgent: {e}")
            return f"Error analyzing synergy: {str(e)}"
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"company capabilities core competencies competitive advantages market position partnerships collaboration opportunities",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response = self.llm.invoke(prompt)
            
            return response.content
            
        except Exception as e:
            logger.error(f"Error in SynergyAgent: {e}")
            return f"Error analyzing synergy: {str(e)}"


class PricingAgent:
    """
    Agent for recommending pricing and packaging
    Role: Pricing Strategist
    """
    
    PROMPT = """You are a SaaS pricing strategist with expertise in HR technology and enterprise software.

Your mission: Recommend appropriate Eightfold AI pricing tier and engagement model for {company_name}.

**Eightfold Pricing Tiers (typical structure):**
- Enterprise: Large organizations (5000+ employees), full platform, custom pricing
- Mid-Market: Growing companies (500-5000 employees), modular approach, standard pricing
- Emerging: Smaller organizations (<500 employees), focused solutions, package pricing

Using the retrieved context about {company_name}:

1. **Company Profile for Pricing**
   - Estimated employee count: [number]
   - Estimated annual revenue: [if available]
   - Funding stage/financial position: [startup, growth, mature, public]
   - Current HR tech stack maturity: [basic, developing, sophisticated]
   - Geographic footprint: [single country, regional, global]

2. **Recommended Tier**
   - Pricing Tier: [Enterprise / Mid-Market / Emerging]
   - Justification: [why this tier fits their scale and budget]
   - Estimated Contract Value: [rough annual estimate based on industry benchmarks]

3. **Module Recommendations**
   - Must-Have Modules: [critical for their immediate needs]
   - Nice-to-Have Modules: [expansion opportunities]
   - Phased Approach: [if starting with subset and expanding]

4. **Value-Based Pricing Angle**
   - ROI drivers for this company
   - Cost savings they can expect (e.g., reduced time-to-hire, lower turnover)
   - Value metrics to emphasize in pricing conversation

5. **Competitive Budget Context**
   - Likely current spend on recruiting/HR tech
   - Budget constraints or opportunities
   - Procurement process complexity

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases
- Begin directly with your first heading or content

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "PricingAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze pricing and packaging recommendations"""
        try:
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"company size revenue funding employees budget financial position market segment pricing models",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response_content = invoke_llm_with_fallback(prompt)
            
            return response_content
            
        except Exception as e:
            logger.error(f"Error in PricingAgent: {e}")
            return f"Error analyzing pricing: {str(e)}"


class ROIAgent:
    """
    Agent for estimating ROI and business impact
    Role: Financial Analyst
    """
    
    PROMPT = """You are a financial analyst specializing in HR technology ROI and workforce analytics.

Your mission: Project the return on investment and business impact for {company_name} implementing Eightfold AI.

**ROI Framework for Talent Intelligence:**
- Time-to-Hire Reduction: 30-50% typical improvement
- Cost-per-Hire Reduction: 20-40% typical savings
- Quality of Hire Improvement: Better retention, performance
- Internal Mobility: 15-25% increase in internal fills
- Retention Impact: 3-10% improvement in retention rates
- Recruiter Productivity: 2-3x efficiency gains

Using the retrieved context about {company_name}:

1. **Baseline Assumptions** (estimate from industry benchmarks if not available)
   - Current employee count: [number]
   - Estimated annual hiring volume: [number of hires]
   - Average cost-per-hire: [$amount]
   - Average time-to-hire: [days]
   - Annual turnover rate: [%]
   - Cost of turnover: [estimated]

2. **6-Month ROI Projection**
   - Initial Implementation Period: [months 1-3]
   - Early Wins: [quick hits and early metrics]
   - Estimated Savings/Value: [$amount]
   - Key Metrics Improving: [which KPIs]

3. **1-Year ROI Projection**
   - Full Platform Adoption
   - Cumulative Savings: [$amount]
   - Efficiency Gains: [productivity metrics]
   - Quality Improvements: [retention, performance]
   - Cost Avoidance: [bad hires prevented, turnover reduced]

4. **3-Year Strategic Value**
   - Compound Benefits: [long-term impact]
   - Organizational Capabilities: [skills intelligence, workforce planning]
   - Competitive Advantage: [talent acquisition edge]
   - Total Value Created: [$amount]

5. **ROI Calculation**
   - Total Investment: [estimated annual cost]
   - Total Return: [savings + value created]
   - ROI Percentage: [calculation]
   - Payback Period: [months to break even]

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases
- Begin directly with your first heading or content
- Provide specific numbers where possible, clearly state assumptions, and be conservative in estimates
- Use industry benchmarks when company-specific data unavailable

Retrieved Context:
{context}

"""

    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "ROIAgent"
    
    def analyze(self, company_name: str, references: str = '') -> str:
        """Analyze ROI projections"""
        try:
            # Retrieve context with Eightfold reference documents
            context = self.retriever_tool.invoke({
                "query": f"company metrics KPIs performance revenue growth cost savings efficiency improvements ROI projections hiring metrics",
                "company_name": company_name,
                "include_eightfold": True  # Ensures eightfold_reference documents are included
            })
            
            # Add references if provided
            if references:
                context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            
            prompt = self.PROMPT.format(company_name=company_name, context=context)
            response_content = invoke_llm_with_fallback(prompt)
            
            return response_content
            
        except Exception as e:
            logger.error(f"Error in ROIAgent: {e}")
            return f"Error analyzing ROI: {str(e)}"
            
        except Exception as e:
            logger.error(f"Error in ROIAgent: {e}")
            return f"Error analyzing ROI: {str(e)}"


class AdditionalDataRequestAgent:
    """
    Agent for researching specific additional data requested by the user
    Role: Custom Research Specialist
    """
    
    PROMPT = """You are a specialized research analyst who focuses on answering specific questions and data requests about companies.

Your mission: Research and provide detailed information about {company_name} specifically addressing the user's additional data request.

**User's Additional Data Request:**
{additional_request}

**Guidelines:**
1. Focus EXCLUSIVELY on the user's specific request
2. Provide comprehensive, detailed information
3. Use data and facts from the retrieved context
4. If the request involves comparisons, provide side-by-side analysis
5. If the request involves specific metrics, provide quantitative data
6. If context is insufficient, clearly state what information is available and what is missing
7. Organize your response with clear headings and structure

**Quality Standards:**
- Be specific and detailed (not generic)
- Use concrete examples and data points
- Cite sources when available
- Acknowledge limitations if data is incomplete
- Provide actionable insights related to the request

**CRITICAL OUTPUT REQUIREMENTS:**
- Start IMMEDIATELY with the analysis - NO introductory phrases like "Okay", "Let me", "I'm ready", etc.
- Begin directly with your first heading or content

Retrieved Context:
{context}

"""
    
    def __init__(self, llm: ChatGoogleGenerativeAI, retriever_tool):
        self.llm = llm
        self.retriever_tool = retriever_tool
        self.name = "AdditionalDataRequestAgent"
    
    def analyze(self, company_name: str, additional_request: str = '', associated_companies: List[str] = None, references: str = '') -> str:
        """
        Analyze specific additional data request from user
        
        Args:
            company_name: Name of the company to research
            additional_request: Specific data or analysis requested by user
            associated_companies: List of associated companies for comparison context
            references: Reference information provided by user
        
        Returns:
            Detailed research response addressing the request
        """
        try:
            # If no additional request, return early
            if not additional_request or additional_request.strip() == '':
                return "No additional data was requested. All standard analyses are covered by other agents."
            
            # Build comprehensive search query
            search_query_parts = [company_name, additional_request]
            if associated_companies:
                search_query_parts.extend(associated_companies)
            if references:
                search_query_parts.append(references)
            
            search_query = ' '.join(search_query_parts)
            logger.info(f"AdditionalDataRequestAgent searching with query: {search_query[:100]}...")
            
            # Get web search results using DDGS
            web_context = ""
            if search_tool:
                try:
                    web_results = search_tool.search_company_info(company_name, query=search_query, max_results=5)
                    if web_results:
                        web_context = "\n\n=== WEB SEARCH RESULTS ===\n"
                        for i, result in enumerate(web_results[:5], 1):
                            web_context += f"\n[Web Source {i}]\n{result.get('content', '')[:2000]}\n"
                        logger.info(f"Retrieved {len(web_results)} web results")
                except Exception as e:
                    logger.warning(f"Web search failed: {e}")
            
            # Get vector store context
            vector_context = self.retriever_tool.invoke({
                "query": f"{additional_request} {company_name}",
                "company_name": company_name,
                "include_eightfold": False  # Focus on company-specific data for custom requests
            })
            
            # Combine all context sources
            combined_context = vector_context
            if web_context:
                combined_context += "\n\n" + web_context
            if references:
                combined_context += f"\n\n=== USER PROVIDED REFERENCES ===\n{references}"
            if associated_companies:
                combined_context += f"\n\n=== ASSOCIATED COMPANIES FOR COMPARISON ===\n{', '.join(associated_companies)}"
            
            prompt = self.PROMPT.format(
                company_name=company_name,
                additional_request=additional_request,
                context=combined_context
            )
            response_content = invoke_llm_with_fallback(prompt)
            
            return response_content
            
        except Exception as e:
            logger.error(f"Error in AdditionalDataRequestAgent: {e}")
            return f"Error researching additional data: {str(e)}"
