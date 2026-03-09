"""
Firebase Firestore Initialization and Configuration
Handles secure connection to Firebase with proper error handling and logging
"""

import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud.firestore_v1.base_client import BaseClient
import json
import os
from typing import Optional, Dict, Any
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class FirebaseConfig:
    """Configuration dataclass for Firebase settings"""
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    token_uri: str = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url: str = "https://www.googleapis.com/oauth2/v1/certs"
    client_x509_cert_url: str = ""

class FirebaseManager:
    """Singleton manager for Firebase Firestore connections"""
    
    _instance: Optional['FirebaseManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.db: Optional[BaseClient] = None
            self.bucket = None
            self._initialized = True
    
    def initialize(self, config_path: str = "config/firebase-service-account.json") -> bool:
        """
        Initialize Firebase Admin SDK with proper error handling
        
        Args:
            config_path: Path to Firebase service account JSON file
            
        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            # Verify file exists
            if not os.path.exists(config_path):
                logger.error(f"Firebase config file not found at: {config_path}")
                logger.info("Please create Firebase project and download service account key from:")
                logger.info("https://console.firebase.google.com/")
                return False
            
            # Load and validate config
            with open(config_path, 'r') as f:
                config_data = json.load(f)
            
            # Verify required fields
            required_fields = ['project_id', 'private_key_id', 'private_key', 'client_email']
            for field in required_fields:
                if field not in config_data:
                    logger.error(f"Missing required field in Firebase config: {field}")
                    return False
            
            # Initialize Firebase app (check if already initialized)
            if not firebase_admin._apps:
                cred = credentials.Certificate(config_path)
                firebase_admin.initialize_app(cred, {
                    'storageBucket': f"{config_data['project_id']}.appspot.com"
                })
                logger.info("Firebase Admin SDK initialized successfully")
            else:
                logger.info("Firebase Admin SDK already initialized")
            
            # Initialize Firestore and Storage
            self.db = firestore.client()
            self.bucket = storage.bucket()
            
            # Initialize collections
            self._initialize_collections()
            
            # Test connection
            test_doc = self.db.collection('system_health').document('connection_test')
            test_doc.set({
                'timestamp': datetime.now().isoformat(),
                'status': 'connected',
                'version': '1.0.0'
            })
            logger.info("Firebase connection test successful")
            
            return True
            
        except FileNotFoundError as e:
            logger.error(f"Config file not found: {e}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            return False
        except ValueError as e:
            logger.error(f"Invalid Firebase credentials: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}", exc_info=True)
            return False
    
    def _initialize_collections(self) -> None:
        """Initialize required Firestore collections if they don't exist"""
        collections = [
            'market_data',
            'signals',
            'trades',
            'performance_metrics',
            'system_health',
            'historical_arb_data',
            'ml_models',
            'configuration',
            'risk_limits'
        ]
        
        for collection in collections:
            # Firestore doesn't require explicit collection creation
            # We'll create a dummy document to ensure collection exists
            try:
                test_ref = self.db.collection(collection).document('_initialized')
                test_ref.set({
                    'created_at': datetime.now().isoformat(),
                    'purpose': f'Initialization marker for {collection}'
                })
                logger.debug(f"Collection initialized: {collection}")
            except Exception as e:
                logger.error(f"Failed to initialize collection {collection}: {e}")
    
    def get_db(self) -> BaseClient:
        """Get Firestore database instance with validation"""
        if self.db is None:
            raise RuntimeError("Firebase not initialized. Call initialize() first.")
        return self.db
    
    def get_bucket(self):
        """Get Cloud Storage bucket instance with validation"""
        if self.bucket is None:
            raise RuntimeError("Firebase Storage not initialized. Call initialize() first.")
        return self.bucket
    
    def write_trade(self, trade_data: Dict[str, Any]) -> str:
        """
        Write trade data to Firestore with validation
        
        Args:
            trade_data: Dictionary containing trade information
            
        Returns:
            str: Document ID of the created trade
        """
        try:
            # Validate required fields
            required_fields = ['timestamp', 'pair', 'side', 'size', 'entry_price']
            for field in required_fields:
                if field not in trade_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Add metadata
            trade_data['recorded_at'] = datetime.now().isoformat()
            trade_data['trade_id'] = hashlib.sha256(
                f"{trade_data['timestamp']}_{trade_data['pair']}".encode()
            ).hexdigest()[:16]
            
            # Write to Firestore
            trade_ref = self.db.collection('trades').document(trade_data['trade_id'])
            trade_ref.set(trade_data)
            
            logger.info(f"Trade recorded: {trade_data['trade_id']}")
            return trade_data['trade_id']
            
        except Exception as e:
            logger.error(f"Failed to write trade: {e}", exc_info=True)
            raise

# Global instance
firebase_manager = FirebaseManager()

def initialize_firebase(config_path: str = "config/firebase-service-account.json") -> bool:
    """Convenience function to initialize Firebase"""
    return firebase_manager.initialize(config_path)

if __name__ == "__main__":
    # Test initialization
    if initialize_firebase():
        logger.info("Firebase setup completed successfully")
    else:
        logger.error("Firebase setup failed")