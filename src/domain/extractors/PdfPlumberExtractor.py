from PIL import Image
from typing import List
from domain.base.ExtractorInterface import ExtractorInterface

class PdfPlumberExtractor(ExtractorInterface):
    def __init__(self, imageResolution: int = 400):
        self._imageResolution = imageResolution

    def extract_image(self, page: Image.Image) -> List[Image.Image]:
        
        extracted_images = []
        images = page.images

        # Save extracted images
        if images:
            for i, image in enumerate(images):
                page_num = image["page_number"]
                page_height = page.height
                image_bbox = (image['x0'], page_height - image['y1'], image['x1'], page_height - image['y0'])
                cropped_page = page.crop(image_bbox)
                image_object = cropped_page.to_image(resolution=self._imageResolution).original
                extracted_images.append(image_object)
                
        return extracted_images