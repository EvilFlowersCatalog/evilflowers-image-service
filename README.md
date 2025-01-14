# EvilFlowers Image Service

A Python microservice that extracts and analyzes images from PDF documents using state-of-the-art AI models for image captioning and classification.

# Installation

### Install dependencies
```bash
make install
```
or

```bash
pip install -r requirements.txt 
```

## Run the script

### Run the script with Makefile
```
make run
```

### Run the script directly
```
python src/main.py
```

# Project Structure

```
.
├── Dockerfile
├── Makefile
├── README.md
├── requirements.txt
├── .gitignore
└── src/
├── main.py
├── api.py
├── config/
│ └── Config.py
├── domain/
│ ├── base/
│ │ ├── ExtractorInterface.py
│ │ └── ModelInterface.py
│ ├── extractors/
│ │ └── PdfPlumberExtractor.py
│ └── models/
│ ├── PaliGemma.py
│ ├── ResNet50.py
│ └── VisionTransformer.py
└── imageHandler/
├── ImageExtractor.py
├── ImageProcessor.py
└── ImageService.py
```

## Architecture Overview

### Core Components

#### 1. ImageService
- Main orchestrator that coordinates image extraction and processing
- Implements singleton pattern
- Manages workflow between extraction and processing

#### 2. ImageExtractor
- Extracts images from PDF documents using PdfPlumber
- Validates document paths
- Manages image resolution

#### 3. ImageProcessor
- Image captioning using PaliGemma model
- Image classification using Vision Transformer or ResNet50
- Configurable model selection

### Models

#### 1. PaliGemma
- Image captioning model
- Generates descriptive captions for images
- Uses google/paligemma-3b-mix-224

#### 2. VisionTransformer
- Image classification model
- Classifies images using ViT architecture
- Uses google/vit-base-patch16-224

#### 3. ResNet50
- Alternative image classifier
- Uses microsoft/resnet-50
- Provides robust image classification

### API Endpoints

FastAPI server exposing:

- POST `/process_images`
  - Accepts PDF file uploads
  - Returns list of image captions and classifications

## Configuration

Environment variables (via .env):
- `CAPTIONING_MODEL`: Select image captioning model
- `LABELING_MODEL`: Select image classification model
- `EXTRACTOR_MODEL`: Select PDF extraction method

## Docker Support

Containerized deployment with:
- Python 3.12 base image
- FastAPI server exposed on port 8000
- Temporary file storage for uploads
- All dependencies pre-installed

## Requirements

- Python 3.12
- pip
- make
- Key dependencies:
  - FastAPI
  - pdfplumber
  - Pillow
  - PyTorch
  - Transformers
  - python-dotenv
