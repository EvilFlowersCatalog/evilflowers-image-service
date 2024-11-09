from PIL import Image
from typing import List
from abc import ABC, abstractmethod

class ExtractorInterface(ABC):
    @abstractmethod
    def extract_image(self, page: Image.Image) -> List[Image.Image]:
        pass
