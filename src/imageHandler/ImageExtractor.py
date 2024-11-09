from PIL import Image
from typing import List
import os
import pdfplumber

from config.Config import Config
from domain.base.ExtractorInterface import ExtractorInterface
from domain.extractors.PdfPlumberExtractor import PdfPlumberExtractor

class ImageExtractor:

    config = Config()
    _document_path: str
    _extractor: ExtractorInterface
    images: List[Image.Image]

    def __init__(self, document_path: str):
        self._validate(document_path)
        self._document_path = document_path
        self._extractor = self._load_extractor()

    def set_document_path(self, document_path: str):
        self._document_path = document_path

    def extract_image(self, page: Image.Image, imageResolution: int = 400) -> List[Image.Image]:
        
        extracted_images = []
        images = page.images

        # Save extracted images
        if images:
            for i, image in enumerate(images):
                page_num = image["page_number"]
                page_height = page.height
                image_bbox = (image['x0'], page_height - image['y1'], image['x1'], page_height - image['y0'])
                cropped_page = page.crop(image_bbox)
                image_object = cropped_page.to_image(resolution=imageResolution).original
                extracted_images.append(image_object)
                
        return extracted_images


    def extract_images(self) -> List[Image.Image]:
        doc, pages = self._load_document()
        all_images = []
        for page in pages:
            all_images.extend(self._extractor.extract_image(page))
        self.images = all_images

        doc.close()
        return all_images

    ##
    # Private functions
    def _load_document(self) -> List[Image.Image]:
        doc = pdfplumber.open(self._document_path)
        return doc, doc.pages
        # return convert_from_path(self.document_path)
    
    def _validate(self, document_path: str):
        assert os.path.exists(
            document_path
        ), f"Document path did not found: {document_path}"

    def _load_extractor(self):
        if self.config.get_config()['EXTRACTOR_MODEL'] == 'PdfPlumber':
            extractor = PdfPlumberExtractor()
        else:
            raise ValueError(f"Extractor type {self.config.get_config()['EXTRACTOR_MODEL']} not supported")
        return extractor
