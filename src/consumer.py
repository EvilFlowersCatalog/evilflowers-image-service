from kafka.consumer import DefaultConsumer
from config.consumer_config import consumer_conf, consumer_subscriptions
from imageHandler.ImageService import ImageHandler
import json

from elvira_elasticsearch_client import ElasticsearchClient 

class MyConsumer(DefaultConsumer):
    def msg_process(self, msg):
        
        json_string = msg.value().decode('utf-8')
        json_object = json.loads(json_string)
        
        image_handler = ImageHandler(json_object["document_path"])
        image_predictions, page_numbers = image_handler.process_images()
        
        print(image_predictions)

        client = ElasticsearchClient()
        client.save_extracted_images_to_elasticsearch(document_id=json_object["document_id"],
                                                    images_data=image_predictions,
                                                    page_numbers=page_numbers)
if __name__ == "__main__":
    consumer = MyConsumer(consumer_conf, consumer_subscriptions)
    consumer.start_consume()
    print("Consumer started")
