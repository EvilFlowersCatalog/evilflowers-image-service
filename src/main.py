from imageHandler.ImageHandler import ImageHandler


def main():
    document_path = "../test_data/doc1.pdf"
    image_handler = ImageHandler(document_path)
    image_handler.process_images()

if __name__ == "__main__":
    main()
