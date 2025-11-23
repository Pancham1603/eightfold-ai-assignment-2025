"""
Pinecone vector store with Knowledge Graph for Graph RAG
"""

from pinecone import Pinecone, ServerlessSpec
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import List, Dict, Any, Optional, Tuple
import networkx as nx
import json
import logging
from config.settings import config

logger = logging.getLogger(__name__)

# Predefined industry categories for company classification
INDUSTRY_CATEGORIES = {
    'TECHNOLOGY_SOFTWARE': {
        'name': 'Technology & Software',
        'keywords': ['software', 'saas', 'platform', 'cloud', 'ai', 'machine learning', 'analytics', 'data'],
        'description': 'Software development, SaaS platforms, cloud services, AI/ML solutions'
    },
    'FINANCE_FINTECH': {
        'name': 'Finance & FinTech',
        'keywords': ['bank', 'finance', 'payment', 'fintech', 'insurance', 'investment', 'trading', 'blockchain'],
        'description': 'Banking, financial services, payment processing, insurance, investment platforms'
    },
    'HEALTHCARE_MEDICAL': {
        'name': 'Healthcare & Medical',
        'keywords': ['healthcare', 'medical', 'hospital', 'pharmaceutical', 'biotech', 'health tech', 'telemedicine'],
        'description': 'Healthcare services, medical devices, pharmaceuticals, health technology'
    },
    'ECOMMERCE_RETAIL': {
        'name': 'E-commerce & Retail',
        'keywords': ['ecommerce', 'retail', 'marketplace', 'shopping', 'consumer', 'e-commerce', 'online store'],
        'description': 'Online retail, marketplaces, consumer goods, retail technology'
    },
    'MANUFACTURING_INDUSTRIAL': {
        'name': 'Manufacturing & Industrial',
        'keywords': ['manufacturing', 'industrial', 'factory', 'production', 'automation', 'supply chain'],
        'description': 'Manufacturing, industrial automation, supply chain, production systems'
    },
    'MARKETING_ADVERTISING': {
        'name': 'Marketing & Advertising',
        'keywords': ['marketing', 'advertising', 'digital marketing', 'seo', 'content', 'social media', 'brand'],
        'description': 'Marketing services, advertising, digital marketing, branding, content creation'
    },
    'EDUCATION_EDTECH': {
        'name': 'Education & EdTech',
        'keywords': ['education', 'learning', 'training', 'edtech', 'e-learning', 'course', 'university'],
        'description': 'Educational services, e-learning platforms, training, educational technology'
    },
    'CONSULTING_SERVICES': {
        'name': 'Consulting & Professional Services',
        'keywords': ['consulting', 'advisory', 'professional services', 'consulting firm', 'strategy'],
        'description': 'Business consulting, professional services, advisory, strategy'
    },
    'REAL_ESTATE_CONSTRUCTION': {
        'name': 'Real Estate & Construction',
        'keywords': ['real estate', 'property', 'construction', 'building', 'architecture', 'proptech'],
        'description': 'Real estate, property management, construction, architecture'
    },
    'TELECOMMUNICATIONS': {
        'name': 'Telecommunications',
        'keywords': ['telecom', 'telecommunications', 'network', 'mobile', 'broadband', 'connectivity'],
        'description': 'Telecommunications, networking, mobile services, connectivity'
    },
    'ENERGY_UTILITIES': {
        'name': 'Energy & Utilities',
        'keywords': ['energy', 'utility', 'power', 'renewable', 'solar', 'electric', 'oil', 'gas'],
        'description': 'Energy production, utilities, renewable energy, power distribution'
    },
    'TRANSPORTATION_LOGISTICS': {
        'name': 'Transportation & Logistics',
        'keywords': ['transportation', 'logistics', 'shipping', 'delivery', 'freight', 'supply chain', 'fleet'],
        'description': 'Transportation services, logistics, shipping, delivery, fleet management'
    },
    'MEDIA_ENTERTAINMENT': {
        'name': 'Media & Entertainment',
        'keywords': ['media', 'entertainment', 'streaming', 'content', 'gaming', 'publishing', 'music'],
        'description': 'Media production, entertainment, streaming, gaming, publishing'
    },
    'HOSPITALITY_TRAVEL': {
        'name': 'Hospitality & Travel',
        'keywords': ['hotel', 'hospitality', 'travel', 'tourism', 'restaurant', 'food service', 'booking'],
        'description': 'Hotels, restaurants, travel services, tourism, food service'
    },
    'AGRICULTURE_FOOD': {
        'name': 'Agriculture & Food',
        'keywords': ['agriculture', 'farming', 'food', 'agtech', 'agricultural', 'crop', 'livestock'],
        'description': 'Agriculture, farming, food production, agtech'
    },
    'OTHER': {
        'name': 'Other Industries',
        'keywords': [],
        'description': 'Companies that don\'t fit into standard categories'
    }
}

