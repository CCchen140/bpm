"""
Bird Species Recognition IPC Client
Local inter-process communication client for bird species recognition

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
import time
import tempfile
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BirdIPCClient:
    """
    Local IPC Client for Bird Species Recognition
    
    Communicates with bird_service_ipc.py via file-based IPC.
    Designed to be bundled with another application.
    """
    
    def __init__(self, ipc_dir: Optional[str] = None, timeout: float = 30.0):
        """
        Initialize IPC Client
        
        Args:
            ipc_dir: Directory for IPC communication files
            timeout: Maximum wait time for response (seconds)
        """
        if ipc_dir is None:
            ipc_dir = os.path.join(tempfile.gettempdir(), 'bird_ipc')
        self.ipc_dir = ipc_dir
        
        self.request_file = os.path.join(self.ipc_dir, 'request.json')
        self.response_file = os.path.join(self.ipc_dir, 'response.json')
        self.lock_file = os.path.join(self.ipc_dir, 'service.lock')
        
        self.timeout = timeout
        self.service_process = None
        
        logger.info(f"IPC Client initialized")
        logger.info(f"IPC Directory: {self.ipc_dir}")
    
    def is_service_running(self) -> bool:
        """Check if service is running"""
        return os.path.exists(self.lock_file)
    
    def start_service(self, 
                     model_path: str = '31_checkpoint.pth',
                     bird_info_path: str = 'bird_info.json',
                     device: Optional[str] = None) -> bool:
        """
        Start the IPC service as a subprocess
        
        Args:
            model_path: Path to model checkpoint
            bird_info_path: Path to bird info JSON
            device: Computation device
            
        Returns:
            True if started successfully
        """
        if self.is_service_running():
            logger.info("Service is already running")
            return True
        
        try:
            # Get the directory of this script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            service_script = os.path.join(script_dir, 'bird_service_ipc.py')
            
            # Prepare environment
            env = os.environ.copy()
            if device:
                env['DEVICE'] = device
            
            # Start service as subprocess
            logger.info("Starting IPC service...")
            self.service_process = subprocess.Popen(
                [sys.executable, service_script],
                cwd=script_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            # Wait for service to start
            start_time = time.time()
            while not self.is_service_running():
                if time.time() - start_time > 60:  # 60 second timeout
                    logger.error("Service failed to start within timeout")
                    return False
                time.sleep(0.5)
            
            logger.info("IPC Service started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start service: {e}")
            return False
    
    def stop_service(self):
        """Stop the IPC service"""
        if self.service_process:
            logger.info("Stopping IPC service...")
            self.service_process.terminate()
            try:
                self.service_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.service_process.kill()
            self.service_process = None
            logger.info("IPC Service stopped")
    
    def _send_request(self, request: Dict) -> bool:
        """Send request to service"""
        try:
            # Wait for any existing response to be consumed
            if os.path.exists(self.response_file):
                try:
                    os.remove(self.response_file)
                except:
                    pass
            
            # Write request
            with open(self.request_file, 'w', encoding='utf-8') as f:
                json.dump(request, f, ensure_ascii=False)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send request: {e}")
            return False
    
    def _wait_for_response(self) -> Optional[Dict]:
        """Wait for response from service"""
        start_time = time.time()
        
        while time.time() - start_time < self.timeout:
            try:
                if os.path.exists(self.response_file):
                    with open(self.response_file, 'r', encoding='utf-8') as f:
                        response = json.load(f)
                    
                    # Remove response file after reading
                    try:
                        os.remove(self.response_file)
                    except:
                        pass
                    
                    return response
                    
            except Exception as e:
                logger.error(f"Error reading response: {e}")
            
            time.sleep(0.01)  # Small delay
        
        logger.error(f"Timeout waiting for response ({self.timeout}s)")
        return None
    
    def _call(self, request: Dict) -> Dict:
        """Make an IPC call"""
        if not self.is_service_running():
            return {'success': False, 'error': 'Service not running'}
        
        if not self._send_request(request):
            return {'success': False, 'error': 'Failed to send request'}
        
        response = self._wait_for_response()
        if response is None:
            return {'success': False, 'error': 'Timeout waiting for response'}
        
        return response
    
    def health_check(self) -> Dict:
        """Check service health"""
        return self._call({'action': 'health'})
    
    def get_model_info(self) -> Dict:
        """Get model information"""
        return self._call({'action': 'info'})
    
    def predict(self, 
                image_path: str, 
                top_k: int = 5,
                min_confidence: float = 0.0) -> Dict:
        """
        Predict bird species from image
        
        Args:
            image_path: Path to image file
            top_k: Number of predictions to return
            min_confidence: Minimum confidence threshold
            
        Returns:
            Prediction results
        """
        return self._call({
            'action': 'predict',
            'image_path': image_path,
            'top_k': top_k,
            'min_confidence': min_confidence
        })
    
    def search_species(self, query: str, limit: int = 10) -> Dict:
        """
        Search bird species by name
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            Search results
        """
        return self._call({
            'action': 'search',
            'query': query,
            'limit': limit
        })


class BirdRecognizer:
    """
    High-level bird recognition interface
    
    Automatically manages service lifecycle
    """
    
    def __init__(self,
                 model_path: str = '31_checkpoint.pth',
                 bird_info_path: str = 'bird_info.json',
                 device: Optional[str] = None,
                 auto_start: bool = True):
        """
        Initialize Bird Recognizer
        
        Args:
            model_path: Path to model checkpoint
            bird_info_path: Path to bird info JSON
            device: Computation device
            auto_start: Automatically start service if not running
        """
        self.model_path = model_path
        self.bird_info_path = bird_info_path
        self.device = device
        self.auto_start = auto_start
        
        self.client = BirdIPCClient()
        self._service_started_by_us = False
        
        if auto_start and not self.client.is_service_running():
            self._start_service()
    
    def _start_service(self) -> bool:
        """Start the recognition service"""
        success = self.client.start_service(
            model_path=self.model_path,
            bird_info_path=self.bird_info_path,
            device=self.device
        )
        if success:
            self._service_started_by_us = True
        return success
    
    def recognize(self, 
                  image_path: str, 
                  top_k: int = 5) -> List[Dict]:
        """
        Recognize bird species in image
        
        Args:
            image_path: Path to image file
            top_k: Number of predictions to return
            
        Returns:
            List of predictions with confidence scores
        """
        result = self.client.predict(image_path, top_k=top_k)
        
        if result.get('success'):
            return result.get('predictions', [])
        else:
            logger.error(f"Recognition failed: {result.get('error')}")
            return []
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search bird species
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching species
        """
        result = self.client.search_species(query, limit=limit)
        
        if result.get('success'):
            return result.get('results', [])
        else:
            logger.error(f"Search failed: {result.get('error')}")
            return []
    
    def close(self):
        """Clean up resources"""
        if self._service_started_by_us:
            self.client.stop_service()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Example usage
