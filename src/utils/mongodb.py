"""
MongoDB Connection and Chat Management Module
Handles all database operations for chat persistence
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure, OperationFailure
from bson import ObjectId

logger = logging.getLogger(__name__)


class MongoDBManager:
    """Manages MongoDB connection and operations for chat persistence"""
    
    def __init__(self, uri: str, db_name: str):
        """
        Initialize MongoDB connection
        
        Args:
            uri: MongoDB connection URI
            db_name: Database name
        """
        self.uri = uri
        self.db_name = db_name
        self.client: Optional[MongoClient] = None
        self.db = None
        self.chats_collection = None
        
    def connect(self):
        """Establish connection to MongoDB"""
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            # Test connection
            self.client.admin.command('ping')
            
            self.db = self.client[self.db_name]
            self.chats_collection = self.db['Chats']
            
            # Create indexes for better performance
            self.chats_collection.create_index([('created_at', DESCENDING)])
            self.chats_collection.create_index('session_id')
            
            logger.info(f"✅ Connected to MongoDB: {self.db_name}")
            return True
            
        except ConnectionFailure as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error connecting to MongoDB: {e}")
            return False
    
    def disconnect(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")
    
    def create_chat_session(self, session_id: str, company_name: str = "New Chat") -> Optional[str]:
        """
        Create a new chat session document
        
        Args:
            session_id: Unique session identifier
            company_name: Name of the company being researched
            
        Returns:
            Document ID as string, or None if failed
        """
        try:
            chat_document = {
                'session_id': session_id,
                'company_name': company_name,
                'messages': [],
                'research_results': None,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'is_research_complete': False
            }
            
            result = self.chats_collection.insert_one(chat_document)
            logger.info(f"✅ Created chat session: {session_id} for company: {company_name}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"❌ Failed to create chat session: {e}")
            return None
    
    def add_message(self, session_id: str, role: str, content: str, 
                    message_type: str = "text", metadata: Optional[Dict] = None) -> bool:
        """
        Add a message to an existing chat session
        
        Args:
            session_id: Session identifier
            role: 'user' or 'assistant'
            content: Message content
            message_type: Type of message (text, research_acknowledgment, etc.)
            metadata: Additional metadata for the message
            
        Returns:
            True if successful, False otherwise
        """
        try:
            message = {
                'role': role,
                'content': content,
                'type': message_type,
                'timestamp': datetime.utcnow().isoformat(),
                'metadata': metadata or {}
            }
            
            result = self.chats_collection.update_one(
                {'session_id': session_id},
                {
                    '$push': {'messages': message},
                    '$set': {'updated_at': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.debug(f"✅ Message added to session {session_id}")
                return True
            else:
                logger.warning(f"⚠️ Session {session_id} not found for message addition")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to add message: {e}")
            return False
    
    def update_company_name(self, session_id: str, company_name: str) -> bool:
        """
        Update the company name for a chat session
        
        Args:
            session_id: Session identifier
            company_name: New company name
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.chats_collection.update_one(
                {'session_id': session_id},
                {
                    '$set': {
                        'company_name': company_name,
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Updated company name to '{company_name}' for session {session_id}")
                return True
            else:
                logger.warning(f"⚠️ Session {session_id} not found for company name update")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to update company name: {e}")
            return False
    
    def save_research_results(self, session_id: str, research_results: Dict) -> bool:
        """
        Save research results to a chat session
        
        Args:
            session_id: Session identifier
            research_results: Complete research/account plan data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.chats_collection.update_one(
                {'session_id': session_id},
                {
                    '$set': {
                        'research_results': research_results,
                        'is_research_complete': True,
                        'updated_at': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Research results saved for session {session_id}")
                return True
            else:
                logger.warning(f"⚠️ Session {session_id} not found for research results")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to save research results: {e}")
            return False
    
    def get_chat_session(self, session_id: str) -> Optional[Dict]:
        """
        Retrieve a chat session by session_id
        
        Args:
            session_id: Session identifier
            
        Returns:
            Chat document as dictionary, or None if not found
        """
        try:
            chat = self.chats_collection.find_one({'session_id': session_id})
            if chat:
                chat['_id'] = str(chat['_id'])  # Convert ObjectId to string
                return chat
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to retrieve chat session: {e}")
            return None
    
    def get_all_chats(self, limit: int = 50) -> List[Dict]:
        """
        Retrieve all chat sessions, sorted by most recent first
        
        Args:
            limit: Maximum number of chats to return
            
        Returns:
            List of chat documents (without messages for efficiency)
        """
        try:
            chats = self.chats_collection.find(
                {},
                {'session_id': 1, 'company_name': 1, 'created_at': 1, 
                 'updated_at': 1, 'is_research_complete': 1}
            ).sort('updated_at', DESCENDING).limit(limit)
            
            chat_list = []
            for chat in chats:
                chat['_id'] = str(chat['_id'])
                chat_list.append(chat)
                
            logger.info(f"✅ Retrieved {len(chat_list)} chat sessions")
            return chat_list
            
        except Exception as e:
            logger.error(f"❌ Failed to retrieve chats: {e}")
            return []
    
    def delete_chat_session(self, session_id: str) -> bool:
        """
        Delete a chat session
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.chats_collection.delete_one({'session_id': session_id})
            
            if result.deleted_count > 0:
                logger.info(f"✅ Deleted chat session: {session_id}")
                return True
            else:
                logger.warning(f"⚠️ Session {session_id} not found for deletion")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to delete chat session: {e}")
            return False
    
    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists in the database
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if exists, False otherwise
        """
        try:
            count = self.chats_collection.count_documents({'session_id': session_id}, limit=1)
            return count > 0
        except Exception as e:
            logger.error(f"❌ Failed to check session existence: {e}")
            return False
    
    def cleanup_stale_new_chats(self, current_session_id: str = None) -> int:
        """
        Delete all chat sessions with name 'New Chat' except the current one
        
        Args:
            current_session_id: Session ID to exclude from deletion (keep current session)
            
        Returns:
            Number of chats deleted
        """
        try:
            # Build query: company_name is "New Chat" and session_id is NOT current
            query = {'is_research_complete': False}
            
            if current_session_id:
                query['session_id'] = {'$ne': current_session_id}
            
            result = self.chats_collection.delete_many(query)
            deleted_count = result.deleted_count
            
            if deleted_count > 0:
                logger.info(f"✅ Cleaned up {deleted_count} stale 'New Chat' sessions")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Failed to cleanup stale chats: {e}")
            return 0


# Global MongoDB manager instance
mongo_manager: Optional[MongoDBManager] = None


def initialize_mongodb(uri: str, db_name: str) -> bool:
    """
    Initialize global MongoDB manager
    
    Args:
        uri: MongoDB connection URI
        db_name: Database name
        
    Returns:
        True if successful, False otherwise
    """
    global mongo_manager
    
    try:
        mongo_manager = MongoDBManager(uri, db_name)
        return mongo_manager.connect()
    except Exception as e:
        logger.error(f"❌ Failed to initialize MongoDB: {e}")
        return False


def get_mongo_manager() -> Optional[MongoDBManager]:
    """Get the global MongoDB manager instance"""
    return mongo_manager
