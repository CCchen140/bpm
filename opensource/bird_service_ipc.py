"""
Bird Species Recognition IPC Service
Local inter-process communication service for bird species recognition

Copyright (C) 2024  [Your Name]

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import os
import sys
import json
import logging
import tempfile
import uuid
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class BirdIPCService:
    """
    Local IPC Service for Bird Species Recognition
    
    Uses file-based IPC for communication between processes.
    Designed to be bundled with another application.
    """
    
    def __init__(self, 
                 model_path: str = '31_checkpoint.pth',
                 bird_info_path: str = 'bird_info.json',
                 device: Optional[str] = None,
                 ipc_dir: Optional[str] = None):
        """
        Initialize IPC Service
        
        Args:
            model_path: Path to model checkpoint
            bird_info_path: Path to bird info JSON
            device: Computation device (cuda/cpu)
            ipc_dir: Directory for IPC communication files
        """
        self.model_path = model_path
        self.bird_info_path = bird_info_path
        self.device = device
        
        # Setup IPC directory
        if ipc_dir is None:
            ipc_dir = os.path.join(tempfile.gettempdir(), 'bird_ipc')
        self.ipc_dir = ipc_dir
        os.makedirs(self.ipc_dir, exist_ok=True)
        
        # Request/Response file paths
        self.request_file = os.path.join(self.ipc_dir, 'request.json')
        self.response_file = os.path.join(self.ipc_dir, 'response.json')
        self.lock_file = os.path.join(self.ipc_dir, 'service.lock')
        
        # Service state
        self.running = False
        self.classifier = None
        self.service_thread = None
        
        logger.info(f"IPC Service initialized")
        logger.info(f"IPC Directory: {self.ipc_dir}")
        
    def _load_model(self) -> bool:
        """Load the bird classification model"""
        try:
            from bird_classifier_simple import BirdClassifier
            
            logger.info("Loading model...")
            start_time = time.time()
            
            self.classifier = BirdClassifier(
                model_path=self.model_path,
                bird_info_path=self.bird_info_path,
                device=self.device
            )
            
            elapsed = time.time() - start_time
            logger.info(f"Model loaded in {elapsed:.2f}s")
            logger.info(f"Classes: {self.classifier.num_classes}")
            logger.info(f"Device: {self.classifier.device}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def _is_locked(self) -> bool:
        """Check if service is already running"""
        return os.path.exists(self.lock_file)
    
    def _acquire_lock(self) -> bool:
        """Acquire service lock"""
        try:
            if self._is_locked():
                return False
            
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
            return True
        except Exception as e:
            logger.error(f"Failed to acquire lock: {e}")
            return False
    
    def _release_lock(self):
        """Release service lock"""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
    
    def _read_request(self) -> Optional[Dict]:
        """Read request from IPC file"""
        try:
            if not os.path.exists(self.request_file):
                return None
            
            with open(self.request_file, 'r', encoding='utf-8') as f:
                request = json.load(f)
            
            # Remove request file after reading
            os.remove(self.request_file)
            
            return request
            
        except Exception as e:
            logger.error(f"Failed to read request: {e}")
            return None
    
    def _write_response(self, response: Dict):
        """Write response to IPC file"""
        try:
            response['timestamp'] = datetime.utcnow().isoformat()
            response['pid'] = os.getpid()
            
            with open(self.response_file, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to write response: {e}")
    
    def _process_request(self, request: Dict) -> Dict:
        """Process a single request"""
        try:
            action = request.get('action')
            
            if action == 'predict':
                return self._handle_predict(request)
            elif action == 'info':
                return self._handle_info()
            elif action == 'health':
                return self._handle_health()
            elif action == 'search':
                return self._handle_search(request)
            else:
                return {
                    'success': False,
                    'error': f'Unknown action: {action}'
                }
                
        except Exception as e:
            logger.exception("Error processing request")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _handle_predict(self, request: Dict) -> Dict:
        """Handle prediction request"""
        if self.classifier is None:
            return {'success': False, 'error': 'Model not loaded'}
        
        image_path = request.get('image_path')
        if not image_path or not os.path.exists(image_path):
            return {'success': False, 'error': 'Invalid image path'}
        
        top_k = request.get('top_k', 5)
        min_confidence = request.get('min_confidence', 0.0)
        
        start_time = time.time()
        results = self.classifier.predict(image_path, top_k=top_k)
        elapsed = time.time() - start_time
        
        # Filter by confidence
        filtered_results = [
            r for r in results 
            if r['confidence'] >= min_confidence
        ]
        
        return {
            'success': True,
            'predictions': filtered_results,
            'inference_time_ms': round(elapsed * 1000, 2)
        }
    
    def _handle_info(self) -> Dict:
        """Handle model info request"""
        if self.classifier is None:
            return {'success': False, 'error': 'Model not loaded'}
        
        return {
            'success': True,
            'model': {
                'num_classes': self.classifier.num_classes,
                'device': str(self.classifier.device),
                'bird_info_count': len(self.classifier.bird_info)
            }
        }
    
    def _handle_health(self) -> Dict:
        """Handle health check request"""
        return {
            'success': True,
            'status': 'healthy',
            'model_loaded': self.classifier is not None
        }
    
    def _handle_search(self, request: Dict) -> Dict:
        """Handle species search request"""
        if self.classifier is None:
            return {'success': False, 'error': 'Model not loaded'}
        
        query = request.get('query', '').strip().lower()
        limit = request.get('limit', 10)
        
        if not query:
            return {'success': False, 'error': 'Query is required'}
        
        results = []
        for idx, bird in enumerate(self.classifier.bird_info):
            if any(query in field.lower() for field in bird):
                results.append({
                    'id': idx,
                    'chinese_name': bird[0],
                    'english_name': bird[1],
                    'scientific_name': bird[2]
                })
                if len(results) >= limit:
                    break
        
        return {
            'success': True,
            'query': query,
            'results': results,
            'total': len(results)
        }
    
    def _service_loop(self):
        """Main service loop"""
        logger.info("Service loop started")
        
        while self.running:
            try:
                # Check for request
                request = self._read_request()
                
                if request:
                    logger.debug(f"Processing request: {request.get('action')}")
                    response = self._process_request(request)
                    self._write_response(response)
                
                # Small delay to prevent busy waiting
                time.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error in service loop: {e}")
                time.sleep(0.1)
        
        logger.info("Service loop stopped")
    
    def start(self) -> bool:
        """
        Start the IPC service
        
        Returns:
            True if started successfully, False otherwise
        """
        # Check if already running
        if self._is_locked():
            logger.warning("Service is already running")
            return False
        
        # Acquire lock
        if not self._acquire_lock():
            logger.error("Failed to acquire service lock")
            return False
        
        # Load model
        if not self._load_model():
            self._release_lock()
            return False
        
        # Start service
        self.running = True
        self.service_thread = threading.Thread(target=self._service_loop)
        self.service_thread.daemon = True
        self.service_thread.start()
        
        logger.info("IPC Service started successfully")
        return True
    
    def stop(self):
        """Stop the IPC service"""
        logger.info("Stopping IPC Service...")
        self.running = False
        
        if self.service_thread:
            self.service_thread.join(timeout=5)
        
        self._release_lock()
        
        # Cleanup IPC files
        for f in [self.request_file, self.response_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        
        logger.info("IPC Service stopped")
    
    def is_running(self) -> bool:
        """Check if service is running"""
        return self.running and self._is_locked()


def main():
    """Main entry point"""
    import signal
    
    # Handle signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        if service:
            service.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and start service
    service = BirdIPCService()
    
    if not service.start():
        logger.error("Failed to start service")
        sys.exit(1)
    
    logger.info("Service is running. Press Ctrl+C to stop.")
    
    # Keep main thread alive
    try:
        while service.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()


if __name__ == '__main__':
    main()
