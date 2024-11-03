from PIL import Image
from typing import List
from pdf2image import convert_from_path
import pytesseract
import os


class ImageExtractor:

    _document_path: str
    images: List[Image.Image]

    def __init__(self, document_path: str):
        self._validate()
        self.document_path = document_path

    def set_document_path(self, document_path: str):
        self.document_path = document_path

    def extract_image(self, page: Image.Image) -> List[Image.Image]:
        # Use pytesseract to find image bounding boxes
        image_data = pytesseract.image_to_data(
            page, output_type=pytesseract.Output.DICT
        )

        extracted_images = []
        for i, conf in enumerate(image_data["conf"]):
            if (
                conf == "-1"
            ):  # '-1' confidence usually indicates a non-text area, potentially an image
                left = image_data["left"][i]
                top = image_data["top"][i]
                width = image_data["width"][i]
                height = image_data["height"][i]

                # Crop the image
                cropped_image = page.crop((left, top, left + width, top + height))
                extracted_images.append(cropped_image)

        return extracted_images

    def extract_images(self) -> List[Image.Image]:
        pages = self._load_document()
        all_images = []
        for page in pages:
            all_images.extend(self.extract_image(page))
        self.images = all_images
        return all_images

    ##
    # Private functions
    def _load_document(self) -> List[Image.Image]:
        return convert_from_path(self.document_path)

    def _validate(self, document_path: str):
        assert os.path.exists(
            document_path
        ), f"Document path did not found: {document_path}"
