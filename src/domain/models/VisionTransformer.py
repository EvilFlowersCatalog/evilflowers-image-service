from PIL import Image
import torch
from transformers import ViTImageProcessor, ViTForImageClassification
from domain.base.ModelInterface import ModelInterface

class VisionTransformerModel(ModelInterface):

    _instance = None
    model: ViTForImageClassification
    processor: ViTImageProcessor

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.initialized = True
            model_id = "google/vit-base-patch16-224"
            self.model = ViTForImageClassification.from_pretrained(model_id).eval()
            self.processor = ViTImageProcessor.from_pretrained(model_id)
        else:
            return self._instance

    def preprocess_data(self):
        pass

    def predict(self, image: Image.Image) -> str:
        inputs = self.processor(images=image.convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            outputs = self.model(**inputs) 
        logits = outputs.logits
        predicted_class_index = logits.argmax(-1).item()
        return self.model.config.id2label[predicted_class_index]
