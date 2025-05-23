from imageHandler.ImageService import ImageHandler


def main():
    document_path = "test_data/doc1.pdf"
    image_handler = ImageHandler(document_path)
    return image_handler.process_images()

if __name__ == "__main__":
    predictions, page_numbers = main()
    print(predictions)
    print(page_numbers)