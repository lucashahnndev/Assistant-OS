import os
from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import logging
from PIL import Image
import io

router = APIRouter()
logger = logging.getLogger("AssetsRoute")

def get_static_dir(request: Request) -> str:
    """Resolve the static directory path."""
    try:
        kernel = getattr(request.app.state, "kernel", None)
        if kernel and hasattr(kernel, "config_manager"):
            base_data_dir = kernel.config_manager.get_data_dir()
        else:
            base_data_dir = os.path.join(os.getcwd(), "data")
    except Exception:
        base_data_dir = os.path.join(os.getcwd(), "data")
        
    static_dir = os.path.join(base_data_dir, "static")
    os.makedirs(static_dir, exist_ok=True)
    return static_dir

def process_and_save_icon(img: Image.Image, size: tuple, filepath: str, format: str = "PNG"):
    """Resize image to target size while preserving aspect ratio and padding if necessary, then save."""
    # Convert to RGBA to ensure transparency is supported
    img = img.convert("RGBA")
    
    # Calculate aspect ratio preserving size
    target_width, target_height = size
    img_ratio = img.width / img.height
    target_ratio = target_width / target_height
    
    if target_ratio > img_ratio:
        # Target is wider than image
        new_height = target_height
        new_width = int(new_height * img_ratio)
    else:
        # Target is taller than image
        new_width = target_width
        new_height = int(new_width / img_ratio)
        
    # Resize the image smoothly
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # Create a new transparent background image of the target size
    new_img = Image.new("RGBA", size, (0, 0, 0, 0))
    
    # Paste the resized image into the center
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    new_img.paste(resized_img, (paste_x, paste_y), resized_img)
    
    # Save it
    new_img.save(filepath, format=format)

@router.post("/api/assets/logo")
async def upload_logo(request: Request, file: UploadFile = File(...)):
    """
    Receives a logo image, processes it into multiple required PWA formats,
    and saves them to the static directory.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    try:
        content = await file.read()
        img = Image.open(io.BytesIO(content))
        
        static_dir = get_static_dir(request)
        
        # 1. PWA Manifest Icons (192x192 and 512x512)
        process_and_save_icon(img, (192, 192), os.path.join(static_dir, "logo-192x192.png"))
        process_and_save_icon(img, (512, 512), os.path.join(static_dir, "logo-512x512.png"))
        
        # 2. Apple Touch Icon (180x180)
        process_and_save_icon(img, (180, 180), os.path.join(static_dir, "apple-touch-icon.png"))
        
        # 3. Favicon (32x32)
        process_and_save_icon(img, (32, 32), os.path.join(static_dir, "favicon.ico"), format="ICO")
        
        return JSONResponse(content={"status": "success", "message": "Logos generated successfully."})
    except Exception as e:
        logger.error(f"Error processing logo upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")
