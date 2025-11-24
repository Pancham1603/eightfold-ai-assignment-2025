"""
Flask application for Company Research Assistant with Multi-Agent Dashboard
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import logging
import json
import asyncio
from datetime import datetime
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI

from config.settings import config
from src.vector_store.pinecone_store import vector_store
from src.agents.deep_agent import main_agent, dashboard
from src.ingestion.document_processor import DocumentProcessor
from src.agents.sub_agents import AdditionalDataRequestAgent, PineconeRetrieverTool
from src.utils.mongodb import initialize_mongodb, get_mongo_manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Multi-key management for Gemini API (session-based)
def get_chat_llm(key_index: int = 0):
    """Get ChatGoogleGenerativeAI instance with specified API key index"""
    if not config.GOOGLE_API_KEYS:
        logger.error("No Google API keys configured")
        raise ValueError("No Google API keys available")
    
    api_key = config.GOOGLE_API_KEYS[key_index % len(config.GOOGLE_API_KEYS)]
    return ChatGoogleGenerativeAI(
        model=config.GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0.7
    )

def invoke_with_fallback(prompt: str, session_id: str, max_retries: int = None) -> str:
    """Invoke Gemini with automatic key fallback on errors (session-aware)"""
    if session_id not in active_sessions:
        active_sessions[session_id] = {'api_key_index': 0}
    
    session = active_sessions[session_id]
    if 'api_key_index' not in session:
        session['api_key_index'] = 0
    
    if max_retries is None:
        max_retries = len(config.GOOGLE_API_KEYS)
    
    current_key_index = session['api_key_index']
    last_error = None
    
    for attempt in range(max_retries):
        try:
            llm = get_chat_llm(current_key_index)
            response = llm.invoke(prompt)
            # Success! Keep this key for this session
            session['api_key_index'] = current_key_index
            logger.info(f"Session {session_id[:8]} using API key {current_key_index + 1}")
            return response.content.strip()
        except Exception as e:
            last_error = e
            logger.warning(f"Session {session_id[:8]}: API key {current_key_index + 1} failed: {e}")
            current_key_index = (current_key_index + 1) % len(config.GOOGLE_API_KEYS)
            logger.info(f"Session {session_id[:8]}: Switching to API key {current_key_index + 1}")
            
            if attempt < max_retries - 1:
                continue
    
    logger.error(f"Session {session_id[:8]}: All API keys exhausted. Last error: {last_error}")
    raise last_error

# Initialize with first key for non-session usage
chat_llm = get_chat_llm()

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Initialize MongoDB connection
logger.info(f"Initializing MongoDB: {config.MONGO_DB_URI}")
if not initialize_mongodb(config.MONGO_DB_URI, config.MONGO_DB_NAME):
    logger.warning("⚠️ MongoDB connection failed - chat persistence disabled")

# Create separate namespace for progress updates to avoid interference with chat
progress_namespace = '/progress'

# Enhanced session tracking
active_sessions = {}
# Session structure: {
#   'session_id': {
#       'company_name': str,
#       'status': str,  # 'idle', 'researching', 'complete'
#       'research_done': bool,
#       'research_results': dict,  # Full account plan data
#       'associated_companies': list,
#       'current_agent': str,
#       'conversation_history': list,  # Chain of Thought: [{'role': 'user'/'assistant', 'content': str, 'timestamp': str}]
#       'api_key_index': int  # Last successful Gemini API key index for this session
#       'sources_used': {  # Track all sources used in research
#           'pinecone_eightfold': [],  # Eightfold AI vector documents
#           'pinecone_target': [],  # Target company vector documents
#           'web_scraped': []  # Web links scraped
#       }
#   }
# }


def preprocess_eightfold_references(message: str) -> str:
    """
    Convert first-person pronouns (we, our, my, I) to 'Eightfold AI' references.
    This helps the system understand that users are referring to Eightfold AI.
    
    Examples:
    - "How do our tools benefit company X" -> "How do Eightfold AI's tools benefit company X"
    - "Can we help them" -> "Can Eightfold AI help them"
    - "What's my value proposition" -> "What's Eightfold AI's value proposition"
    """
    import re
    
    # Patterns to detect Eightfold AI context (talking about products/services/business)
    eightfold_context_keywords = [
        'tools', 'platform', 'solution', 'product', 'service', 'technology',
        'benefit', 'help', 'value', 'offer', 'provide', 'capabilities',
        'talent', 'hiring', 'recruitment', 'AI', 'workforce', 'employee'
    ]
    
    # Check if message contains business/product context
    has_business_context = any(keyword in message.lower() for keyword in eightfold_context_keywords)
    
    if has_business_context:
        # Replace pronouns with Eightfold AI
        # "our/Our" -> "Eightfold AI's"
        message = re.sub(r'\bOur\b', "Eightfold AI's", message)
        message = re.sub(r'\bour\b', "Eightfold AI's", message)
        
        # "we/We" -> "Eightfold AI"
        message = re.sub(r'\bWe\b', "Eightfold AI", message)
        message = re.sub(r'\bwe\b', "Eightfold AI", message)
        
        # "my/My" -> "Eightfold AI's"
        message = re.sub(r'\bMy\b', "Eightfold AI's", message)
        message = re.sub(r'\bmy\b', "Eightfold AI's", message)
        
        # "I" in business context -> "Eightfold AI" (careful with this one)
        message = re.sub(r'\bI offer\b', "Eightfold AI offers", message, flags=re.IGNORECASE)
        message = re.sub(r'\bI provide\b', "Eightfold AI provides", message, flags=re.IGNORECASE)
        message = re.sub(r'\bI have\b', "Eightfold AI has", message, flags=re.IGNORECASE)
        
    return message


def classify_user_message(message: str, session_data: dict, session_id: str) -> dict:
    """
    Classify user message into: casual, research_request, or follow_up
    Uses Chain of Thought: considers conversation history for context
    
    Args:
        message: User's message to classify
        session_data: Session data with conversation history
        session_id: Session identifier for key management
    
    Returns:
        {
            'type': 'casual' | 'research_request' | 'follow_up',
            'confidence': float,
            'reasoning': str,
            'processed_message': str  # Message with Eightfold AI references processed
        }
    """
    research_done = session_data.get('research_done', False)
    company_name = session_data.get('company_name', '')
    conversation_history = session_data.get('conversation_history', [])
    
    # Preprocess Eightfold AI references
    processed_message = preprocess_eightfold_references(message)
    
    # Build conversation context (last 5 exchanges for efficiency)
    recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
    history_text = ""
    if recent_history:
        history_text = "\n\nRecent Conversation:\n"
        for msg in recent_history:
            role = "User" if msg['role'] == 'user' else "Assistant"
            history_text += f"{role}: {msg['content'][:100]}...\n"
    
    classification_prompt = f"""
You are a message classifier for a sales intelligence assistant representing Eightfold AI.

Current Session State:
- Research completed: {research_done}
- Company researched: {company_name if company_name else 'None'}
{history_text}
Original User Message: "{message}"
Processed Message: "{processed_message}"

Classify this message into ONE of these categories:

1. **casual**: Greetings, small talk, general questions about capabilities, confused users asking for help, edge cases (personal info requests, inappropriate queries)
2. **research_request**: Clear instruction to research/analyze a company ("research Apple", "how do Eightfold AI's tools benefit company X", "I need info on Tesla", etc.)
3. **follow_up**: Questions about previously researched company - ONLY if research_done=True ("tell me more", "what's their pricing", etc.)