# Try to import spaCy for NER (optional)
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    HAS_SPACY = True
    logger.info("spaCy NER loaded successfully")
except (ImportError, OSError) as e:
    HAS_SPACY = False
    logger.warning(f"spaCy not available ({e}). Using rule-based entity extraction. Install with: pip install spacy && python -m spacy download en_core_web_sm")

class KnowledgeGraph:
    """Knowledge graph for storing entity relationships"""
    
    def __init__(self):
        """Initialize knowledge graph"""
        self.graph = nx.DiGraph()
    
    def add_entity(self, entity: str, entity_type: str, attributes: Dict[str, Any] = None):
        """Add an entity to the graph"""
        self.graph.add_node(
            entity,
            type=entity_type,
            attributes=attributes or {}
        )
    
    def add_relationship(self, source: str, target: str, relationship: str, properties: Dict[str, Any] = None):
        """Add a relationship between entities"""
        self.graph.add_edge(
            source,
            target,
            relationship=relationship,
            properties=properties or {}
        )
    
    def get_entity_relationships(self, entity: str) -> List[Dict[str, Any]]:
        """Get all relationships for an entity"""
        relationships = []
        
        if entity not in self.graph:
            return relationships
        
        # Outgoing edges
        for target in self.graph.successors(entity):
            edge_data = self.graph[entity][target]
            relationships.append({
                'source': entity,
                'target': target,
                'relationship': edge_data.get('relationship', 'related_to'),
                'properties': edge_data.get('properties', {})
            })
        
        # Incoming edges
        for source in self.graph.predecessors(entity):
            edge_data = self.graph[source][entity]
            relationships.append({
                'source': source,
                'target': entity,
                'relationship': edge_data.get('relationship', 'related_to'),
                'properties': edge_data.get('properties', {})
            })
        
        return relationships
    
    def get_subgraph(self, entity: str, depth: int = 2) -> Dict[str, Any]:
        """Get subgraph around an entity"""
        if entity not in self.graph:
            return {'nodes': [], 'edges': []}
        
        # Get nodes within depth
        nodes = set([entity])
        current_level = set([entity])
        
        for _ in range(depth):
            next_level = set()
            for node in current_level:
                next_level.update(self.graph.successors(node))
                next_level.update(self.graph.predecessors(node))
            nodes.update(next_level)
            current_level = next_level
        
        # Extract subgraph
        subgraph = self.graph.subgraph(nodes)
        
        return {
            'nodes': [
                {
                    'id': node,
                    'type': subgraph.nodes[node].get('type', 'unknown'),
                    'attributes': subgraph.nodes[node].get('attributes', {})
                }
                for node in subgraph.nodes()
            ],
            'edges': [
                {
                    'source': source,
                    'target': target,
                    'relationship': data.get('relationship', 'related_to'),
                    'properties': data.get('properties', {})
                }
                for source, target, data in subgraph.edges(data=True)
            ]
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary"""
        return {
            'nodes': [
                {
                    'id': node,
                    'type': self.graph.nodes[node].get('type', 'unknown'),
                    'attributes': self.graph.nodes[node].get('attributes', {})
                }
                for node in self.graph.nodes()
            ],
            'edges': [
                {
                    'source': source,
                    'target': target,
                    'relationship': data.get('relationship', 'related_to'),
                    'properties': data.get('properties', {})
                }
                for source, target, data in self.graph.edges(data=True)
            ]
        }


class PineconeGraphRAGStore:
    """Pinecone vector store with Knowledge Graph for Graph RAG"""
    
    def __init__(self):
        """Initialize Pinecone and Knowledge Graph"""
        
        # Initialize HuggingFace embeddings (free, local, unlimited)
        # Using all-MiniLM-L6-v2: fast, good quality, 384 dimensions
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        
        # Initialize Pinecone
        self.pc = Pinecone(api_key=config.PINECONE_API_KEY)
        
        # Create index if it doesn't exist
        index_name = config.PINECONE_INDEX_NAME
        
        if index_name not in self.pc.list_indexes().names():
            logger.info(f"Creating Pinecone index: {index_name}")
            self.pc.create_index(
                name=index_name,
                dimension=config.PINECONE_DIMENSION,
                metric='cosine',
                spec=ServerlessSpec(
                    cloud='aws',
                    region=config.PINECONE_REGION
                )
            )
        
        # Initialize vector store
        self.index = self.pc.Index(index_name)
        self.vectorstore = PineconeVectorStore(
            index=self.index,
            embedding=self.embeddings,
            text_key="text"
        )
        
        # Initialize knowledge graph
        self.knowledge_graph = KnowledgeGraph()
        
        # Initialize Gemini for data quality validation
        self.llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=0.1  # Low temperature for consistent yes/no answers
        )
        
        logger.info(f"Pinecone Graph RAG Store initialized with index: {index_name}")
    
    def validate_data_quality(self, content: str, company_name: str) -> bool:
        """
        Use Gemini LLM to validate if retrieved data is meaningful or just placeholder text
        
        Args:
            content: The content to validate
            company_name: Name of the company
        
        Returns:
            True if data is meaningful, False if it's placeholder/under construction/low quality
        """
        try:
            # Create validation prompt
            validation_prompt = f"""Analyze the following text about '{company_name}' and determine if it contains meaningful, actionable business information.

Text to analyze:
{content[:1000]}

Respond with ONLY 'TRUE' if the text contains:
- Specific business information (products, services, business model)
- Concrete details about the company's operations
- Recent news, events, or developments
- Verifiable facts about the company

Respond with ONLY 'FALSE' if the text:
- States the website is under construction
- Contains only generic/vague statements
- Says information is limited or unavailable
- Is placeholder content with no real details
- Contains error messages or "coming soon" type messages

Your response (TRUE or FALSE):"""
            
            response = self.llm.invoke(validation_prompt)
            result = response.content.strip().upper()
            
            # Parse response
            is_meaningful = result.startswith('TRUE')
            
            if not is_meaningful:
                logger.warning(f"Data validation failed for {company_name}: Low quality content detected")
            else:
                logger.info(f"Data validation passed for {company_name}: Meaningful content found")
            
            return is_meaningful
            
        except Exception as e:
            logger.error(f"Error in data quality validation: {e}")
            # On error, assume data is valid to avoid blocking the workflow
            return True
    
    def categorize_company(self, company_name: str, content: str) -> List[str]:
        """
        Categorize a company into one or more industry categories using LLM analysis
        
        Args:
            company_name: Name of the company
            content: Company information/description
        
        Returns:
            List of category keys (e.g., ['TECHNOLOGY_SOFTWARE', 'FINANCE_FINTECH'])
        """
        try:
            # Create categorization prompt
            categories_list = "\n".join([
                f"- {key}: {info['name']} - {info['description']}"
                for key, info in INDUSTRY_CATEGORIES.items()
            ])
            
            categorization_prompt = f"""Analyze the following company information and categorize '{company_name}' into the most relevant industry categories.

Company Information:
{content[:2000]}

Available Categories:
{categories_list}

Instructions:
1. Select 1-3 most relevant categories (primary category first)
2. Respond with ONLY the category keys separated by commas
3. If none fit well, use 'OTHER'

Example response format: TECHNOLOGY_SOFTWARE,FINANCE_FINTECH

Your response (category keys only):"""
            
            response = self.llm.invoke(categorization_prompt)
            result = response.content.strip().upper()
            
            # Parse response
            categories = [cat.strip() for cat in result.split(',') if cat.strip()]
            
            # Validate categories
            valid_categories = [cat for cat in categories if cat in INDUSTRY_CATEGORIES]
            
            if not valid_categories:
                # Fallback: keyword-based matching
                valid_categories = self._keyword_based_categorization(content)
            
            logger.info(f"Categorized {company_name} as: {', '.join(valid_categories)}")
            return valid_categories
            
        except Exception as e:
            logger.error(f"Error categorizing company: {e}")
            # Fallback to keyword-based
            return self._keyword_based_categorization(content)
    
    def _keyword_based_categorization(self, content: str) -> List[str]:
        """Fallback: Categorize using keyword matching"""
        content_lower = content.lower()
        matched_categories = []
        
        for category_key, category_info in INDUSTRY_CATEGORIES.items():
            if category_key == 'OTHER':
                continue
            keywords = category_info['keywords']
            if any(keyword in content_lower for keyword in keywords):
                matched_categories.append(category_key)
        
        # Return top 3 or default to OTHER
        return matched_categories[:3] if matched_categories else ['OTHER']
    
    def extract_entities(self, text: str, company_name: str) -> List[Tuple[str, str]]:
        """
        Extract entities from text for knowledge graph using spaCy NER
        Falls back to rule-based if spaCy unavailable
        """
        entities = []
        
        # Add company as main entity
        entities.append((company_name.lower(), 'ORGANIZATION'))

        # Use spaCy NER for better entity extraction
        try:
            doc = nlp(text[:5000])  # Limit text length for performance
            
            entity_type_mapping = {
                'ORG': 'ORGANIZATION',
                'PERSON': 'PERSON',
                'GPE': 'LOCATION',
                'LOC': 'LOCATION',
                'PRODUCT': 'PRODUCT',
                'MONEY': 'FINANCIAL',
                'DATE': 'DATE',
                'EVENT': 'EVENT'
            }
            
            for ent in doc.ents:
                mapped_type = entity_type_mapping.get(ent.label_, ent.label_)
                entities.append((ent.text.lower(), mapped_type))
            
            logger.debug(f"Extracted {len(entities)} entities using spaCy NER")
            return entities
            
        except Exception as e:
            logger.error(f"spaCy NER error: {e}, falling back to rule-based")
        
        # Fallback: Rule-based extraction
        keywords = {
            'PRODUCT': ['product', 'service', 'platform', 'solution', 'app', 'tool'],
            'TECHNOLOGY': ['technology', 'software', 'system', 'framework', 'ai', 'cloud'],
            'LOCATION': ['headquarters', 'office', 'based in', 'located', 'city'],
            'PERSON': ['ceo', 'founder', 'executive', 'president', 'director'],
            'INDUSTRY': ['industry', 'sector', 'market', 'business']
        }
        
        text_lower = text.lower()
        for entity_type, markers in keywords.items():
            for marker in markers:
                if marker in text_lower:
                    entities.append((marker, entity_type))
        
        return entities
    
    def add_company_data(
        self,
        company_name: str,
        data: List[Dict[str, Any]],
        source: str = "web_scraping"
    ) -> List[str]:
        """
        Add company research data to vector store and knowledge graph with error handling
        
        Args:
            company_name: Name of the company
            data: List of data chunks with 'content' and optional 'metadata'
            source: Source of the data
        
        Returns:
            List of document IDs added
        """
        try:
            documents = []
            
            # Categorize company using all content
            all_content = " ".join([item.get('content', '')[:500] for item in data])
            company_categories = self.categorize_company(company_name, all_content)
            
            # Add company node to knowledge graph with categories
            self.knowledge_graph.add_entity(
                company_name.lower(),
                'ORGANIZATION',
                {
                    'name': company_name,
                    'source': source,
                    'categories': company_categories,
                    'primary_category': company_categories[0] if company_categories else 'OTHER'
                }
            )
            
            # Add category relationships to knowledge graph
            for category in company_categories:
                category_name = INDUSTRY_CATEGORIES[category]['name']
                self.knowledge_graph.add_entity(category, 'INDUSTRY_CATEGORY', {'name': category_name})
                self.knowledge_graph.add_relationship(
                    company_name.lower(),
                    category,
                    'belongs_to_category',
                    {'primary': category == company_categories[0]}
                )
            
            for idx, item in enumerate(data):
                content = item.get('content', '')
                metadata = item.get('metadata', {})
                
                if not content:
                    logger.warning(f"Empty content for chunk {idx}, skipping")
                    continue
                
                # Enrich metadata - keep it minimal to avoid 40KB limit
                # Truncate large fields to prevent metadata size issues
                clean_metadata = {
                    'company_name': company_name.lower(),
                    'source': source,
                    'chunk_id': idx,
                    'url': metadata.get('url', '')[:500],  # Limit URL length
                    'title': metadata.get('title', '')[:200],  # Limit title
                    'type': metadata.get('type', 'text'),
                    'categories': ','.join(company_categories),  # Store as comma-separated string
                    'primary_category': company_categories[0] if company_categories else 'OTHER'
                }
                
                # Add snippet only if small enough
                snippet = metadata.get('snippet', '')
                if snippet and len(snippet) < 500:
                    clean_metadata['snippet'] = snippet[:500]
                
                metadata = clean_metadata
                
                # Extract entities and build knowledge graph
                try:
                    entities = self.extract_entities(content, company_name)
                    for entity, entity_type in entities:
                        self.knowledge_graph.add_entity(entity, entity_type)
                        self.knowledge_graph.add_relationship(
                            company_name.lower(),
                            entity,
                            'mentions',
                            {'context': content[:100]}
                        )
                except Exception as e:
                    logger.error(f"Error extracting entities for chunk {idx}: {e}")
                
                # Skip graph_context in metadata to avoid size limits
                # Graph context will be retrieved separately when needed
                
                # Final safety check: ensure metadata is under 35KB (safe margin from 40KB limit)
                metadata_str = json.dumps(metadata)
                if len(metadata_str.encode('utf-8')) > 35000:
                    logger.warning(f"Metadata too large ({len(metadata_str.encode('utf-8'))} bytes), truncating")
                    # Remove snippet if still too large
                    if 'snippet' in metadata:
                        del metadata['snippet']
                    # Truncate title further if needed
                    if 'title' in metadata:
                        metadata['title'] = metadata['title'][:100]
                
                doc = Document(
                    page_content=content,
                    metadata=metadata
                )
                documents.append(doc)
            
            if not documents:
                logger.warning(f"No valid documents to add for {company_name}")
                return []
            
            # Add to vector store with batch operation
            try:
                ids = self.vectorstore.add_documents(documents)
                logger.info(f"Successfully added {len(ids)} documents for company: {company_name}")
                return ids
            except Exception as e:
                logger.error(f"Error adding documents to Pinecone: {e}")
                raise
                
        except Exception as e:
            logger.error(f"Error in add_company_data for {company_name}: {e}")
            raise
    
    def search_company_data(
        self,
        query: str,
        company_name: Optional[str] = None,
        k: int = 5,
        include_graph: bool = True
    ) -> List[Document]:
        """
        Search for relevant company data with graph context
        
        Args:
            query: Search query
            company_name: Optional company name to filter results
            k: Number of results to return
            include_graph: Include knowledge graph context
        
        Returns:
            List of relevant documents with graph context
        """
        if company_name:
            # Filter by company name
            results = self.vectorstore.similarity_search(
                query,
                k=k,
                filter={'company_name': company_name.lower()}
            )
        else:
            results = self.vectorstore.similarity_search(query, k=k)
        
        # Enrich with graph context if requested
        if include_graph and results:
            for doc in results:
                company = doc.metadata.get('company_name')
                if company:
                    graph_context = self.knowledge_graph.get_subgraph(company, depth=2)
                    doc.metadata['graph_subgraph'] = graph_context
        
        logger.info(f"Found {len(results)} results for query: {query}")
        return results
    
    def get_company_context(self, company_name: str, max_docs: int = 10) -> str:
        """
        Get comprehensive context about a company with graph RAG
        
        Args:
            company_name: Name of the company
            max_docs: Maximum number of documents to retrieve
        
        Returns:
            Formatted context string with graph information
        """
        results = self.search_company_data(
            f"Information about {company_name}",
            company_name=company_name,
            k=max_docs,
            include_graph=True
        )
        
        if not results:
            return f"No data found for {company_name}"
        
        # Get knowledge graph context
        graph_context = self.knowledge_graph.get_subgraph(company_name.lower(), depth=2)
        
        context_parts = [f"=== Knowledge Graph for {company_name} ==="]
        context_parts.append(f"Entities: {len(graph_context['nodes'])}")
        context_parts.append(f"Relationships: {len(graph_context['edges'])}")
        context_parts.append("")
        
        # Add relationship summary
        if graph_context['edges']:
            context_parts.append("Key Relationships:")
            for edge in graph_context['edges'][:5]:
                context_parts.append(
                    f"  - {edge['source']} --[{edge['relationship']}]--> {edge['target']}"
                )
            context_parts.append("")
        
        context_parts.append(f"=== Document Context ===")
        for idx, doc in enumerate(results, 1):
            source = doc.metadata.get('source', 'unknown')
            url = doc.metadata.get('url', '')
            context_parts.append(
                f"\n[Source {idx} - {source}]\n{doc.page_content}\n"
            )
        
        return "\n".join(context_parts)
    
    def get_category_context(self, categories: List[str], max_docs: int = 5) -> str:
        """
        Get market research context for specific industry categories
        
        Args:
            categories: List of category keys
            max_docs: Maximum documents per category
        
        Returns:
            Formatted context from companies in the same categories
        """
        context_parts = []
        
        for category in categories:
            if category not in INDUSTRY_CATEGORIES:
                continue
            
            category_info = INDUSTRY_CATEGORIES[category]
            context_parts.append(f"\n=== {category_info['name']} Industry Context ===")
            
            # Search for documents in this category
            try:
                results = self.vectorstore.similarity_search(
                    f"{category_info['description']} industry trends market analysis",
                    k=max_docs,
                    filter={'primary_category': category}
                )
                
                if results:
                    context_parts.append(f"Found {len(results)} relevant insights from {category_info['name']} companies:")
                    for idx, doc in enumerate(results, 1):
                        company = doc.metadata.get('company_name', 'Unknown')
                        context_parts.append(f"\n[Company: {company}]")
                        context_parts.append(doc.page_content[:300] + "...")
                else:
                    context_parts.append(f"No data available for {category_info['name']} category yet.")
            except Exception as e:
                logger.error(f"Error retrieving category context for {category}: {e}")
                context_parts.append(f"Error retrieving context for this category.")
        
        return "\n".join(context_parts)
    
    def get_enriched_company_context(self, company_name: str, max_docs: int = 10, include_category_context: bool = True) -> str:
        """
        Get comprehensive context about a company INCLUDING insights from similar companies in the same categories
        
        Args:
            company_name: Name of the company
            max_docs: Maximum number of documents to retrieve
            include_category_context: Whether to include context from same-category companies
        
        Returns:
            Formatted context string with company data + category insights
        """
        # Get company-specific context
        company_context = self.get_company_context(company_name, max_docs)
        
        if not include_category_context:
            return company_context
        
        # Get company categories from knowledge graph
        company_node = company_name.lower()
        if company_node in self.knowledge_graph.graph:
            node_data = self.knowledge_graph.graph.nodes[company_node]
            categories = node_data.get('attributes', {}).get('categories', [])
            
            if categories:
                category_context = self.get_category_context(categories, max_docs=3)
                
                enriched_context = f"{company_context}\n\n{'='*60}\n"
                enriched_context += f"=== RELATED INDUSTRY INSIGHTS ===\n"
                enriched_context += f"Leveraging market research from companies in the same industry:\n"
                enriched_context += category_context
                
                return enriched_context
        
        return company_context
    
    def get_knowledge_graph(self, company_name: str) -> Dict[str, Any]:
        """Get the knowledge graph for a company"""
        return self.knowledge_graph.get_subgraph(company_name.lower(), depth=3)
    
    def delete_company_data(self, company_name: str) -> int:
        """
        Delete all data for a specific company
        
        Args:
            company_name: Name of the company
        
        Returns:
            Number of documents deleted
        """
        # Note: Pinecone deletion by metadata filter requires paid tier
        # For now, we'll log this limitation
        logger.warning(
            f"Pinecone metadata filtering for deletion requires paid tier. "
            f"Company data for {company_name} marked for manual cleanup."
        )
        
        # Remove from knowledge graph
        if company_name.lower() in self.knowledge_graph.graph:
            self.knowledge_graph.graph.remove_node(company_name.lower())
            logger.info(f"Removed {company_name} from knowledge graph")
        
        return 0
    
    def list_companies(self) -> List[str]:
        """
        Get list of all companies in the knowledge graph
        
        Returns:
            List of company names
        """
        companies = [
            node for node in self.knowledge_graph.graph.nodes()
            if self.knowledge_graph.graph.nodes[node].get('type') == 'company'
        ]
        return sorted(companies)
    
    def add_eightfold_documents(self, documents: List[Document]) -> List[str]:
        """
        Add Eightfold AI reference documents to vector store
        
        These documents serve as the knowledge base about Eightfold AI's products,
        services, value propositions, and capabilities. They are tagged with special
        metadata for retrieval during company research.
        
        Args:
            documents: List of Document objects with Eightfold content
        
        Returns:
            List of document IDs added
        """
        try:
            # Ensure all documents have Eightfold-specific metadata
            for doc in documents:
                if 'is_eightfold_reference' not in doc.metadata:
                    doc.metadata['is_eightfold_reference'] = True
                if 'company_name' not in doc.metadata:
                    doc.metadata['company_name'] = 'eightfold_ai'
            
            # Add to knowledge graph
            self.knowledge_graph.add_entity(
                'eightfold_ai',
                'REFERENCE_COMPANY',
                {
                    'name': 'Eightfold AI',
                    'type': 'AI Talent Intelligence Platform',
                    'is_reference': True
                }
            )
            
            # Add documents to vector store
            ids = self.vectorstore.add_documents(documents)
            logger.info(f"Added {len(ids)} Eightfold AI reference documents to vector store")
            
            return ids
            
        except Exception as e:
            logger.error(f"Error adding Eightfold documents: {e}")
            raise
    
    def retrieve_eightfold_context(
        self,
        query: str,
        k: int = 5
    ) -> List[Document]:
        """
        Retrieve Eightfold AI reference documents relevant to a query
        
        This is used by sub-agents to get context about Eightfold's offerings
        when analyzing how to provide value to target companies.
        
        Args:
            query: Query about Eightfold's capabilities or offerings
            k: Number of documents to retrieve
        
        Returns:
            List of relevant Eightfold AI reference documents
        """
        try:
            results = self.vectorstore.similarity_search(
                query,
                k=k,
                filter={'is_eightfold_reference': True}
            )
            
            logger.info(f"Retrieved {len(results)} Eightfold reference docs for query: {query}")
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving Eightfold context: {e}")
            return []
    
    def retrieve_company_with_eightfold_context(
        self,
        company_name: str,
        query: str,
        company_docs: int = 5,
        eightfold_docs: int = 3
    ) -> Dict[str, Any]:
        """
        Retrieve both company data AND relevant Eightfold AI context
        
        This provides a comprehensive view combining:
        1. Target company information
        2. Eightfold AI capabilities relevant to the query
        
        Args:
            company_name: Target company name
            query: Specific query/question
            company_docs: Number of company documents to retrieve
            eightfold_docs: Number of Eightfold reference docs to retrieve
        
        Returns:
            Dictionary with company_context and eightfold_context
        """
        # Get company-specific information
        company_results = self.search_company_data(
            query,
            company_name=company_name,
            k=company_docs,
            include_graph=True
        )
        
        # Get relevant Eightfold AI context
        eightfold_results = self.retrieve_eightfold_context(
            query,
            k=eightfold_docs
        )
        
        # Format contexts
        company_context = "\n\n".join([
            f"[Company Source {i+1}]\n{doc.page_content}"
            for i, doc in enumerate(company_results)
        ])
        
        eightfold_context = "\n\n".join([
            f"[Eightfold Reference {i+1}]\n{doc.page_content}"
            for i, doc in enumerate(eightfold_results)
        ])
        
        return {
            'company_context': company_context if company_context else f"No data found for {company_name}",
            'eightfold_context': eightfold_context if eightfold_context else "No relevant Eightfold reference data found",
            'company_docs': company_results,
            'eightfold_docs': eightfold_results
        }
    
    def has_sufficient_company_data(self, company_name: str, min_docs: int = 10) -> Dict[str, Any]:
        """
        Check if the vector store has sufficient valuable data for a company
        
        Args:
            company_name: Name of the company to check
            min_docs: Minimum number of quality documents required
        
        Returns:
            Dictionary with:
                - has_data: bool - True if sufficient data exists
                - doc_count: int - Number of documents found
                - quality_score: float - Average quality score (0-1)
                - should_scrape: bool - Whether to proceed with scraping
        """
        try:
            # Search for general company information
            search_queries = [
                f"{company_name} company overview",
                f"{company_name} products services",
                f"{company_name} business model"
            ]
            
            all_docs = []
            for query in search_queries:
                results = self.vectorstore.similarity_search(
                    query,
                    k=10,
                    filter={'company_name': company_name.lower()}
                )
                all_docs.extend(results)
            
            # Remove duplicates based on content
            unique_docs = []
            seen_content = set()
            for doc in all_docs:
                content_hash = hash(doc.page_content[:200])
                if content_hash not in seen_content:
                    seen_content.add(content_hash)
                    unique_docs.append(doc)
            
            doc_count = len(unique_docs)
            
            # Check data quality using LLM validation
            quality_scores = []
            sample_size = min(5, doc_count)  # Check up to 5 documents for quality
            
            for doc in unique_docs[:sample_size]:
                is_quality = self.validate_data_quality(doc.page_content, company_name)
                quality_scores.append(1.0 if is_quality else 0.0)
            
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
            
            # Decision logic
            has_sufficient_data = doc_count >= min_docs and avg_quality >= 0.6
            
            result = {
                'has_data': has_sufficient_data,
                'doc_count': doc_count,
                'quality_score': avg_quality,
                'should_scrape': not has_sufficient_data
            }
            
            if has_sufficient_data:
                logger.info(f"✓ Sufficient data found for {company_name}: {doc_count} docs, quality: {avg_quality:.2f}")
            else:
                logger.info(f"✗ Insufficient data for {company_name}: {doc_count} docs (need {min_docs}), quality: {avg_quality:.2f}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking company data: {e}")
            # On error, default to scraping to be safe
            return {
                'has_data': False,
                'doc_count': 0,
                'quality_score': 0.0,
                'should_scrape': True
            }


# Global instance
vector_store = PineconeGraphRAGStore()
