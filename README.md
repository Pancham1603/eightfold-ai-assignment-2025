# Company Research Assistant AI Agent

## Overview
This project is a sophisticated **Company Research Assistant** built as an autonomous AI agent. It leverages a **Deep Agent Architecture** to orchestrate multiple specialized sub-agents, enabling comprehensive research, analysis, and account planning for target companies. The system is designed to help sales and strategy teams by automatically gathering data, analyzing fit, and generating detailed account plans.

## Table of Contents
- [Overview](#overview)
- [Setup Instructions](#setup-instructions)
- [Architecture Notes](#architecture-notes)
- [Design Decisions](#design-decisions)
- [Conversational Quality](#️-conversational-quality)
- [Agentic Behavior](#agentic-behavior)
- [Technical Implementation](#technical-implementation)
- [Intelligence & Adaptability](#intelligence--adaptability)


## Setup Instructions

### Prerequisites
- Python 3.10+
- Google Gemini API Key(s)
- Pinecone API Key
- MongoDB (optional, for chat persistence)

### Installation
1.  **Clone the repository**:
    ```bash
    git clone https://github.com/Pancham1603/eightfold-ai-assignment-2025.git
    cd eightfold-ai-assignment-2025
    ```

2.  **Create a virtual environment**:
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Linux/Mac
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration**:
    `.env.example`: Copy this file to .env and fill in your 

### Running the Application
```bash
python app.py
```
Access the dashboard at `http://localhost:5000`.



## Architecture Notes

> For detailed visual diagrams and workflow explanations, see [ARCHITECTURE_DIAGRAMS.md](./ARCHITECTURE_DIAGRAMS.md)


### High-Level Architecture
The system follows a **Deep Agent** pattern where a central **Orchestrator** manages a team of **Specialized Sub-Agents**.

>**Checkout [Component Interactions](#component-interactions) diagram**

### Key Components
1.  **Deep Agent Orchestrator (`src/agents/deep_agent.py`)**: The brain of the system. It handles user intent, manages data gathering, and coordinates sub-agents.
2.  **Specialized Sub-Agents (`src/agents/sub_agents.py`)**: Independent agents focused on specific domains (e.g., Financials, Technology, Competitors).
3.  **Pinecone Graph RAG Store (`src/vector_store/pinecone_store.py`)**: A hybrid storage solution combining vector search (Pinecone) with a Knowledge Graph for rich, contextual retrieval.
4.  **Smart Web Scraper (`src/tools/web_scraper.py`)**: An intelligent scraper that caches results, logs activity, and respects site policies.


## Design Decisions

### 1. Deep Agent vs. Single Chain
**Decision**: We chose a **Deep Agent** architecture over a single monolithic LLM chain.
**Reasoning**:
-   **Specialization**: Different aspects of company research (e.g., "Financial ROI" vs. "Cultural Fit") require different analytical lenses and prompts.
-   **Parallelism**: Sub-agents can run concurrently, significantly reducing the total time to generate a comprehensive report.
-   **Modularity**: New agents can be added (e.g., a "Legal Risk Agent") without rewriting the core logic.

### 2. Graph RAG (Retrieval Augmented Generation)
**Decision**: We implemented a **Knowledge Graph** alongside the Vector Store.

>**Checkout [Multi Company Analysis](#data-flow-with-multi-company-analysis) diagram**

**Reasoning**:
-   Vector search is great for semantic similarity but struggles with structured relationships (e.g., "Who is the CTO of Company X?").
-  **Multi-Company Comparative Analysis**: When comparing companies (e.g., "Compare Microsoft's cloud strategy with AWS"), the Knowledge Graph explicitly tracks relationships between entities across different organizations, enabling nuanced competitive analysis that pure vector similarity cannot achieve.
-   The Knowledge Graph explicitly maps entities (People, Products, Locations) and their relationships, allowing agents to answer complex queries more accurately.

<!-- ### 3. Multi-Key Management
**Decision**: Implemented a session-aware API key rotation system.
**Reasoning**:
-   LLM APIs often have rate limits. The system automatically rotates through a pool of keys if one fails, ensuring high availability and uninterrupted research sessions. -->

### 3. Quality-Dependent Scraping
**Decision**: Scraping is triggered **only** if existing data is insufficient or low quality.

>**Checkout [Quality Algorithm](#data-quality-assessment-algorithm) diagram**

**Reasoning**:
-   **Efficiency**: Avoids redundant scraping if we already have good data.
-   **Cost**: Reduces Pinecone Write and API calls.
-   **Logic**: The system calculates a `quality_score` (0-1) based on the meaningfulness of content. If `docs < 10` OR `quality < 0.6`, it triggers a fresh scrape.

### 4. Parallel Threading with Work Pool
**Decision**: Implemented `ThreadPoolExecutor` with `max_workers=8` for concurrent agent execution.

**Reasoning**:
-   **Performance**: Running multiple specialized agents sequentially would take 3-5 minutes. Parallel execution reduces this to 30-60 seconds.
-   **Resource Optimization**: The work pool manages thread allocation efficiently, preventing resource exhaustion while maximizing throughput.
-   **Non-blocking**: While agents run in background threads, the main Flask thread remains responsive to emit real-time progress updates via SocketIO.

### 5. Flask + SocketIO Real-Time Architecture
**Decision**: Built the web interface using Flask with Flask-SocketIO for bidirectional communication.

**Reasoning**:
-   **Real-Time Progress Updates**: SocketIO enables server-to-client push notifications, allowing users to see live progress as agents complete their analysis (e.g., "Overview Agent: Complete", "Pricing Agent: Running...").
-   **Asynchronous User Experience**: Users don't face a frozen interface during long-running research tasks. The UI updates dynamically with status messages, completion percentages, and intermediate results.
-   **Session Persistence**: SocketIO maintains persistent connections, enabling the system to track conversation context across multiple requests within the same research session.
-   **Lightweight**: Compared to polling-based solutions, SocketIO reduces server load and provides instant updates without client-side request overhead.

### 6. MongoDB for Conversation Persistence
**Decision**: Integrated MongoDB (optional) for storing chat history and session state.

**Reasoning**:
-   **Context Retention Across Sessions**: Stores complete conversation history, allowing users to resume research on the same company days later without losing context.
-   **Audit Trail**: Maintains a log of all research requests, agent outputs, and user interactions for compliance and debugging.
-   **Scalability**: Unlike in-memory session storage, MongoDB ensures chat history survives server restarts and scales horizontally for multi-user deployments.
-   **Structured Querying**: Enables features like "Show me all research done on SaaS companies last month" by leveraging MongoDB's flexible query capabilities.
-   **Optional Deployment**: The system degrades gracefully if MongoDB is unavailable, falling back to in-memory session management for development/testing environments.


## Conversational Quality

Ensuring a high-quality conversational experience was a priority. We addressed this through:

### Intelligent Message Analysis & Classification
Every chat message undergoes sophisticated analysis before execution:

#### Three-Tier Classification System
The `process_prompt` method employs an LLM-powered classifier to categorize each message:

1.  **Casual/Chatty Messages**:
    -   **Indicators**: Greetings, small talk, vague expressions ("Hey!", "How's it going?", "I was wondering...").
    -   **System Response**: Acknowledges politely, then redirects to business objectives ("Hello! I'm here to help with company research. Which company would you like to analyze?").
    -   **Example**: "Hi there! What can you do?" → Friendly introduction + capability summary.

2.  **Research Request (Main trigger that we use)**:
    -   **Indicators**: Contains a company name, new research objective, or explicit request ("Research Tesla", "Analyze Microsoft's cloud strategy").
    -   **System Response**: Extracts company name, identifies focus areas, initiates full data gathering and agent orchestration.
    -   **Example**: "I need an account plan for Salesforce" → Triggers scraping + all sub-agents.

3.  **Follow-Up Query**:
    -   **Indicators**: References previously discussed company, uses pronouns ("their", "they"), asks for specific sections ("What about their pricing?").
    -   **System Response**: Retrieves session context, identifies relevant sub-agents, executes targeted analysis without re-scraping.
    -   **Example**: After researching Apple, "Tell me more about their competitive landscape" → Invokes only `AdditionalDataRequestAgent` using cached data.

>**Checkout [AdditionalDataRequestAgent](#additionaldatarequest-agent-detailed-flow) diagram**

#### Structured Intent Extraction
The classification process outputs a structured JSON object:
```json
{
"type": "casual|research_request|follow_up",
"confidence": 0.0-1.0,
"reasoning": "brief explanation (mention user type if casual: confused/efficient/chatty/edge_case)"
}
```

This allows the Orchestrator to:
-   **Route efficiently**: Skip unnecessary scraping for follow-ups.
-   **Maintain context**: Preserve company name across conversation turns.
-   **Optimize token usage**: Only invoke relevant sub-agents for targeted queries.

#### Ambiguity Handling
-   **Unclear Company**: "Tell me about that tech company" → System asks: "Which company would you like to research?"
-   **Multi-Intent**: "Research Apple and tell me about their pricing" → Classifies as research_request with specific_focus=['pricing'], triggers full pipeline but highlights pricing in the response.

### User Intent Classification
The `process_prompt` method analyzes every user message to classify the user type:
-   **Confused**: "I think I need help with..." -> System offers guidance.
-   **Efficient**: "Research Apple. Focus on AI." -> System executes immediately.
-   **Chatty**: "Hey! How are you? I was thinking about..." -> System engages politely but steers back to business.
-   **Edge Case**: "What is the CTO's favorite food?" -> System politely declines irrelevant/private requests.

### Context Retention & Session State Management
The system implements sophisticated context retention mechanisms to maintain coherent, multi-turn conversations:

#### In-Memory Session State
-   **Active Session Tracking**: Maintains a session state machine (Idle → Researching → Complete) to handle context awareness.
-   **Company Context Persistence**: Remembers the `company_name` across conversation turns, enabling follow-up questions like "Tell me more about their competitors" without requiring the user to restate the company name.
-   **Reference Accumulation**: Stores user-provided references (pasted articles, job descriptions, competitive intel) throughout the conversation, incorporating them into subsequent agent analyses.
-   **Associated Companies**: Tracks previously mentioned companies for comparative analysis (e.g., "Now compare them with Google" automatically retrieves both Microsoft and Google contexts).

#### MongoDB Conversation Persistence (Optional)
-   **Long-Term Memory**: Stores complete conversation history in MongoDB, enabling users to resume research sessions after hours or days.
-   **Cross-Session Context**: Retrieves previous research on the same company to avoid redundant data gathering and provide continuity (e.g., "You researched Tesla last week. Here's updated information...").
-   **User Preference Learning**: Tracks which agents or sections users regenerate most often, enabling future optimizations.
-   **Conversation Replay**: Allows users to review past research sessions, compare how their understanding of a company evolved over time.

#### Intelligent Context Injection
Every agent invocation receives:
1. **Primary Company Context**: Full vector store data for the target company.
2. **Comparative Context**: Data for associated companies if doing competitive analysis.
3. **User-Specific Context**: References, focus areas, and constraints from the current and previous conversations.
4. **Session History**: Previous agent outputs from the same research session to avoid contradictions and ensure coherence.

This multi-layered context retention ensures the system behaves like a knowledgeable research partner who "remembers" past interactions, rather than treating each query as a standalone request.


## Agentic Behavior

### Deep Agents & Sub-Agents
We are using multiple sub agents or mini agents that each do their mutually exclusive research about a vertical of generating account plan.
-   **Invocation**: The Orchestrator determines which agents to invoke based on the user's request.
    -   *Full Report*: Invokes all agents.
    -   *Specific Query*: Invokes only relevant agents (e.g., "Check their pricing" -> Invokes `PricingAgent`).
-   **Parallel Execution**: When multiple agents are needed, they run in parallel using `ThreadPoolExecutor`. This reduces the wait time from minutes to seconds.

### Sub-Agent Roles

<details open>
<summary><strong>Overview Agent</strong></summary>

**Role**: Corporate Analyst  
**Objective**: Provides a high-level snapshot of the target company, establishing foundational context for all subsequent analyses.  

**Key Outputs**:
- Company history, founding year, and headquarters location
- Core business model and primary revenue streams
- Industry classification and market position
- Leadership team structure and key executives
- Recent major events (acquisitions, funding rounds, strategic pivots)

**Intelligence**: This agent prioritizes credible sources (official website, press releases) and cross-references multiple data points to ensure accuracy. It acts as the foundation upon which other agents build deeper insights.
</details>

<details>
<summary><strong>Product Fit Agent</strong></summary>

**Role**: Solutions Engineer  
**Objective**: Analyzes the alignment between the company's current technology stack, pain points, and potential solutions you could offer.  

**Key Outputs**:
- Technology infrastructure assessment (cloud platforms, enterprise software, data systems)
- Identified gaps or inefficiencies in their current setup
- Use case scenarios where your product/service could add value
- Integration feasibility analysis
- Technical decision-maker identification

**Intelligence**: This agent looks for explicit mentions of technologies, job postings for specific roles (e.g., "seeking DevOps engineer experienced with AWS"), and publicly stated technical challenges. It reasons about product-market fit rather than making generic recommendations.
</details>

<details>
<summary><strong>Goals Agent</strong></summary>

**Role**: Strategic Planner  
**Objective**: Uncovers the company's strategic objectives, priorities, and long-term vision to align sales messaging with their actual business needs.  

**Key Outputs**:
- Documented strategic initiatives (digital transformation, market expansion, sustainability goals)
- Growth targets and KPIs (revenue goals, market share ambitions)
- Innovation focus areas (R&D investments, emerging technology adoption)
- Competitive positioning strategies
- Risk factors or challenges publicly acknowledged by leadership

**Intelligence**: This agent analyzes earnings call transcripts, annual reports, CEO interviews, and strategic announcements. It distinguishes between marketing fluff and genuine strategic commitments by looking for resource allocation signals (budget, hiring, partnerships).
</details>

<details>
<summary><strong>Department Mapping Agent</strong></summary>

**Role**: HR/Organizational Specialist  
**Objective**: Maps out the company's organizational structure to identify key stakeholders, decision-making hierarchies, and departmental pain points.  

**Key Outputs**:
- Organizational chart (departments, reporting lines)
- Department-specific challenges (e.g., IT struggling with legacy systems, Sales needing better CRM)
- Headcount trends by department (rapid hiring in Engineering signals tech investment)
- Key influencers and champions within target departments
- Cross-functional dynamics and collaboration patterns

**Intelligence**: This agent scrapes LinkedIn for employee distributions, analyzes job postings to infer departmental priorities, and cross-references public org charts. It identifies which departments are growing (budget availability) and which are likely decision-makers for your solution.
</details>

<details>
<summary><strong>Synergy Agent</strong></summary>

**Role**: Partnership Manager  
**Objective**: Identifies existing partnerships, ecosystems, and strategic alliances that could serve as entry points or value-add talking points.  

**Key Outputs**:
- Current technology partners and integrations
- Strategic alliance network (resellers, co-marketing agreements)
- Ecosystem participation (industry consortia, open-source contributions)
- Potential mutual partners or customers
- Competitive partnership overlaps

**Intelligence**: This agent looks for press releases about partnerships, integration marketplaces, and co-branded initiatives. It reasons about how your existing partnerships could create warm introductions or demonstrate ecosystem compatibility.
</details>

<details>
<summary><strong>Pricing Agent</strong></summary>

**Role**: Sales Operations  
**Objective**: Estimates the company's budget capacity, pricing sensitivity, and willingness to invest in solutions like yours.  

**Key Outputs**:
- Estimated budget range based on company size and industry benchmarks
- Historical spending patterns on similar tools/services
- Pricing model preferences (per-seat, usage-based, enterprise license)
- Procurement process insights (centralized vs. departmental budgets)
- Contract negotiation leverage points

**Intelligence**: This agent triangulates data from public filings, industry reports, and similar company case studies. **Note**: Often hidden on the frontend because financial data is frequently incomplete or unreliable for private companies, leading to speculative outputs.
</details>

<details>
<summary><strong>ROI Agent</strong></summary>

**Role**: Business Value Consultant  
**Objective**: Builds a quantitative business case by projecting the financial and operational impact of adopting your solution.  

**Key Outputs**:
- Cost-benefit analysis framework
- Projected efficiency gains (time saved, error reduction)
- Revenue uplift potential (faster time-to-market, improved customer retention)
- Total Cost of Ownership (TCO) comparison
- Payback period and ROI timeline

**Intelligence**: This agent uses retrieved data about the company's scale, operational bottlenecks, and industry benchmarks to model outcomes. **Note**: Often hidden on the frontend because calculations rely on assumptions when hard data is sparse, yielding inconsistent results that could mislead sales teams.
</details>

<details>
<summary><strong>Additional Data Agent</strong></summary>

**Role**: Custom Researcher  
**Objective**: Handles ad-hoc, user-specified research requests that fall outside the scope of standard agents (e.g., "What's their approach to sustainability?", "Any recent controversies?").  

**Key Outputs**:
- Targeted deep-dives on specific topics
- Competitive intelligence on niche aspects
- Compliance and regulatory considerations
- Cultural insights (employee sentiment, Glassdoor reviews)
- Custom queries based on user-provided reference materials

**Intelligence**: This is the most flexible agent, using dynamic prompting to adapt to wildly different requests. It performs focused retrieval from the vector store and can incorporate user-provided context (pasted job descriptions, articles) into its analysis. It acts as the "catch-all" for anything the specialized agents don't cover.
</details>


## Technical Implementation

### AI Architecture
-   **Framework**: LangChain Deep agents for agent orchestration.
-   **Model**: Google Gemini Pro (via `ChatGoogleGenerativeAI`).
-   **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (HuggingFace) for cost-effective, high-quality embeddings.

### Chat Message Analysis
The `DeepAgentOrchestrator.process_prompt` function uses a specialized system prompt to extract structured JSON from natural language:
```json
{
"company_name": "Target Company",
"additional_data_requested": "Specific focus areas",
"user_type": "efficient",
"needs_clarification": false
}
```
This allows the system to understand complex, multi-part requests.

### Data Gathering & Quality Control
Before running agents, the system performs a **Data Health Check** (`has_sufficient_company_data`):
1.  **Search**: Queries the vector store for the company.
2.  **Deduplicate**: Removes duplicate content.
3.  **Quality Check**: Samples 5 documents and asks an LLM: "Does this contain meaningful business info?" (True/False).
4.  **Decision**:
    -   If `Quality Score >= 0.6` AND `Doc Count >= 10`: **Skip Scraping**.
    -   Else: **Trigger Web Scraper**.

### Scraping Implementation
#### Multi-Query Search Strategy
The scraper uses **targeted search queries** to ensure comprehensive coverage of the data needed for the main sub-agents:

```python
search_queries = [
    f"{company_name} company overview business model products services",
    f"{company_name} strategic goals expansion plans growth initiatives",
    f"{company_name} leadership team executives stakeholders",
    f"{company_name} annual report financial results workforce",
    f"{company_name} company culture employee experience hiring"
]
```

Each query is designed to populate the vector store with information relevant to specific agent domains:
-   **Query 1**: Feeds the **Overview Agent** with foundational company data.
-   **Query 2**: Supports the **Goals Agent** by capturing strategic direction.
-   **Query 3**: Enables the **Department Mapping Agent** to identify key decision-makers.
-   **Query 4**: Provides financial and operational context for **ROI** and **Pricing Agents**.
-   **Query 5**: Helps the **Product Fit Agent** and **Department Mapping Agent** understand organizational culture and hiring trends.

This multi-query approach ensures that the vector store contains **domain-specific context** for each specialized agent, improving retrieval accuracy during the analysis phase.

-   **Multi-Source**: Uses DuckDuckGo to find the official website, About pages, and News.
-   **Smart Parsing**: `BeautifulSoup` cleans HTML, removing navbars/footers to extract only core text.
-   **Caching**: Results are cached to disk (`data/scrape_cache`) to prevent re-scraping the same URLs.

### Parallel Sub-Agents
The `generate_account_plan` method uses Python's `concurrent.futures.ThreadPoolExecutor`:
```python
with ThreadPoolExecutor(max_workers=8) as executor:
    future_to_agent = {executor.submit(agent.analyze, ...): agent for agent in agents}
```
This allows all sub-agents to research simultaneously, limited only by API rate limits (handled by the key rotation system for local usage).

>**Checkout [Threading Model](#threading-model-with-progress-updates-using-sockets) diagram**

### Regeneration & Selective Update
Users can request updates to specific parts of the report. The `agents_to_run` parameter allows the Orchestrator to re-run only specific agents (e.g., `['pricing', 'roi']`) without regenerating the entire report, saving time and tokens.

>**Checkout [Selective Update](#selective-agent-regeneration-flow) diagram**

### Formatting & Reporting
The `AccountPlanDashboard` class aggregates the outputs from all agents into a cohesive report. It supports:
-   **Markdown**: For readable, structured documents.
-   **JSON**: For programmatic integration.
-   **HTML**: For the web dashboard.


## Intelligence & Adaptability

### Handling Guidelines & Constraints
The system is designed to adhere to strict guidelines:
-   **Privacy**: It refuses to scrape or generate personal private information.
-   **Relevance**: It filters out off-topic data during the scraping phase.
-   **Accuracy**: By using RAG (Retrieval Augmented Generation), it grounds all responses in retrieved data, minimizing hallucinations.

### Adaptability to Situations
-   **Low Data**: If a company has a thin digital footprint, the agents acknowledge the limitation rather than hallucinating facts.
-   **Ambiguity**: If the user says "Apple", the system infers "Apple Inc." but is ready to clarify if the context suggests a different entity.
-   **Contextual References**: If a user provides a pasted job description or news article ("Reference Info"), the agents incorporate this specific context into their analysis.

# System Architecture - Parallel Execution Flow

## User Input Flow

```
User Input (Natural Language)
         │
         ▼
┌────────────────────────┐
│   Flask SocketIO       │
│   handle_research_     │
│   company()            │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Gemini Prompt         │
│  Processor             │
│  process_prompt()      │
└────────┬───────────────┘
         │
         ▼
    Extract JSON:
    {
      company_name,
      additional_data_requested,
      references_given,
      associated_companies
    }
         │
         ▼
┌────────────────────────────────────────────┐
│  Data Quality Assessment                   │
│  has_sufficient_company_data()             │
│                                            │
│  For each company:                         │
│  1. Search vector store                    │
│  2. Deduplicate documents                  │
│  3. Sample 5 docs → LLM quality check      │
│  4. Calculate quality_score (0-1)          │
│                                            │
│  Decision Logic:                           │
│  • doc_count >= 10 AND quality >= 0.6      │
│    ✓ Use Existing Data (skip scraping)     │
│  • ELSE                                    │
│    → Trigger Web Scraping                  │
└────────┬───────────────────────────────────┘
         │
         ▼
    ┌────┴────┐
    │ Quality │
    │ Check   │
    └────┬────┘
         │
    ┌────┴──────────────────────────┐
    │                               │
    ▼ Sufficient                    ▼ Insufficient
┌────────────────┐          ┌──────────────────────┐
│ Use Existing   │          │  Web Scraping        │
│ Vector Data    │          │  ├─ DuckDuckGo       │
│                │          │  ├─ Website Scrape   │
│ Skip scraping  │          │  └─ Cache Results    │
└────────┬───────┘          └───────────┬──────────┘
         │                              │
         │                              ▼
         │                  ┌───────────────────────┐
         │                  │ Add to Vector Store   │
         │                  │ with metadata         │
         │                  └───────────┬───────────┘
         │                              │
         └──────────┬───────────────────┘
                    ▼
┌────────────────────────────────────────┐
│  Vector Store (Pinecone)               │
│  + Enhanced Company Data               │
│  + User Context & References           │
│  + Knowledge Graph Relationships       │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│         AGENT SELECTION & EXECUTION            │
│                                                │
│  Determine agents_to_run:                      │
│  • Full report: All 8 agents                   │
│  • Specific query: Selected agents only        │
│  • Regeneration: User-selected agents          │
│  • Additional data: AdditionalDataRequest only │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│         PARALLEL AGENT EXECUTION               │
│  ThreadPoolExecutor (max_workers=8)            │
│                                                │
│  Core Analysis Agents (run in parallel):       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Overview │  │ Product  │  │  Goals   │      │
│  │  Agent   │  │   Fit    │  │  Agent   │      │
│  └──────────┘  └──────────┘  └──────────┘      │
│                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │   Dept   │  │ Synergy  │  │ Pricing  │      │
│  │ Mapping  │  │  Agent   │  │  Agent   │      │
│  └──────────┘  └──────────┘  └──────────┘      │
│                                                │
│  ┌──────────┐                                  │
│  │   ROI    │                                  │
│  │  Agent   │                                  │
│  └──────────┘                                  │
│                                                │
│  Special Agent (conditional):                  │
│  ┌────────────────────────────────────┐        │
│  │ AdditionalDataRequest Agent        │        │
│  │ • Answers follow-up questions      │        │
│  │ • Handles specific data requests   │        │
│  │ • Searches existing vector store   │        │
│  │ • If insufficient → Web search     │        │
│  │ • Enhances vector store if needed  │        │
│  └────────────────────────────────────┘        │
│                                                │
│  All agents access:                            │
│  • Pinecone Vector Store (shared context)      │
│  • User-provided references                    │
│  • Associated company data                     │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────┐
│  Results Aggregation   │
│  as_completed()        │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  Dashboard Generation  │
│  ├─ JSON Format        │
│  └─ HTML Format        │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│  SocketIO Response     │
│  research_complete     │
└────────────────────────┘
```

## Data Flow with Multi-Company Analysis

```
User Prompt: "Compare Microsoft with Google on cloud strategies"
         │
         ▼
┌────────────────────────────────────────┐
│  Gemini Extracts:                      │
│  • Primary: Microsoft                  │
│  • Associated: [Google]                │
│  • Additional: Cloud strategies        │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Parallel Data Gathering:              │
│  ├─ Microsoft (search + scrape)        │
│  └─ Google (search + scrape)           │
└────────┬───────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  Pinecone Vector Store:                 │
│                                         │
│  [Microsoft]                            │
│      ├─ Business model docs             │
│      ├─ Cloud strategy docs             │
│      └─ Related to: Google              │
│                                         │
│  [Google]                               │
│      ├─ Business model docs             │
│      ├─ Cloud strategy docs             │
│      └─ Related to: Microsoft           │
│                                         │
│  [Context]                              │
│      └─ "Focus on cloud strategies"     │
└────────┬────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Each Agent Receives:                  │
│  • Microsoft primary data              │
│  • Google comparison data              │
│  • "Cloud strategies" focus context    │
│  • Knowledge graph relationships       │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Agent Outputs Include:                │
│  • Microsoft analysis                  │
│  • Comparison with Google              │
│  • Cloud strategy insights             │ 
│  • Competitive positioning             │
└────────────────────────────────────────┘
```

## Component Interactions

```
┌──────────────────────────────────────────────────────────┐
│                    Flask App (app.py)                    │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │  handle_research_company()                        │   │
│  │  1. Process prompt with Gemini                    │   │
│  │  2. Gather data for all companies                 │   │
│  │  3. Trigger parallel agents                       │   │
│  │  4. Stream progress updates                       │   │
│  │  5. Return results                                │   │
│  └──────────────┬────────────────────────────────────┘   │
└─────────────────┼────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│          DeepAgent Orchestrator (deep_agent.py)         │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  process_prompt()                                │   │
│  │  └─► Gemini LLM ─► Extract structured JSON       │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  gather_company_data()                           │   │
│  │  └─► DuckDuckGo Search ─► Scraper ─► Pinecone    │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  generate_account_plan(parallel=True)            │   │
│  │  └─► ThreadPoolExecutor ─► Selected agents in || │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────────────────┐
│              Specialized Agents (sub_agents.py)          │
│                                                          │
│  Each agent:                                             │
│  • Retrieves context from Pinecone                       │
│  • Uses Gemini for analysis                              │
│  • Returns specialized insights                          │
│                                                          │
│  Agents run CONCURRENTLY via ThreadPoolExecutor          │
└─────────────────┬────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│         Supporting Services (External/Storage)          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ Pinecone │  │  Gemini  │  │  DDGS    │               │
│  │  Vector  │  │   LLM    │  │  Search  │               │
│  │  Store   │  │          │  │          │               │
│  └──────────┘  └──────────┘  └──────────┘               │
└─────────────────────────────────────────────────────────┘
```

## Threading Model with Progress Updates using Sockets

```
Main Thread (Flask-SocketIO)
    │
    └─► handle_research_company()
            │
            ├─► Emit: progress_update (prompt_processing)
            │
            ├─► process_prompt() [Main Thread]
            │
            ├─► Emit: progress_update (data_gathering)
            │
            ├─► gather_company_data() [Main Thread]
            │
            ├─► Emit: progress_update (agents_starting)
            │
            └─► ThreadPoolExecutor.submit() [Creates Worker Threads]
                    │
                    ├─► Worker Thread 1: Overview Agent
                    ├─► Worker Thread 2: Product Fit Agent
                    ├─► Worker Thread 3: Goals Agent
                    ├─► Worker Thread 4: Dept Mapping Agent
                    └─► Worker Thread 5: Synergy Agent
                            │
                            │ (Each thread independently)
                            ├─► Query Pinecone
                            ├─► Call Gemini API
                            ├─► Process results
                            └─► Return to main thread
                                    │
                                    ▼
                    as_completed() collects results
                            │
                            ▼
                    Emit: progress_update (per agent)
                            │
                            ▼
                    Emit: research_complete
```


## Selective Agent Regeneration Flow

```
User Request: "Update the pricing and ROI sections"
         │
         ▼
┌────────────────────────────────────────┐
│  Parse Regeneration Request            │
│  • Identify agents to re-run           │
│  • Keep existing results for others    │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Agent Selection:                      │
│  agents_to_run = ['pricing', 'roi']    │
│                                        │
│  Skip: overview, product_fit, goals,   │
│        dept_mapping, synergy           │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Parallel Execution (2 agents only)    │
│  ┌──────────┐  ┌──────────┐            │
│  │ Pricing  │  │   ROI    │            │
│  │  Agent   │  │  Agent   │            │
│  └──────────┘  └──────────┘            │
└────────┬───────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│  Merge Results:                        │
│  • Keep old: overview, product_fit...  │
│  • Update: pricing, roi                │
│  • Generate updated report             │
└────────────────────────────────────────┘

Benefits:
• Faster updates (only re-run needed agents)
• Token/cost savings
• Preserves quality of unchanged sections
```

## AdditionalDataRequest Agent Detailed Flow

```
User: "What's their employee retention rate?"
         │
         ▼
┌────────────────────────────────────────────────┐
│  AdditionalDataRequest Agent Invoked           │
│  Input:                                        │
│  • company_name: "Microsoft"                   │
│  • additional_data_requested: "employee        │
│    retention rate"                             │
│  • references: [user context]                  │
│  • associated_companies: [comparison targets]  │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│  STEP 1: Search Existing Vector Store          │
│  Query: "Microsoft employee retention rate"    │
│                                                │
│  ┌──────────────────────────────────────┐      │
│  │ Pinecone Retriever Tool              │      │
│  │ • Semantic search                    │      │
│  │ • Filter by company_name             │      │
│  │ • Return top 5 docs                  │      │
│  └──────────────────────────────────────┘      │
└────────┬───────────────────────────────────────┘
         │
         ▼
    ┌────┴────┐
    │ Quality │
    │ Check   │
    └────┬────┘
         │
    ┌────┴───────────────────────┐
    │                            │
    ▼ Sufficient                 ▼ Insufficient
┌────────────────┐      ┌──────────────────────────┐
│ STEP 2A:       │      │ STEP 2B:                 │
│ Answer from    │      │ Web Search Enhancement   │
│ Existing Data  │      │                          │
│                │      │ ┌────────────────────┐   │
│ • Extract info │      │ │ DuckDuckGo Search  │   │
│ • Synthesize   │      │ │ Query: "Microsoft  │   │
│   with LLM     │      │ │ employee retention │   │
│ • Return answer│      │ │ rate statistics"   │   │
│                │      │ └─────────┬──────────┘   │
└────────┬───────┘      │           │              │
         │              │           ▼              │
         │              │ ┌────────────────────┐   │
         │              │ │ Scrape Results     │   │
         │              │ │ • Filter relevant  │   │
         │              │ │ • Extract data     │   │
         │              │ └─────────┬──────────┘   │
         │              │           │              │
         │              │           ▼              │
         │              │ ┌────────────────────┐   │
         │              │ │ Add to Vector      │   │
         │              │ │ Store (enhance)    │   │
         │              │ └─────────┬──────────┘   │
         │              │           │              │
         │              │           ▼              │
         │              │ ┌────────────────────┐   │
         │              │ │ Generate Answer    │   │
         │              │ │ with new data      │   │
         │              │ └─────────┬──────────┘   │
         │              └───────────┼──────────────┘
         │                          │
         └──────────┬───────────────┘
                    ▼
┌────────────────────────────────────────┐
│  STEP 3: Return Comprehensive Answer   │
│  • Direct answer to user's question    │
│  • Source citations                    │
│  • Note if data was enhanced           │
└────────────────────────────────────────┘

Key Features:
• Intelligent data sufficiency assessment
• Automatic vector store enhancement
• Seamless fallback to web search
• Preserves data for future queries
```

## Data Quality Assessment Algorithm

```
┌────────────────────────────────────────────────┐
│  has_sufficient_company_data(company_name)     │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│  Search Vector Store                           │
│  • Query: "[company] overview", "products",    │
│          "business model"                      │
│  • Filter: company_name                        │
│  • Collect all matching documents              │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│  Deduplicate Documents                         │
│  • Hash first 200 chars of content             │
│  • Remove duplicate hashes                     │
│  • Count unique documents                      │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│  Quality Assessment (LLM-based)                │
│  • Sample up to 5 documents                    │
│  • For each doc, ask Gemini:                   │
│    "Does this contain meaningful business      │
│     information about [company]?"              │
│  • Responses: TRUE or FALSE                    │
│  • Calculate: quality_score = (TRUE_count /    │
│                                total_sampled)  │
└────────┬───────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────┐
│  Decision Matrix                               │
│                                                │
│  IF doc_count >= 10 AND quality_score >= 0.6:  │
│    ✓ has_data = True                           │
│    ✓ should_scrape = False                     │
│    → Use existing data                         │
│                                                │
│  ELSE:                                         │
│    ✗ has_data = False                          │
│    ✗ should_scrape = True                      │
│    → Trigger web scraping                      │
│                                                │
│  Return: {has_data, doc_count, quality_score,  │
│          should_scrape}                        │
└────────────────────────────────────────────────┘

Quality Criteria (LLM evaluates):
✓ Meaningful: Specific products, services, financials, news
✗ Low Quality: "Under construction", generic text, errors
```
