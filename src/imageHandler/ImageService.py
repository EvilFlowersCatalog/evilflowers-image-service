from PIL import Image
from typing import List, Tuple

from imageHandler.ImageExtractor import ImageExtractor
from imageHandler.ImageProcessor import ImageProcessor

class ImageHandler:

    _instance = None
    image_extractor: ImageExtractor
    image_processor: ImageProcessor

    def __init__(self, document_path: str):
        if not hasattr(self, "initialized"):
            self.image_extractor = ImageExtractor(document_path)
            self.image_processor = ImageProcessor()
            self.initialized = True
        else:
            return self._instance

    def process_images(self) -> List[Tuple[str, str]]:
        images, page_numbers = self.image_extractor.extract_images()
        predictions = self.image_processor.process_images(images)
        return predictions, page_numbers

    def process_image(self, image: Image.Image) -> Tuple[str, str]:
        return self.image_processor.create_image_label(image)
