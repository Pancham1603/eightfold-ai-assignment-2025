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
