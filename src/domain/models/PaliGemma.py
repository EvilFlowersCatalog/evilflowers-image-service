from PIL import Image
import torch
from transformers import PaliGemmaForConditionalGeneration, AutoProcessor
from domain.base.ModelInterface import ModelInterface

class PaliGemmaModel(ModelInterface):

    _instance = None
    model: PaliGemmaForConditionalGeneration
    processor: AutoProcessor


    def __init__(self):
        if not hasattr(self, "initialized"):
            self.initialized = True
            model_id = "google/paligemma-3b-mix-224"
            self.model = PaliGemmaForConditionalGeneration.from_pretrained(model_id).eval()
            self.processor = AutoProcessor.from_pretrained(model_id)
        else:
            return self._instance


    def preprocess_data(self):
        pass


    def predict(self, image: Image.Image) -> str:
        # notebook_login()]

        prompt = "caption en"
        model_inputs = self.processor(text=prompt, images=image, return_tensors="pt")
        input_len = model_inputs["input_ids"].shape[-1]

        with torch.inference_mode():
            generation = self.model.generate(**model_inputs, max_new_tokens=100, do_sample=False)
            generation = generation[0][input_len:]
            decoded = self.processor.decode(generation, skip_special_tokens=True)

        return decoded
    
