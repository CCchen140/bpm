# Bird Species Recognition IPC Service

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

A local inter-process communication (IPC) service for bird species recognition using deep learning. Designed to be bundled with other applications.

## Overview

This project provides a **local-only** bird species recognition service that communicates via file-based IPC. It's designed to be bundled with another application and does not expose any network interfaces.

## Features

- 🐦 **10,000+ Bird Species**: Supports recognition of over 10,000 bird species worldwide
- 🔒 **Local Only**: No network exposure, file-based IPC communication
- 🚀 **Easy Integration**: Simple Python API for integration with other applications
- 📦 **Bundle Ready**: Designed to be packaged with other software
- 🔄 **Auto Service Management**: Automatic service lifecycle management
- 🔍 **Species Search**: Search bird species by name

## Architecture

```
┌─────────────────┐      File-based IPC      ┌─────────────────┐
│  Your           │  ┌──────────────────┐   │  Bird           │
│  Application    │◄─┤ request.json     ├──►│  Recognition    │
│                 │  │ response.json    │   │  Service        │
│  (Client)       │◄─┤ service.lock     │   │  (Subprocess)   │
└─────────────────┘  └──────────────────┘   └─────────────────┘
```

## Project Structure

```
.
├── bird_service_ipc.py      # IPC Service (runs as subprocess)
├── bird_client_ipc.py       # IPC Client (use this in your app)
├── bird_classifier_simple.py # Model wrapper
├── bird_info.json           # Bird species database
├── 31_checkpoint.pth/       # Model checkpoint (directory)
├── requirements.txt         # Python dependencies
├── LICENSE                  # GPL 3.0 License
└── README.md               # This file
```

## Quick Start

### Prerequisites

- Python 3.11+
- PyTorch
- Model checkpoint file (`31_checkpoint.pth` or `28_checkpoint.pth`)
- Bird info database (`bird_info.json`)

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Place model files in the project directory:
   - `31_checkpoint.pth/` (or `28_checkpoint.pth/`)
   - `bird_info.json`

### Usage

#### Method 1: High-Level Interface (Recommended)

```python
from bird_client_ipc import BirdRecognizer

# Initialize recognizer (auto-starts service)
with BirdRecognizer() as recognizer:
    # Recognize a bird image
    predictions = recognizer.recognize('path/to/bird.jpg', top_k=5)
    
    for pred in predictions:
        print(f"{pred['chinese_name']}: {pred['confidence']:.2%}")
    
    # Search species
    results = recognizer.search('麻雀', limit=5)
    for r in results:
        print(f"{r['chinese_name']} ({r['english_name']})")
```

#### Method 2: Low-Level Client

```python
from bird_client_ipc import BirdIPCClient

# Create client
client = BirdIPCClient()

# Start service manually
client.start_service()

# Check health
health = client.health_check()
print(health)

# Predict
result = client.predict('path/to/bird.jpg', top_k=5)
print(result['predictions'])

# Stop service
client.stop_service()
```

## API Reference

### BirdRecognizer (High-Level)

| Method | Description |
|--------|-------------|
| `recognize(image_path, top_k=5)` | Recognize bird species in image |
| `search(query, limit=10)` | Search species by name |
| `close()` | Clean up resources |

### BirdIPCClient (Low-Level)

| Method | Description |
|--------|-------------|
| `start_service()` | Start the IPC service subprocess |
| `stop_service()` | Stop the IPC service |
| `health_check()` | Check service health |
| `get_model_info()` | Get model information |
| `predict(image_path, top_k=5)` | Predict bird species |
| `search_species(query, limit=10)` | Search species |

## Bundling with Your Application

### Directory Structure

```
your_application/
├── your_app.py
├── bird_recognition/          # Copy this entire folder
│   ├── bird_service_ipc.py
│   ├── bird_client_ipc.py
│   ├── bird_classifier_simple.py
│   ├── bird_info.json
│   ├── 31_checkpoint.pth/
│   └── __init__.py
└── ...
```

### Integration Example

```python
# In your application
import sys
sys.path.insert(0, 'bird_recognition')

from bird_client_ipc import BirdRecognizer

class YourApp:
    def __init__(self):
        self.bird_recognizer = BirdRecognizer(
            model_path='bird_recognition/31_checkpoint.pth',
            bird_info_path='bird_recognition/bird_info.json'
        )
    
    def identify_bird(self, image_path):
        predictions = self.bird_recognizer.recognize(image_path, top_k=3)
        return predictions
    
    def cleanup(self):
        self.bird_recognizer.close()
```

## IPC Communication

The service uses file-based IPC in the system's temp directory:

- **Request**: `{temp}/bird_ipc/request.json`
- **Response**: `{temp}/bird_ipc/response.json`
- **Lock**: `{temp}/bird_ipc/service.lock`

### Request Format

```json
{
  "action": "predict",
  "image_path": "/path/to/image.jpg",
  "top_k": 5,
  "min_confidence": 0.0
}
```

### Response Format

```json
{
  "success": true,
  "predictions": [
    {
      "chinese_name": "麻雀",
      "english_name": "Eurasian Tree Sparrow",
      "scientific_name": "Passer montanus",
      "confidence": 0.9567
    }
  ],
  "inference_time_ms": 125.43,
  "timestamp": "2024-01-15T10:30:00",
  "pid": 12345
}
```

## Model Information

- **Architecture**: ResNet34
- **Input Size**: 224x224 pixels
- **Output Classes**: 11,000 bird species
- **Training Framework**: PyTorch

## Requirements

```
torch>=2.0.0
torchvision>=0.15.0
Pillow>=10.0.0
numpy>=1.24.0
```

## License

This project is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) file for details.

### GPL 3.0 Summary

- ✅ **Free to use** for personal and commercial purposes
- ✅ **Free to modify** and create derivative works
- ✅ **Free to distribute** copies
- 📋 **Must disclose source** when distributing
- 📋 **Must use same license** for derivative works
- 📋 **Must state changes** made to the code

## Disclaimer

This software is provided for educational and research purposes. Bird identification accuracy may vary depending on image quality and species similarity.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and feature requests, please use the GitHub Issues page.

---

**Note**: This is a local-only service. It does not expose any network interfaces and is designed to be used within a single machine via inter-process communication.