USER TYPE DETECTION (for casual messages):
- **Confused User**: Vague requests, uncertainty ("I need help with a company but not sure what", "umm...", "I think...")
- **Efficient User**: Direct, concise, specific instructions ("Research X. Focus on Y. Keep it short.")
- **Chatty User**: Long messages with tangents, personal anecdotes, multiple topics in one message
- **Edge Case User**: Requesting personal info (CTO's pets, favorite food), confidential data (exact runway, private financials), or completely off-topic

CLASSIFICATION RULES:
- USE CONVERSATION HISTORY to understand context and references
- MULTI-TURN CONFUSED USER: If assistant just asked for clarification and user provides more details (even vague), classify as 'casual' so assistant can continue helping
- If user says "tell me more" and we just researched a company, it's a 'follow_up'
- Confused/vague company mentions (partial names, uncertain) → 'casual' (agent will guide them)
- User providing additional clues after being asked (industry, logo, features) → 'casual' (agent will acknowledge and help)
- Clear company name with research intent → 'research_request'
- Personal info or inappropriate requests → 'casual' (agent will politely decline)
- Off-topic or out-of-scope → 'casual' (agent will redirect)
- research_done=True + question about that company → 'follow_up'
- Pronouns "we/our/my" refer to Eightfold AI (already converted in processed message)

SPECIAL CASE - Incremental Company Discovery:
If conversation shows user is gradually describing a company they can't quite remember:
- User: "I need help with a company" → 'casual'
- User: "it's something like yamdocs" → 'casual' (not enough to research)
- User: "logo had letter A" → 'casual' (still gathering info)
- User: "I think it's Adobe" → 'research_request' (now we have a name!)

Respond in JSON format:
{{
    "type": "casual|research_request|follow_up",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation (mention user type if casual: confused/efficient/chatty/edge_case)"
}}
"""
    
    try:
        result_text = invoke_with_fallback(classification_prompt, session_id)
        
        # Extract JSON from response
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0].strip()
        
        classification = json.loads(result_text)
        classification['processed_message'] = processed_message  # Include processed message
        logger.info(f"Message classified as: {classification['type']} (confidence: {classification['confidence']})")
        if processed_message != message:
            logger.info(f"Processed message: {processed_message}")
        return classification
        
    except Exception as e:
        logger.error(f"Error classifying message: {e}")
        # Fallback: simple keyword-based classification
        message_lower = message.lower()
        
        casual_keywords = ['hi', 'hello', 'hey', 'how are you', 'what can you do', 'help', 'thanks', 'thank you']
        research_keywords = ['research', 'analyze', 'tell me about', 'information on', 'look up', 'find out about']
        
        if any(keyword in message_lower for keyword in casual_keywords):
            return {'type': 'casual', 'confidence': 0.7, 'reasoning': 'Keyword match (fallback)'}
        elif research_done and len(message.split()) < 15:  # Short questions after research
            return {'type': 'follow_up', 'confidence': 0.6, 'reasoning': 'Short question after research (fallback)'}
        elif any(keyword in message_lower for keyword in research_keywords):
            return {'type': 'research_request', 'confidence': 0.7, 'reasoning': 'Keyword match (fallback)'}
        else:
            return {'type': 'research_request', 'confidence': 0.5, 'reasoning': 'Default (fallback)'}


def handle_chat(message: str, session_id: str, conversation_history: list = None) -> str:
    """
    Handle casual conversation without accessing vector store or web search.
    Adapts to different user types: confused, efficient, chatty, and edge cases.
    Uses Chain of Thought: maintains conversation context.
    
    Args:
        message: Current user message
        session_id: Session identifier for key management
        conversation_history: List of previous messages for context
    """
    if conversation_history is None:
        conversation_history = []
    
    # Build conversation context (last 5 exchanges)
    recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
    history_text = ""
    if recent_history:
        history_text = "\n\nConversation Context:\n"
        for msg in recent_history:
            role = "User" if msg['role'] == 'user' else "You"
            history_text += f"{role}: {msg['content'][:150]}\n"
        history_text += "\n"
    
    # Debug logging
    logger.info(f"handle_chat called with {len(conversation_history)} history messages")
    if recent_history:
        logger.info(f"Recent history preview: {history_text[:200]}...")
    
    casual_prompt = f"""
You are a professional Sales Intelligence Assistant designed specifically to research companies and generate account plans for Eightfold AI.
{history_text}
Current User message: {message}

SCOPE OF ASSISTANCE:
Your ONLY purpose is to help with:
- Researching companies (business model, products, pricing, industry)
- Generating account plans for sales teams
- Analyzing business value propositions and ROI
- Finding information about specific companies
- Answering questions about research results

MESSAGE TYPE DETECTION:

**GIBBERISH/UNCLEAR** - Random characters, typos, incomprehensible text:
- Respond: "That seems a bit unclear. Could you please clarify what you're requesting?"
- NEVER ask "What's the company name?" for gibberish
- Examples: "fx gmgbtvfytunmt", "asdfghjkl", "mmmm"

**GREETINGS** - Hi, hello, hey, good morning, etc:
- Respond warmly and briefly: "Hello! Which company would you like me to research?"
- MATCH their energy: "Hi!" for "hi", "Hello!" for "hello"
- Keep it under 12 words total
- Examples: 
  * "hi" → "Hi! Which company would you like me to research?"
  * "hello there" → "Hello! What company can I help you with?"

USER TYPE HANDLING:

1. **The Confused User** (unsure what they want):
   - KEEP IT BRIEF: 1-2 sentences max
   - Ask ONE specific clarifying question at a time
   - Don't repeat what they already told you
   - Don't explain what you can do unless they ask
   - Example: "What's the company name?" NOT "I'd be happy to help! What's the company name? Are you looking for..."

2. **The Efficient User** (wants quick results):
   - ULTRA BRIEF: Acknowledge and act
   - No explanations unless needed
   - Example: "Researching [company] now." NOT "Got it. I'll research [company] and focus on..."

3. **The Chatty User** (goes off-topic):
   - Match their warmth but stay brief
   - Quick acknowledgment + redirect
   - Example: "That's fun! What company can I research?" NOT long explanations

4. **The Edge Case User** (inappropriate/out-of-scope requests):
   - Politely decline in ONE sentence
   - Offer alternative in ONE sentence
   - Example: "I can't access personal info. I can analyze their business strategy instead?"

RESPONSE RULES:
1. **BE EXTREMELY CONCISE** - Maximum 1-2 sentences per response
2. **NO REPETITION** - Don't repeat information user already provided
3. **ONE QUESTION AT A TIME** - Ask only what you need to know next
4. **GIBBERISH DETECTION** - If message is random characters/incomprehensible, ask for clarification, don't ask for company name
5. **GREETING DETECTION** - If message is a greeting, greet back warmly + ask which company
6. If the message is relevant to company research:
   - USE CONVERSATION HISTORY to avoid asking for info they already gave
   - If you just asked a clarifying question, acknowledge their answer briefly and ask next question OR start research
   - For confused users: 
     * First message: "What's the company name?"
     * If they give partial info: Acknowledge briefly, ask for best guess: "Got it. Your best guess at the name?"
     * If they keep giving clues instead of a name: CHANGE YOUR APPROACH - try suggestions: "Is it Adobe?" or "Sounds like Adobe?"
     * NEVER repeat the same question twice - if they didn't give a name, either suggest possibilities or accept you need more info
     * If they provide a name: Start research immediately, no extra explanation
   - For efficient users: Single sentence acknowledgment, start research
   - For chatty users: Brief warm acknowledgment (5 words max), ask question

7. HANDLING VAGUE COMPANY NAMES:
   - First time: Ask for best guess: "Your best guess at the name?"
   - Second time (if they give more clues but no name): Make suggestions based on clues: "Sounds like Adobe? Or another company?"
   - NEVER ask the same question twice in a row
   - Example conversation:
     * User: "company at BPM conference, docs management"
     * You: "Your best guess at the name?"
     * User: "big company, logo has letter A"
     * You: "Adobe? Or thinking of a different one?" (NOT "Your best guess at the name?" again)

8. INAPPROPRIATE requests:
   - ONE sentence decline + ONE sentence alternative
   - Example: "I can't access personal info. Want their business strategy instead?"

9. OFF-TOPIC:
   - ONE sentence: "I only do company research. Which company?"

10. **CRITICAL: Keep ALL responses under 20 words unless providing research results**

Provide your response:
"""
    
    try:
        response_text = invoke_with_fallback(casual_prompt, session_id)
        return response_text
    except Exception as e:
        logger.error(f"Error in casual chat: {e}")
        return "Hello! I'm your Sales Intelligence Assistant for Eightfold AI. I can help you research companies and generate comprehensive account plans. What company would you like me to analyze?"


def handle_follow_up_question(message: str, session_data: dict, session_id: str) -> dict:
    """
    Handle follow-up questions using cached research data or AdditionalDataRequestAgent.
    Uses Chain of Thought: considers conversation history for better context understanding.
    
    Args:
        message: User's follow-up question
        session_data: Session data containing research results
        session_id: Session identifier for key management
    
    Returns:
        {
            'answer': str,
            'source': 'cached' | 'additional_agent',
            'confidence': float
        }
    """
    research_results = session_data.get('research_results', {})
    company_name = session_data.get('company_name', '')
    conversation_history = session_data.get('conversation_history', [])
    
    if not research_results:
        return {
            'answer': "I don't have any research data cached. Please start a new research session first.",
            'source': 'error',
            'confidence': 0.0
        }
    
    # Build conversation context
    recent_history = conversation_history[-10:] if len(conversation_history) > 10 else conversation_history
    history_text = ""
    if recent_history:
        history_text = "\n\nRecent Conversation:\n"
        for msg in recent_history:
            role = "User" if msg['role'] == 'user' else "Assistant"
            history_text += f"{role}: {msg['content'][:100]}...\n"
    
    # Step 1: Try to answer from cached data
    search_prompt = f"""
You are analyzing a follow-up question about {company_name} for Eightfold AI sales intelligence.

Available Research Data:
- Company Overview: {research_results.get('company_overview', '')[:500]}...
- Product Fit: {research_results.get('product_fit', '')[:500]}...
- Long-term Goals: {research_results.get('long_term_goals', '')[:500]}...
- Department Mapping: {research_results.get('dept_mapping', '')[:500]}...
- Synergy Opportunities: {research_results.get('synergy_opportunities', '')[:500]}...
- Pricing: {research_results.get('pricing_recommendation', '')[:500]}...
- ROI: {research_results.get('roi_forecast', '')[:500]}...
{history_text}
Current User Question: {message}

USER TYPE HANDLING:
- **Efficient User** (direct questions): Provide concise, focused answers
- **Chatty User** (conversational tone): Match their warmth while staying professional
- **Edge Case** (inappropriate/out-of-scope): Politely decline and offer alternatives

EDGE CASE DETECTION:
If the question asks for:
- Personal employee information (pets, hobbies, private life) → Cannot answer, offer business alternatives
- Confidential financials (exact funding runway, undisclosed metrics) → Explain limitations, offer what IS available (funding trends, headcount growth)
- Completely unrelated topics → Redirect to research scope

CRITICAL DECISION LOGIC:
1. USE CONVERSATION HISTORY to understand context (e.g., "what about their competitors?" refers to previously discussed company)
2. Check if question is appropriate and within scope
3. If inappropriate/out-of-scope: Set can_answer=false, provide polite decline + alternatives
4. If appropriate BUT cached data is INCOMPLETE or MISSING specific information needed:
   - Set can_answer=true
   - Set answer="NEED_ADDITIONAL_DATA"
   - This will trigger web scraping to find the answer
5. If can answer FULLY from cached data: Provide comprehensive answer

**WHEN TO USE "NEED_ADDITIONAL_DATA":**
- Question asks for SPECIFIC information (CEO name, recruitment status, specific metrics)
- Cached data doesn't contain this SPECIFIC information
- Question is WITHIN SCOPE (not personal/confidential/off-topic)
- Example: "Is this company recruiting in colleges?" → If no recruitment data in cache → "NEED_ADDITIONAL_DATA"
- Example: "What is the name of the CEO?" → If no CEO name in cache → "NEED_ADDITIONAL_DATA"
- Example: "What are their main products?" → If products mentioned in cache → Answer from cache

**DO NOT:**
- Say "I don't have access to real-time information" - instead use "NEED_ADDITIONAL_DATA"
- Give up if data is missing - request additional data scraping
- Apologize for lack of data - just trigger the additional data agent

Task:
Search the cached research data and conversation history. If the answer exists, provide it. If the specific data point is missing but the question is valid, return "NEED_ADDITIONAL_DATA" to trigger web scraping.

Respond in JSON format:
{{
    "can_answer": true/false,
    "answer": "your answer or NEED_ADDITIONAL_DATA",
    "confidence": 0.0-1.0
}}
"""
    
    try:
        result_text = invoke_with_fallback(search_prompt, session_id)
        
        # Extract JSON
        if '```json' in result_text:
            result_text = result_text.split('```json')[1].split('```')[0].strip()
        elif '```' in result_text:
            result_text = result_text.split('```')[1].split('```')[0].strip()
        
        result = json.loads(result_text)
        
        if result['can_answer'] and result['answer'] != 'NEED_ADDITIONAL_DATA':
            logger.info(f"Answered follow-up from cached data (confidence: {result['confidence']})")
            return {
                'answer': result['answer'],
                'source': 'cached',
                'confidence': result['confidence']
            }
    
    except Exception as e:
        logger.error(f"Error searching cached data: {e}")
    
    # Step 2: Use AdditionalDataRequestAgent for new data
    logger.info(f"Running AdditionalDataRequestAgent for follow-up question: {message[:50]}...")
    
    try:
        from src.tools.web_scraper import search_tool
        
        llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.7
        )
        
        # Create PineconeRetrieverTool
        retriever_tool = PineconeRetrieverTool(vector_store).get_tool()
        
        # Create agent instance
        additional_agent = AdditionalDataRequestAgent(
            llm=llm,
            retriever_tool=retriever_tool
        )
        
        # Run analysis with web scraping
        logger.info("Invoking AdditionalDataRequestAgent with web scraping...")
        agent_result = additional_agent.analyze(
            company_name=company_name,
            additional_request=message,  # The follow-up question
            references='',
            associated_companies=session_data.get('associated_companies', [])
        )
        
        return {
            'answer': agent_result,
            'source': 'additional_agent',
            'confidence': 0.8
        }
        
    except Exception as e:
        logger.error(f"Error running AdditionalDataRequestAgent: {e}")
        return {
            'answer': f"I encountered an error while gathering additional data: {str(e)}",
            'source': 'error',
            'confidence': 0.0
        }


@app.route('/')
def index():
    """Main page - also cleans up stale 'New Chat' sessions"""
    try:
        # Cleanup stale "New Chat" sessions on page load
        mongo = get_mongo_manager()
        if mongo:
            deleted_count = mongo.cleanup_stale_new_chats()
            if deleted_count > 0:
                logger.info(f"🧹 Cleaned up {deleted_count} stale chat(s) on page load")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
    
    return render_template('index.html')

@app.route('/api/companies', methods=['GET'])
def list_companies():
    """List all companies in the knowledge graph"""
    try:
        companies = vector_store.list_companies()
        return jsonify({
            'success': True,
            'companies': companies,
            'count': len(companies)
        })
    except Exception as e:
        logger.error(f"Error listing companies: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/account-plans', methods=['GET'])
def list_account_plans():
    """List all generated account plans"""
    try:
        plans_dir = Path(config.ACCOUNT_PLANS_FOLDER)
        plans_dir.mkdir(parents=True, exist_ok=True)
        
        plans = []
        for json_file in plans_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
                    plans.append({
                        'company_name': plan_data.get('company_name'),
                        'timestamp': plan_data.get('timestamp'),
                        'filename': json_file.stem
                    })
            except Exception as e:
                logger.error(f"Error reading {json_file}: {e}")
        
        plans.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return jsonify({
            'success': True,
            'plans': plans,
            'count': len(plans)
        })
    except Exception as e:
        logger.error(f"Error listing account plans: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/account-plan/<company_name>', methods=['GET'])
def get_account_plan(company_name):
    """Get account plan for a specific company"""
    try:
        plans_dir = Path(config.ACCOUNT_PLANS_FOLDER)
        safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in company_name)
        safe_name = safe_name.replace(' ', '_')
        
        json_file = plans_dir / f"{safe_name}.json"
        
        if not json_file.exists():
            return jsonify({
                'success': False,
                'error': f'No account plan found for {company_name}'
            }), 404
        
        with open(json_file, 'r', encoding='utf-8') as f:
            plan_data = json.load(f)
        
        return jsonify({
            'success': True,
            'plan': plan_data
        })
    except Exception as e:
        logger.error(f"Error getting account plan: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/ingest-documents', methods=['POST'])
def ingest_documents():
    """Ingest Eightfold AI reference documents"""
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', config.EIGHTFOLD_DOCS_FOLDER)
        
        processor = DocumentProcessor(
            vector_store=vector_store,
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )
        
        stats = processor.process_folder(
            folder_path=folder_path,
            document_type="eightfold_reference",
            metadata={'category': 'reference'}
        )
        
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        logger.error(f"Error ingesting documents: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/company/<company_name>', methods=['GET'])
def get_company_data(company_name):
    """Get stored data for a specific company"""
    try:
        context = vector_store.get_company_context(company_name, max_docs=10)
        return jsonify({
            'success': True,
            'company_name': company_name,
            'context': context
        })
    except Exception as e:
        logger.error(f"Error getting company data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/sources/<session_id>', methods=['GET'])
def get_session_sources(session_id):
    """Get sources used in a research session"""
    try:
        if session_id in active_sessions:
            sources = active_sessions[session_id].get('sources_used', {
                'pinecone_eightfold': [],
                'pinecone_target': [],
                'web_scraped': []
            })
            
            # Also get pinecone sources from main_agent if available
            try:
                pinecone_sources = main_agent.get_retrieved_documents()
                sources['pinecone_eightfold'] = pinecone_sources.get('eightfold', [])
                sources['pinecone_target'] = pinecone_sources.get('target', [])
            except:
                pass
            
            return jsonify({
                'success': True,
                'sources': sources
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
    except Exception as e:
        logger.error(f"Error getting sources: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chats', methods=['GET'])
def get_all_chats():
    """Get all chat sessions from MongoDB"""
    try:
        mongo = get_mongo_manager()
        if not mongo:
            return jsonify({
                'success': False,
                'error': 'MongoDB not available'
            }), 503
        
        chats = mongo.get_all_chats(limit=50)
        return jsonify({
            'success': True,
            'chats': chats
        })
    except Exception as e:
        logger.error(f"Error getting chats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chats/<session_id>', methods=['GET'])
def get_chat(session_id):
    """Get a specific chat session by session_id"""
    try:
        mongo = get_mongo_manager()
        if not mongo:
            return jsonify({
                'success': False,
                'error': 'MongoDB not available'
            }), 503
        
        chat = mongo.get_chat_session(session_id)
        if not chat:
            return jsonify({
                'success': False,
                'error': 'Chat not found'
            }), 404
        
        return jsonify({
            'success': True,
            'chat': chat
        })
    except Exception as e:
        logger.error(f"Error getting chat: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chats/new', methods=['POST'])
def create_new_chat():
    """Create a new chat session"""
    try:
        import uuid
        
        mongo = get_mongo_manager()
        if not mongo:
            return jsonify({
                'success': False,
                'error': 'MongoDB not available'
            }), 503
        
        # Generate new session ID
        new_session_id = str(uuid.uuid4())
        
        # Create chat in MongoDB
        chat_id = mongo.create_chat_session(new_session_id, "New Chat")
        
        if not chat_id:
            return jsonify({
                'success': False,
                'error': 'Failed to create chat'
            }), 500
        
        return jsonify({
            'success': True,
            'session_id': new_session_id,
            'chat_id': chat_id
        })
    except Exception as e:
        logger.error(f"Error creating new chat: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/chats/<session_id>', methods=['DELETE'])
def delete_chat(session_id):
    """Delete a chat session"""
    try:
        mongo = get_mongo_manager()
        if not mongo:
            return jsonify({
                'success': False,
                'error': 'MongoDB not available'
            }), 503
        
        success = mongo.delete_chat_session(session_id)
        
        if not success:
            return jsonify({
                'success': False,
                'error': 'Chat not found or failed to delete'
            }), 404
        
        return jsonify({
            'success': True,
            'message': 'Chat deleted successfully'
        })
    except Exception as e:
        logger.error(f"Error deleting chat: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/graph/<company_name>', methods=['GET'])
def get_company_graph(company_name):
    """Get knowledge graph visualization for a company"""
    try:
        from pyvis.network import Network
        import tempfile
        import os
        
        # Get knowledge graph data
        graph_data = vector_store.get_knowledge_graph(company_name)
        
        if not graph_data or not graph_data.get('nodes'):
            return jsonify({
                'success': False,
                'error': f'No knowledge graph found for {company_name}'
            }), 404
        
        # Create pyvis network
        net = Network(
            height="600px",
            width="100%",
            bgcolor="#1a1a1a",
            font_color="#ffffff",
            directed=True
        )
        
        # Add nodes
        for node in graph_data['nodes']:
            node_id = node['id']
            node_type = node.get('type', 'unknown')
            
            # Color by type
            color_map = {
                'ORGANIZATION': '#3b9eff',
                'PERSON': '#ff6b6b',
                'LOCATION': '#4ecdc4',
                'PRODUCT': '#ffe66d',
                'TECHNOLOGY': '#a8dadc',
                'FINANCIAL': '#06ffa5',
                'DATE': '#f1faee',
                'EVENT': '#e63946'
            }
            
            net.add_node(
                node_id,
                label=node_id,
                title=f"Type: {node_type}",
                color=color_map.get(node_type, '#95a5a6'),
                size=25 if node_type == 'ORGANIZATION' else 15
            )
        
        # Add edges
        for edge in graph_data['edges']:
            net.add_edge(
                edge['source'],
                edge['target'],
                title=edge.get('relationship', 'related'),
                arrows='to'
            )
        
        # Set physics options
        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "stabilization": {
              "enabled": true,
              "iterations": 100
            },
            "barnesHut": {
              "gravitationalConstant": -8000,
              "springLength": 150,
              "springConstant": 0.04
            }
          }
        }
        """)
        
        # Generate HTML
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html', encoding='utf-8') as f:
            net.save_graph(f.name)
            f.seek(0)
        
        with open(f.name, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        os.unlink(f.name)
        
        return jsonify({
            'success': True,
            'company_name': company_name,
            'graph_html': html_content,
            'node_count': len(graph_data['nodes']),
            'edge_count': len(graph_data['edges'])
        })
        
    except Exception as e:
        logger.error(f"Error generating graph for {company_name}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/company/<company_name>', methods=['DELETE'])
def delete_company_data(company_name):
    """Delete all data for a specific company"""
    try:
        deleted_count = vector_store.delete_company_data(company_name)
        return jsonify({
            'success': True,
            'company_name': company_name,
            'deleted_count': deleted_count
        })
    except Exception as e:
        logger.error(f"Error deleting company data: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# AGENT SELECTION AND REGENERATION API ENDPOINTS
# ============================================================================

@app.route('/api/research/regenerate', methods=['POST'])
def regenerate_section():
    """Regenerate a specific section with additional context"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        agent_name = data.get('agent_name')
        company_name = data.get('company_name')
        additional_context = data.get('additional_context', '')  # Optional now
        previous_results = data.get('previous_results', {})
        
        if not all([session_id, agent_name, company_name]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: session_id, agent_name, company_name'
            }), 400
        
        # Map frontend agent names to backend agent keys
        agent_map = {
            'overview': 'overview',
            'value': 'product_fit',
            'goals': 'goals',
            'domain': 'dept_mapping',
            'synergy': 'synergy'
        }
        
        agent_key = agent_map.get(agent_name)
        if not agent_key:
            return jsonify({
                'success': False,
                'error': f'Invalid agent name: {agent_name}'
            }), 400
        
        logger.info(f"Regenerating {agent_name} for {company_name} with context: {additional_context[:50]}...")
        
        # Get the specific agent
        agent = main_agent.sub_agents.get(agent_key)
        if not agent:
            return jsonify({
                'success': False,
                'error': f'Agent not found: {agent_key}'
            }), 500
        
        # Prepare enhanced context (only if additional context provided)
        if additional_context and additional_context.strip():
            enhanced_context = f"Additional Requirements: {additional_context}\n\nPrevious Analysis Context: Consider improvements based on user feedback."
        else:
            enhanced_context = ""  # Empty context = fresh regeneration
        
        # Run the specific agent
        result = agent.analyze(company_name, references=enhanced_context)
        
        return jsonify({
            'success': True,
            'agent': agent_name,
            'result': result,
            'message': f'Regenerated {agent_name} analysis with additional context'
        })
    except Exception as e:
        logger.error(f"Error regenerating section: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/research/regenerate-multiple', methods=['POST'])
def regenerate_multiple():
    """Regenerate multiple sections with shared context"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        agents = data.get('agents', [])
        company_name = data.get('company_name')
        additional_context = data.get('additional_context', '')
        previous_results = data.get('previous_results', {})
        
        if not all([session_id, agents, company_name]):
            return jsonify({
                'success': False,
                'error': 'Missing required fields: session_id, agents, company_name'
            }), 400
        
        # Map frontend agent names to backend agent keys
        agent_map = {
            'overview': 'overview',
            'value': 'product_fit',
            'goals': 'goals',
            'domain': 'dept_mapping',
            'synergy': 'synergy'
        }
        
        logger.info(f"Regenerating {len(agents)} agents for {company_name}: {agents}")
        
        # Prepare enhanced context (only if provided)
        if additional_context and additional_context.strip():
            enhanced_context = f"Additional Requirements: {additional_context}\n\nPrevious Analysis Context: Consider improvements based on user feedback."
        else:
            enhanced_context = ""  # Empty context = fresh regeneration
        
        results = {}
        for agent_name in agents:
            agent_key = agent_map.get(agent_name)
            if not agent_key:
                logger.warning(f"Skipping invalid agent: {agent_name}")
                continue
            
            agent = main_agent.sub_agents.get(agent_key)
            if not agent:
                logger.warning(f"Agent not found: {agent_key}")
                continue
            
            try:
                # Run agent with enhanced context
                result = agent.analyze(company_name, references=enhanced_context)
                results[agent_name] = result
                logger.info(f"✓ Regenerated {agent_name}")
            except Exception as e:
                logger.error(f"Error regenerating {agent_name}: {e}")
                results[agent_name] = f"Error: {str(e)}"
        
        return jsonify({
            'success': True,
            'results': results,
            'message': f'Regenerated {len(results)} sections successfully'
        })
    except Exception as e:
        logger.error(f"Error regenerating multiple sections: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def save_message_to_db(session_id: str, role: str, content: str, message_type: str = "text", metadata: dict = None):
    """
    Save a message to MongoDB for the current session
    
    Args:
        session_id: Session identifier
        role: 'user' or 'assistant'
        content: Message content
        message_type: Type of message (text, research_acknowledgment, etc.)
        metadata: Additional metadata
    """
    mongo = get_mongo_manager()
    if not mongo:
        return
    
    try:
        mongo.add_message(session_id, role, content, message_type, metadata)
    except Exception as e:
        logger.error(f"Failed to save message to MongoDB: {e}")


def update_chat_company_name(session_id: str, company_name: str):
    """
    Update company name for a chat session in MongoDB
    
    Args:
        session_id: Session identifier
        company_name: Company name to set
    """
    mongo = get_mongo_manager()
    if not mongo:
        return
    
    try:
        mongo.update_company_name(session_id, company_name)
        logger.info(f"Updated chat company name to: {company_name}")
    except Exception as e:
        logger.error(f"Failed to update chat company name: {e}")


def save_research_to_db(session_id: str, research_results: dict):
    """
    Save research results to MongoDB for the current session
    
    Args:
        session_id: Session identifier
        research_results: Complete research data
    """
    mongo = get_mongo_manager()
    if not mongo:
        return
    
    try:
        mongo.save_research_results(session_id, research_results)
        logger.info(f"Saved research results to MongoDB for session {session_id}")
    except Exception as e:
        logger.error(f"Failed to save research results to MongoDB: {e}")


# ============================================================================
# WEBSOCKET HANDLERS
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    
    # Initialize session with Chain of Thought conversation history
    active_sessions[request.sid] = {
        'company_name': '',
        'status': 'idle',
        'research_done': False,
        'research_results': {},
        'associated_companies': [],
        'current_agent': None,
        'conversation_history': [],
        'progress_sid': None,
        'current_chat_id': None,  # MongoDB document ID for current chat
        'sources_used': {
            'pinecone_eightfold': [],
            'pinecone_target': [],
            'web_scraped': []
        }
    }
    
    # Create new chat session in MongoDB
    mongo = get_mongo_manager()
    if mongo:
        chat_id = mongo.create_chat_session(request.sid, "New Chat")
        if chat_id:
            active_sessions[request.sid]['current_chat_id'] = chat_id
            logger.info(f"Created MongoDB chat session: {chat_id}")
    
    # Don't send initial message to chat
    # emit('connection_response', {
    #     'status': 'connected',
    #     'message': "Hello! I'm your Sales Intelligence Assistant. Enter a company name to begin comprehensive analysis."
    # })


@socketio.on('connect', namespace=progress_namespace)
def handle_progress_connect():
    """Handle progress namespace connection"""
    logger.info(f"Progress channel connected: {request.sid}")


@socketio.on('register_session', namespace=progress_namespace)
def register_progress_session(data):
    """Map progress namespace connection to main session room"""
    main_sid = data.get('main_sid') if data else None
    progress_sid = request.sid

    if not main_sid:
        emit('error', {'message': 'Missing main session identifier'})
        return

    if main_sid not in active_sessions:
        emit('error', {'message': 'Session not found for progress channel'})
        return

    join_room(main_sid, sid=progress_sid, namespace=progress_namespace)
    active_sessions[main_sid]['progress_sid'] = progress_sid
    logger.info(f"Registered progress channel {progress_sid} for session {main_sid}")
    emit('progress_registered', {'success': True, 'room': main_sid})


@socketio.on('disconnect', namespace=progress_namespace)
def handle_progress_disconnect():
    """Cleanup progress namespace mapping"""
    progress_sid = request.sid
    logger.info(f"Progress channel disconnected: {progress_sid}")

    for session_id, session_data in active_sessions.items():
        if session_data.get('progress_sid') == progress_sid:
            leave_room(session_id, sid=progress_sid, namespace=progress_namespace)
            session_data['progress_sid'] = None
            break


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")
    if request.sid in active_sessions:
        progress_sid = active_sessions[request.sid].get('progress_sid')
        if progress_sid:
            leave_room(request.sid, sid=progress_sid, namespace=progress_namespace)
        del active_sessions[request.sid]


@socketio.on('research_company')
def handle_research_company(data):
    """Handle company research request with multi-agent system"""
    session_id = request.sid
    
    # Start in background thread for non-blocking execution
    socketio.start_background_task(run_research_in_background, session_id, data)

def run_research_in_background(session_id, data):
    """Run research in background to allow real-time progress updates"""
    user_prompt = data.get('company_name', '').strip()  # Can be company name or full prompt
    gather_data = data.get('gather_data', True)
    selected_agents = data.get('selected_agents', None)  # Agent selection from modal
    
    if not user_prompt:
        socketio.emit('error', {'message': 'Company name or prompt is required'}, namespace=progress_namespace, room=session_id)
        return
    
    logger.info(f"Multi-agent research request (background) with prompt: {user_prompt[:100]}...")
    
    # Step 0: Process prompt through Gemini to extract structured information
    socketio.emit('progress_update', {
        'step': 'prompt_processing',
        'message': '🤖 Processing your request...',
        'details': 'Analyzing prompt and extracting key information',
        'progress': 5
    }, namespace=progress_namespace, room=session_id)
    socketio.sleep(0.01)  # Flush the emit
    
    try:
        prompt_data = main_agent.process_prompt(user_prompt)
        company_name = prompt_data['company_name']
        additional_data_requested = prompt_data['additional_data_requested']
        references_given = prompt_data['references_given']
        associated_companies = prompt_data['associated_companies']
        user_type = prompt_data.get('user_type', 'standard')
        needs_clarification = prompt_data.get('needs_clarification', False)
        edge_case_type = prompt_data.get('edge_case_type', 'none')
        
        # Handle edge cases - inappropriate requests
        if edge_case_type != 'none':
            edge_case_responses = {
                'personal_info': f"That's an interesting question—but I can't access or disclose personal information like pet ownership or food preferences unless it's public and relevant to company strategy. Would you like me to focus on {company_name if company_name else 'their'} business objectives or how Eightfold AI might align with their tech strategy instead?",
                'confidential_data': f"That level of financial detail isn't publicly available for {company_name if company_name else 'most companies'}. However, I can analyze recent funding rounds, headcount trends, product launches, and growth trajectory to estimate their hiring focus and expansion plans. Shall I proceed with that analysis?",
                'off_topic': "I'm specifically designed to help with company research and sales intelligence for Eightfold AI. I can't assist with that topic, but I'd be happy to research any company you're interested in or help generate an account plan!"
            }
            emit('chat_response', {
                'message': edge_case_responses.get(edge_case_type, edge_case_responses['off_topic']),
                'type': 'edge_case_response',
                'timestamp': datetime.now().isoformat()
            })
            return
        
        # Handle confused users who need clarification
        if needs_clarification or not company_name:
            clarification_message = "I'd be happy to help! To get started, I need a bit more information:\n\n"
            clarification_message += "1. What's the name of the company you're interested in?\n"
            clarification_message += "2. What would you like to know? (business model, partnership potential, competitive analysis, hiring needs, etc.)\n\n"
            clarification_message += "Even if you're not sure of the details, just share the company name and I'll take it from there!"
            
            emit('chat_response', {
                'message': clarification_message,
                'type': 'clarification_needed',
                'timestamp': datetime.now().isoformat()
            })
            return
        
        # Proceed with research - adapt messaging to user type (for progress updates only)
        user_type_messages = {
            'efficient': f'Understood. Fetching current data on {company_name}...',
            'chatty': f'Great choice! Let me dive into what {company_name} is all about. I\'ll keep you updated as I learn more.',
            'confused': f'Got it! I\'ll start gathering information about {company_name} and see how Eightfold\'s products could fit. I\'ll keep you updated.',
            'standard': f'Starting comprehensive analysis for {company_name}...'
        }
        
        # Build additional context from references and associated companies
        additional_context = ''
        if references_given:
            additional_context += f"Reference Information: {references_given}\n\n"
        if additional_data_requested:
            additional_context += f"Additional Analysis Requested: {additional_data_requested}\n\n"
        
        socketio.emit('progress_update', {
            'step': 'prompt_processed',
            'message': f'✓ Identified primary company: {company_name}',
            'details': user_type_messages.get(user_type, user_type_messages['standard']),
            'progress': 10
        }, namespace=progress_namespace, room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        
    except Exception as e:
        logger.error(f"Error processing prompt: {e}")
        # Fallback: treat as simple company name
        company_name = user_prompt
        additional_data_requested = ''
        references_given = ''
        associated_companies = []
        additional_context = ''
    
    # Store/update session
    if session_id not in active_sessions:
        active_sessions[session_id] = {}
    
    active_sessions[session_id].update({
        'company_name': company_name,
        'status': 'researching',
        'current_agent': None,
        'associated_companies': associated_companies,
        'research_done': False,
        'research_results': {},
        'selected_agents': selected_agents if selected_agents else ['overview', 'value', 'goals', 'domain', 'synergy'],
        'sources_used': {
            'pinecone_eightfold': [],
            'pinecone_target': [],
            'web_scraped': []
        }
    })

    def emit_sources_update():
        """Emit the latest sources list to the frontend"""
        try:
            session_sources = active_sessions.get(session_id, {}).get('sources_used')
            if session_sources is not None:
                socketio.emit('sources_data', session_sources, room=session_id)
        except Exception as e:
            logger.error(f"Error emitting sources data: {e}")
    
    # Set up scraping callback to emit progress
    def scraping_callback(scrape_data):
        """Callback to emit scraping progress to frontend"""
        try:
            logger.info(f"Scraping callback invoked for: {scrape_data.get('url', 'unknown')}")
            
            # Ensure session exists and has sources_used structure
            if session_id in active_sessions:
                if 'sources_used' not in active_sessions[session_id]:
                    active_sessions[session_id]['sources_used'] = {
                        'pinecone_eightfold': [],
                        'pinecone_target': [],
                        'web_scraped': []
                    }
                
                # Add to sources_used (only success and cached)
                if scrape_data['status'] in ['success', 'cached']:
                    # Check for duplicates
                    existing_urls = [s['url'] for s in active_sessions[session_id]['sources_used']['web_scraped']]
                    if scrape_data['url'] not in existing_urls:
                        active_sessions[session_id]['sources_used']['web_scraped'].append({
                            'url': scrape_data['url'],
                            'title': scrape_data['title'],
                            'description': scrape_data['description'],
                            'domain': scrape_data['domain']
                        })
                        logger.info(f"Added web source: {scrape_data['url']} (total: {len(active_sessions[session_id]['sources_used']['web_scraped'])})")
                        emit_sources_update()
            
            # Emit to frontend using socketio
            socketio.emit('scraping_progress', {
                'url': scrape_data['url'],
                'domain': scrape_data['domain'],
                'title': scrape_data['title'],
                'description': scrape_data['description'],
                'status': scrape_data['status']
            }, namespace=progress_namespace, room=session_id)
            socketio.sleep(0.01)  # Flush the emit
            logger.info(f"Emitted scraping progress for: {scrape_data['url']}")
        except Exception as e:
            logger.error(f"Error in scraping callback: {e}")
            import traceback
            traceback.print_exc()
    
    # Register callback with web scraper
    from src.tools.web_scraper import web_scraper, search_tool
    web_scraper.set_scraping_callback(scraping_callback)
    web_scraper.current_company = company_name  # Set current company for callback context
    if hasattr(search_tool, 'scraper'):
        search_tool.scraper.set_scraping_callback(scraping_callback)
        search_tool.scraper.current_company = company_name
    logger.info(
        f"Scraping callback registered for {company_name}, web_scraper set: {web_scraper.scraping_callback is not None}, "
        f"search_tool scraper set: {getattr(search_tool.scraper, 'scraping_callback', None) is not None}"
    )
    
    # Send acknowledgment (only to progress screen, not chat)
    socketio.emit('research_started', {
        'company_name': company_name,
        'message': f'Starting comprehensive analysis for {company_name}...',
        'associated_companies': associated_companies
    }, room=session_id)
    
    try:
        # Step 1: Gather company data if requested
        if gather_data:
            # Gather data for primary company
            socketio.emit('progress_update', {
                'step': 'data_gathering',
                'message': f'Gathering data for {company_name}...',
                'details': 'Searching web and scraping company website',
                'progress': 15
            }, namespace=progress_namespace, room=session_id)
            socketio.sleep(0.01)  # Flush the emit
            
            data_stats = main_agent.gather_company_data(company_name, additional_context)
            
            # Different message based on whether we used existing or new data
            if data_stats.get('used_existing_data'):
                socketio.emit('progress_update', {
                    'step': 'data_gathered',
                    'message': f'✓ Using existing data: {data_stats.get("total_documents", 0)} documents (quality: {data_stats.get("quality_score", 0):.0%})',
                    'details': 'Sufficient high-quality data found in knowledge base',
                    'progress': 25
                }, namespace=progress_namespace, room=session_id)
                socketio.sleep(0.01)  # Flush the emit
            else:
                socketio.emit('progress_update', {
                    'step': 'data_gathered',
                    'message': f'✓ Fresh data gathered: {data_stats.get("total_documents", 0)} documents',
                    'details': f'Search results: {data_stats.get("search_results", 0)}, Website pages: {data_stats.get("website_pages", 0)}',
                    'progress': 25
                }, namespace=progress_namespace, room=session_id)
                socketio.sleep(0.01)  # Flush the emit
            
            # Gather data for associated companies (for comparison/context)
            if associated_companies:
                for idx, assoc_company in enumerate(associated_companies):
                    socketio.emit('progress_update', {
                        'step': f'associated_data_gathering_{idx}',
                        'message': f'Gathering comparison data for {assoc_company}...',
                        'details': 'Building knowledge graph for multi-company analysis',
                        'progress': 25 + (idx + 1) * (15 // len(associated_companies))
                    }, namespace=progress_namespace, room=session_id)
                    socketio.sleep(0.01)  # Flush the emit
                    
                    try:
                        assoc_stats = main_agent.gather_company_data(assoc_company)
                        logger.info(f"Gathered {assoc_stats.get('total_documents', 0)} docs for {assoc_company}")
                        
                        # Add relationship context
                        relationship_context = f"Comparison Context: {assoc_company} is being analyzed in relation to {company_name}. {additional_context}"
                        additional_context += f"\n\nComparison Data for {assoc_company}: Available in knowledge graph."
                        
                    except Exception as e:
                        logger.error(f"Error gathering data for {assoc_company}: {e}")
                
                socketio.emit('progress_update', {
                    'step': 'all_data_gathered',
                    'message': f'✓ All company data gathered',
                    'details': f'Primary: {company_name}, Comparisons: {len(associated_companies)}',
                    'progress': 40
                }, namespace=progress_namespace, room=session_id)
                socketio.sleep(0.01)  # Flush the emit
        
        # Step 2: Run agents in parallel
        # Determine which agents to run based on selection or additional data request
        agents_to_run = None
        if selected_agents:
            # Map frontend keys to backend agent keys
            agent_key_map = {
                'overview': 'overview',
                'value': 'product_fit',
                'goals': 'goals',
                'domain': 'dept_mapping',
                'synergy': 'synergy'
            }
            agents_to_run = [agent_key_map.get(key, key) for key in selected_agents]
            # Add additional_data agent if there's a specific request
            if additional_data_requested and additional_data_requested.strip():
                if 'additional_data' not in agents_to_run:
                    agents_to_run.append('additional_data')
        elif additional_data_requested and additional_data_requested.strip():
            # Include additional_data agent when specific request is made
            agents_to_run = ['overview', 'product_fit', 'goals', 'dept_mapping', 'synergy', 'additional_data']
        
        agent_count = len(agents_to_run) if agents_to_run else 7
        socketio.emit('progress_update', {
            'step': 'agents_starting',
            'message': f'Running {agent_count} selected agents in parallel...',
            'details': 'Parallel execution for faster results' + (' (including custom data request)' if additional_data_requested else ''),
            'progress': 45
        }, namespace=progress_namespace, room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        
        # Reset retriever's document tracking for this session
        main_agent.reset_retrieved_documents()
        
        # Define progress callback
        agent_names = {
            'overview': ('Company Overview Agent', '🏢'),
            'product_fit': ('Product Fit Agent', '🎯'),
            'goals': ('Strategic Goals Agent', '🔮'),
            'dept_mapping': ('Department Mapping Agent', '👥'),
            'synergy': ('Synergy Agent', '🤝'),
            'pricing': ('Pricing Agent', '💰'),
            'roi': ('ROI Agent', '📈'),
            'additional_data': ('Additional Data Request Agent', '📋')
        }
        
        completed_agents = set()
        total_agents_count = agent_count
        
        def agent_progress_callback(data):
            agent_key = data.get('agent_key')
            status = data.get('status')
            
            if agent_key in agent_names and agent_key not in completed_agents:
                completed_agents.add(agent_key)
                agent_name, icon = agent_names[agent_key]
                status_icon = '✓' if status == 'success' else '✗'
                
                # Calculate progress
                completed_count = len(completed_agents)
                current_progress = 45 + int((completed_count / total_agents_count) * 45)
                
                logger.info(f"Emitting progress for {agent_key}...")
                socketio.emit('progress_update', {
                    'step': f'agent_{agent_key}_complete',
                    'message': f'{status_icon} {agent_name} completed',
                    'details': f'{completed_count}/{total_agents_count} agents finished',
                    'progress': current_progress
                }, namespace=progress_namespace, room=session_id)
                socketio.sleep(0)  # Yield to allow emit to flush

        # Use the orchestrator's parallel execution
        results = main_agent.generate_account_plan(
            company_name=company_name,
            gather_data=False,  # Already gathered above
            agents_to_run=agents_to_run,
            references=references_given,
            additional_data_requested=additional_data_requested,
            associated_companies=associated_companies,
            parallel=True,
            progress_callback=agent_progress_callback
        )
        
        socketio.emit('progress_update', {
            'step': 'finalizing',
            'message': '✨ Finalizing account plan...',
            'details': 'Generating comprehensive dashboard and saving results',
            'progress': 95
        }, namespace=progress_namespace, room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        
        json_content = dashboard.generate_json(results)
        html_content = dashboard.generate_html(results)
        
        # Get selected agents from session or data
        session_data = active_sessions.get(session_id, {})
        selected_agents_from_session = session_data.get('selected_agents', [])
        
        # Transform results to match frontend expectations
        frontend_plan = {
            'company_name': results['company_name'],
            'timestamp': results['timestamp'],
            'company_overview': results['analyses'].get('overview', {}).get('content', ''),
            'product_fit': results['analyses'].get('product_fit', {}).get('content', ''),
            'long_term_goals': results['analyses'].get('goals', {}).get('content', ''),
            'dept_mapping': results['analyses'].get('dept_mapping', {}).get('content', ''),
            'synergy_opportunities': results['analyses'].get('synergy', {}).get('content', ''),
            'pricing_recommendation': results['analyses'].get('pricing', {}).get('content', ''),
            'roi_forecast': results['analyses'].get('roi', {}).get('content', ''),
            'additional_data': results['analyses'].get('additional_data', {}).get('content', ''),
            'selected_agents': selected_agents_from_session,  # Include selected agents
            'sources_used': {},  # Will be populated below
            'metadata': {
                'additional_data_requested': additional_data_requested,
                'references_given': references_given,
                'associated_companies': associated_companies,
                'execution_mode': 'parallel'
            }
        }
        
        # Step 7: Collect all sources used during research
        logger.info("Collecting sources used during research...")
        
        # Get documents retrieved during agent execution
        pinecone_sources = main_agent.get_retrieved_documents()
        logger.info(f"Retrieved tracked documents - Eightfold: {len(pinecone_sources['eightfold'])}, Target: {len(pinecone_sources['target'])}")
        
        # Get web scraped sources from session
        web_scraped_sources = []
        if session_id in active_sessions:
            web_scraped_sources = active_sessions[session_id].get('sources_used', {}).get('web_scraped', [])
            logger.info(f"Retrieved {len(web_scraped_sources)} web sources from session")
        
        # Add sources to frontend_plan
        frontend_plan['sources_used'] = {
            'pinecone_eightfold': pinecone_sources['eightfold'],
            'pinecone_target': pinecone_sources['target'],
            'web_scraped': web_scraped_sources
        }
        
        logger.info(f"Sources summary - Eightfold: {len(pinecone_sources['eightfold'])}, Target: {len(pinecone_sources['target'])}, Web: {len(web_scraped_sources)}")
        
        # Emit sources data separately to ensure frontend receives it
        socketio.emit('sources_data', frontend_plan['sources_used'], room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        logger.info(f"Emitted sources_data to session {session_id}")
        
        # Final progress update showing completion
        socketio.emit('progress_update', {
            'step': 'complete',
            'message': 'Research Complete!',
            'details': 'Account plan generated successfully',
            'progress': 100
        }, namespace=progress_namespace, room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        
        socketio.emit('research_complete', {
            'company_name': company_name,
            'success': True,
            'plan': frontend_plan,
            'message': f'✓ Account plan generated successfully!',
            'associated_companies': associated_companies,
            'formats': {
                'json': json_content,
                'html': html_content
            }
        }, room=session_id)
        
        # Update session with research results
        if session_id in active_sessions:
            active_sessions[session_id]['status'] = 'complete'
            active_sessions[session_id]['research_done'] = True
            active_sessions[session_id]['research_results'] = frontend_plan
            active_sessions[session_id]['company_name'] = company_name
            active_sessions[session_id]['associated_companies'] = associated_companies
        
        # Save research results and update company name in MongoDB
        update_chat_company_name(session_id, company_name)
        save_research_to_db(session_id, frontend_plan)
        
    except Exception as e:
        logger.error(f"Research error: {e}")
        import traceback
        traceback.print_exc()
        
        # Emit error progress update
        socketio.emit('progress_update', {
            'step': 'error',
            'message': '❌ Error Occurred',
            'details': str(e),
            'progress': 0
        }, namespace=progress_namespace, room=session_id)
        socketio.sleep(0.01)  # Flush the emit
        
        socketio.emit('error', {
            'message': f'Error researching {company_name}: {str(e)}'
        }, namespace=progress_namespace, room=session_id)
        
        if session_id in active_sessions:
            active_sessions[session_id]['status'] = 'error'


@socketio.on('chat_message')
def handle_chat_message(data):
    """Handle general chat messages with intelligent classification and conversation history tracking"""
    session_id = request.sid
    message = data.get('message', '').strip()
    
    if not message:
        return
    
    logger.info(f"Chat message from {session_id}: {message}")
    
    # Get or create session data
    if session_id not in active_sessions:
        active_sessions[session_id] = {
            'company_name': '',
            'status': 'idle',
            'research_done': False,
            'research_results': {},
            'associated_companies': [],
            'current_agent': None,
            'conversation_history': [],
            'api_key_index': 0  # Initialize with first key
        }
    
    session_data = active_sessions[session_id]
    
    # Don't add to history yet - classify first using PREVIOUS context
    if 'conversation_history' not in session_data:
        session_data['conversation_history'] = []
    
    # Classify the message using conversation history BEFORE this message
    emit('chat_typing', {'typing': True})
    classification = classify_user_message(message, session_data, session_id)
    
    logger.info(f"Message type: {classification['type']}, Confidence: {classification['confidence']}")
    logger.info(f"Conversation history length: {len(session_data.get('conversation_history', []))}")
    
    # NOW add user message to conversation history (Chain of Thought)
    session_data['conversation_history'].append({
        'role': 'user',
        'content': message,
        'timestamp': datetime.now().isoformat()
    })
    
    # Save user message to MongoDB
    save_message_to_db(session_id, 'user', message, 'text')
    
    try:
        # Use processed message for research requests
        processed_message = classification.get('processed_message', message)
        
        if classification['type'] == 'casual':
            # Handle casual conversation with conversation history (EXCLUDE current message)
            # Pass history up to but NOT including the current user message we just added
            history_for_context = session_data.get('conversation_history', [])[:-1]
            response = handle_chat(processed_message, session_id, history_for_context)
            
            # Add assistant response to conversation history
            session_data['conversation_history'].append({
                'role': 'assistant',
                'content': response,
                'timestamp': datetime.now().isoformat()
            })
            
            # Save assistant response to MongoDB
            save_message_to_db(session_id, 'assistant', response, 'casual')
            
            emit('chat_response', {
                'message': response,
                'type': 'casual',
                'timestamp': datetime.now().isoformat()
            })
            
        elif classification['type'] == 'research_request':
            # Detect user type from the original message to send appropriate acknowledgment
            user_type = 'standard'
            is_funny = any(word in message.lower() for word in ['reminds me', 'funny', 'haha', 'lol', 'right?', 'beach trip', 'interesting name'])
            is_chatty = len(message.split()) > 25 or '...' in message or any(word in message.lower() for word in ['anyway', 'so', 'i mean'])
            is_efficient = any(phrase in message.lower() for phrase in ['keep it short', 'focus only', 'just', 'quickly', 'brief'])
            is_uncertain = any(phrase in message.lower() for phrase in ['i think', 'umm', 'uh', 'maybe', 'not sure', 'i wonder'])
            
            if is_funny:
                user_type = 'funny'
            elif is_chatty:
                user_type = 'chatty'
            elif is_efficient:
                user_type = 'efficient'
            elif is_uncertain:
                user_type = 'uncertain'
            
            # Extract just the company name from processed message
            # Use LLM to extract clean company name
            try:
                extract_prompt = f"""Extract ONLY the company name from this message: "{processed_message}"

Examples:
- "Research Apple Inc" → "Apple"
- "Tell me about Tesla Motors" → "Tesla"
- "I want to know about Microsoft Corporation" → "Microsoft"
- "Umm... I think it's called Veritas Cloud. I want to know if Eightfold could work with them?" → "Veritas Cloud"
- "Bluewave Systems—funny name, right?" → "Bluewave Systems"

Respond with ONLY the company name, nothing else."""
                
                company_mention = invoke_with_fallback(extract_prompt, session_id).strip()
                # Remove any quotes or extra punctuation
                company_mention = company_mention.strip('"\'.,!?')
            except:
                # Fallback: use processed message as-is
                company_mention = processed_message
            
            # Create user-type-adapted acknowledgment
            if user_type == 'funny':
                # For funny/playful users, match their energy with a light observation
                ack_message = f"That's a fun observation! Let's see what {company_mention} is all about. Please select which areas you'd like me to analyze."
            elif user_type == 'chatty':
                # For chatty users (but not funny), be warm but professional
                ack_message = f"Sounds good! Let me research {company_mention}. First, please select which research areas you'd like."
            elif user_type == 'efficient':
                # For efficient users, be direct and concise
                ack_message = f"Understood. Select research areas for {company_mention}."
            elif user_type == 'uncertain':
                # For uncertain users, be reassuring
                ack_message = f"Got it! I'll analyze {company_mention}. Please choose which areas to focus on."
            else:
                # Standard acknowledgment
                ack_message = f"Great! I'll research {company_mention}. Please select which areas you'd like me to analyze."
            
            # Store company name for when user confirms agent selection
            # Don't send chat message yet - will send after agent selection
            session_data['pending_research'] = {
                'company_name': processed_message,
                'company_mention': company_mention,
                'ack_message': ack_message,  # Store for later
                'timestamp': datetime.now().isoformat()
            }
            
            # Update chat name in MongoDB immediately when company is identified
            update_chat_company_name(session_id, company_mention)
            
            # Emit chat name update to frontend
            emit('chat_name_updated', {
                'company_name': company_mention,
                'session_id': session_id
            })
            
            # Send flag to show agent selection modal (no chat message)
            emit('chat_response', {
                'message': '',  # No message in chat yet
                'type': 'research_acknowledgment',
                'show_agent_selection': True,
                'company_name': company_mention,
                'timestamp': datetime.now().isoformat()
            })
            
            # DON'T trigger research yet - wait for agent selection confirmation
            # handle_research_company will be called from a new endpoint
            
        elif classification['type'] == 'follow_up':
            # Handle follow-up question using processed message (show typing indicator only)
            result = handle_follow_up_question(processed_message, session_data, session_id)
            
            # Add assistant response to conversation history
            session_data['conversation_history'].append({
                'role': 'assistant',
                'content': result['answer'],
                'timestamp': datetime.now().isoformat(),
                'source': result['source']
            })
            
            source_label = {
                'cached': 'From research data',
                'additional_agent': 'Fresh from web search',
                'error': '⚠️ Error'
            }.get(result['source'], '')
            
            emit('chat_response', {
                'message': result['answer'],
                'type': 'follow_up_answer',
                'source': result['source'],
                'source_label': source_label,
                'confidence': result['confidence'],
                'timestamp': datetime.now().isoformat()
            })
        
        else:
            # Fallback
            fallback_msg = "I'm not sure how to help with that. Try asking me to research a company or ask a question about a company we've already researched."
            
            session_data['conversation_history'].append({
                'role': 'assistant',
                'content': fallback_msg,
                'timestamp': datetime.now().isoformat()
            })
            
            emit('chat_response', {
                'message': fallback_msg,
                'type': 'unclear',
                'timestamp': datetime.now().isoformat()
            })
    
    except Exception as e:
        logger.error(f"Error handling chat message: {e}")
        import traceback
        traceback.print_exc()
        
        error_msg = f"I encountered an error: {str(e)}"
        session_data['conversation_history'].append({
            'role': 'assistant',
            'content': error_msg,
            'timestamp': datetime.now().isoformat()
        })
        
        emit('chat_response', {
            'message': error_msg,
            'type': 'error',
            'timestamp': datetime.now().isoformat()
        })
    
    finally:
        emit('chat_typing', {'typing': False})


@socketio.on('new_session')
def handle_new_session():
    """Reset session for new research - clears conversation history (Chain of Thought)"""
    session_id = request.sid
    
    logger.info(f"New session requested by {session_id}")
    
    # Reset session data including conversation history
    active_sessions[session_id] = {
        'company_name': '',
        'status': 'idle',
        'research_done': False,
        'research_results': {},
        'associated_companies': [],
        'current_agent': None,
        'conversation_history': [],  # Fresh conversation chain
        'progress_sid': None,
        'api_key_index': 0,  # Reset to first key on new session
        'current_chat_id': None,
        'sources_used': {
            'pinecone_eightfold': [],
            'pinecone_target': [],
            'web_scraped': []
        }
    }
    
    # Create new chat session in MongoDB
    mongo = get_mongo_manager()
    if mongo:
        chat_id = mongo.create_chat_session(session_id, "New Chat")
        if chat_id:
            active_sessions[session_id]['current_chat_id'] = chat_id
            logger.info(f"Created new MongoDB chat session: {chat_id}")
            
            # Emit chat name update so frontend refreshes chat list
            emit('chat_name_updated', {
                'company_name': 'New Chat',
                'session_id': session_id
            })
    
    emit('session_reset', {
        'success': True,
        'message': '🔄 Session reset. Ready for new research!',
        'timestamp': datetime.now().isoformat()
    })
    
    # Don't send chat message - just reset silently
    # emit('chat_response', {
    #     'message': "Session reset successfully! What company would you like to research?",
    #     'type': 'system',
    #     'timestamp': datetime.now().isoformat()
    # })


@socketio.on('confirm_agent_selection')
def handle_confirm_agent_selection(data):
    """Handle confirmed agent selection and start research"""
    session_id = request.sid
    selected_agents = data.get('selected_agents', [])
    
    if session_id not in active_sessions:
        socketio.emit('error', {'message': 'Session not found'}, namespace=progress_namespace, room=session_id)
        return
    
    session_data = active_sessions[session_id]
    pending = session_data.get('pending_research')
    
    if not pending:
        socketio.emit('error', {'message': 'No pending research found'}, namespace=progress_namespace, room=session_id)
        return
    
    company_name = pending['company_name']
    company_mention = pending['company_mention']
    ack_message = pending.get('ack_message', f"Great! Let me research {company_mention} and prepare a comprehensive analysis.")
    
    logger.info(f"Starting research for {company_mention} with selected agents: {selected_agents}")
    
    # Add acknowledgment to conversation history (the original one)
    session_data['conversation_history'].append({
        'role': 'assistant',
        'content': ack_message,
        'timestamp': datetime.now().isoformat()
    })
    
    # Save acknowledgment to MongoDB
    save_message_to_db(session_id, 'assistant', ack_message, 'research_acknowledgment')
    
    # Send ONLY the original acknowledgment chat message
    emit('chat_response', {
        'message': ack_message,
        'type': 'research_acknowledgment',
        'timestamp': datetime.now().isoformat()
    })
    
    # Clear pending research
    session_data.pop('pending_research', None)
    
    # Store selected agents in session for filtering and future regeneration
    session_data['selected_agents'] = selected_agents
    
    # Trigger research with selected agents
    handle_research_company({
        'company_name': company_name,
        'gather_data': True,
        'selected_agents': selected_agents
    })


if __name__ == '__main__':
    logger.info("Starting Company Research Assistant server...")
    logger.info(f"Debug mode: {config.DEBUG}")
    
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=config.DEBUG
    )
