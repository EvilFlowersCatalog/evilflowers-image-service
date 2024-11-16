from PIL import Image
import torch
from transformers import AutoImageProcessor, ResNetForImageClassification
from domain.base.ModelInterface import ModelInterface

class ResNet50Model(ModelInterface):

    _instance = None
    model: ResNetForImageClassification
    processor: AutoImageProcessor

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.initialized = True
            model_id = "microsoft/resnet-50"
            self.model = ResNetForImageClassification.from_pretrained(model_id).eval()
            self.processor = AutoImageProcessor.from_pretrained(model_id)
        else:
            return self._instance

    def preprocess_data(self):
        pass

    def predict(self, image: Image.Image) -> str:
        inputs = self.processor(image.convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            outputs = self.model(**inputs) 
        logits = outputs.logits 
        predicted_class_index = logits.argmax(-1).item()
        return self.model.config.id2label[predicted_class_index]
  
