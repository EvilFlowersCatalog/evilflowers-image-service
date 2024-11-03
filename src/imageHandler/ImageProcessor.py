from PIL import Image
from typing import List, Tuple
from models.PaliGemma import PaliGemmaModel

class ImageProcessor:
    def __init__(self):
        pass

    def process_images(self, images: List[Image.Image]) -> List[Tuple[str, str]]:
        return [self.process_image(image) for image in images]

    def process_image(self, image: Image) -> Tuple[str, str]:
        caption = self._create_image_caption(image)
        label = self._create_image_label(image)
        return caption, label

    ##
    # Private functions
    def _create_image_caption(self, image: Image) -> str:
        model = PaliGemmaModel()
        return model.predict(image)

    def _create_image_label(self, image: Image) -> str:
        pass
