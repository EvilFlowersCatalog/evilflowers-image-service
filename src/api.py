from fastapi import FastAPI, UploadFile, File
import os

from imageHandler.ImageService import ImageHandler

app = FastAPI(
    title="EvilFlowers Image Service",
    description="Service for processing and analyzing images",
    version="1.0.0"
)
    
@app.post("/process_images")
async def process_images(file: UploadFile = File(...)):
    # Save uploaded file temporarily
    temp_path = f"temp/{file.filename}"
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        
    with open(temp_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    image_handler = ImageHandler(temp_path)
    return image_handler.process_images()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
