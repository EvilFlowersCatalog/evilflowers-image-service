from PIL import Image
from image_description.imageHandler.ImageExtractor import ImageExtractor
from image_description.imageHandler.ImageProcessor import ImageProcessor
from typing import List, Tuple


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
        images = self.image_extractor.load_images()
        return [self.image_processor.create_image_label(image) for image in images]

    def process_image(self, image: Image.Image) -> Tuple[str, str]:
        return self.image_processor.create_image_label(image)