if __name__ == '__main__':
    # Example 1: Using high-level interface
    print("=" * 50)
    print("Example 1: High-level interface")
    print("=" * 50)
    
    with BirdRecognizer() as recognizer:
        # Check if service is ready
        info = recognizer.client.get_model_info()
        if info.get('success'):
            print(f"Model loaded: {info['model']['num_classes']} classes")
        
        # Recognize image (replace with actual path)
        # predictions = recognizer.recognize('path/to/bird.jpg', top_k=5)
        # for pred in predictions:
        #     print(f"{pred['chinese_name']}: {pred['confidence']:.2%}")
        
        # Search species
        results = recognizer.search('麻雀', limit=5)
        print(f"\nSearch results for '麻雀':")
        for r in results:
            print(f"  - {r['chinese_name']} ({r['english_name']})")
    
    # Example 2: Using low-level client
    print("\n" + "=" * 50)
    print("Example 2: Low-level client")
    print("=" * 50)
    
    client = BirdIPCClient()
    
    # Start service
    if client.start_service():
        print("Service started")
        
        # Health check
        health = client.health_check()
        print(f"Health: {health}")
        
        # Get model info
        info = client.get_model_info()
        print(f"Model info: {info}")
        
        # Stop service
        client.stop_service()
        print("Service stopped")
