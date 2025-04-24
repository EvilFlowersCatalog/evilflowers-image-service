from kafka.consumer import DefaultConsumer
from config.consumer_config import consumer_conf, consumer_subscriptions
from imageHandler.ImageService import ImageHandler
import json

class MyConsumer(DefaultConsumer):
    def msg_process(self, msg):
        
        json_string = msg.value().decode('utf-8')
        json_object = json.loads(json_string)
        
        image_handler = ImageHandler(json_object["document_path"])
        image_predictions = image_handler.process_images()
        
        print(image_predictions)

if __name__ == "__main__":
    consumer = MyConsumer(consumer_conf, consumer_subscriptions)
    consumer.start_consume()
    print("Consumer started")
