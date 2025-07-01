"""
Image preprocessing utilities for improved OCR accuracy
"""

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from io import BytesIO
import base64


def enhance_image_for_ocr(image_data: bytes) -> bytes:
    """
    Apply preprocessing to improve OCR accuracy for trading cards
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        Enhanced image bytes
    """
    # Convert bytes to PIL Image
    image = Image.open(BytesIO(image_data))
    
    # Convert to RGB if not already
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Apply enhancement pipeline
    enhanced = apply_enhancement_pipeline(image)
    
    # Convert back to bytes
    output_buffer = BytesIO()
    enhanced.save(output_buffer, format='JPEG', quality=95)
    return output_buffer.getvalue()


def apply_enhancement_pipeline(image: Image.Image) -> Image.Image:
    """Apply a series of enhancements optimized for trading cards"""
    
    # 1. Increase contrast to make text more readable
    contrast_enhancer = ImageEnhance.Contrast(image)
    enhanced = contrast_enhancer.enhance(1.3)  # 30% more contrast
    
    # 2. Slightly increase sharpness for better text definition
    sharpness_enhancer = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness_enhancer.enhance(1.2)  # 20% more sharpness
    
    # 3. Adjust brightness if image is too dark
    brightness_enhancer = ImageEnhance.Brightness(enhanced)
    # Analyze average brightness and adjust if needed
    grayscale = enhanced.convert('L')
    avg_brightness = np.array(grayscale).mean()
    
    if avg_brightness < 120:  # Image is too dark
        brightness_factor = min(1.5, 120 / avg_brightness)
        enhanced = brightness_enhancer.enhance(brightness_factor)
    elif avg_brightness > 200:  # Image is too bright
        brightness_factor = max(0.8, 180 / avg_brightness)
        enhanced = brightness_enhancer.enhance(brightness_factor)
    
    # 4. Apply noise reduction for cleaner text
    enhanced = enhanced.filter(ImageFilter.MedianFilter(size=3))
    
    return enhanced


def preprocess_with_opencv(image_data: bytes) -> bytes:
    """
    Advanced preprocessing using OpenCV for challenging cards
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        Preprocessed image bytes
    """
    # Convert to numpy array
    nparr = np.frombuffer(image_data, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if image is None:
        return image_data  # Return original if can't decode
    
    # Convert to RGB (OpenCV uses BGR)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # Apply advanced preprocessing
    processed = apply_opencv_pipeline(image)
    
    # Convert back to bytes
    _, buffer = cv2.imencode('.jpg', cv2.cvtColor(processed, cv2.COLOR_RGB2BGR))
    return buffer.tobytes()


def apply_opencv_pipeline(image: np.ndarray) -> np.ndarray:
    """Advanced OpenCV preprocessing pipeline"""
    
    # 1. Noise reduction using bilateral filter
    denoised = cv2.bilateralFilter(image, 9, 75, 75)
    
    # 2. Convert to LAB color space for better luminance control
    lab = cv2.cvtColor(denoised, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    
    # 3. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to L channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    
    # 4. Merge back and convert to RGB
    enhanced_lab = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2RGB)
    
    # 5. Unsharp masking for text clarity
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 2.0)
    enhanced = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)
    
    # 6. Ensure values are in valid range
    enhanced = np.clip(enhanced, 0, 255).astype(np.uint8)
    
    return enhanced


def detect_text_regions(image_data: bytes) -> list:
    """
    Detect potential text regions in the image for focused processing
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        List of (x, y, width, height) tuples for text regions
    """
    # Convert to numpy array
    nparr = np.frombuffer(image_data, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if image is None:
        return []
    
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply morphological operations to find text-like regions
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    text_regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        
        # Filter based on size and aspect ratio (typical for text)
        aspect_ratio = w / h if h > 0 else 0
        area = w * h
        
        if (area > 100 and  # Minimum area
            0.2 < aspect_ratio < 20 and  # Text-like aspect ratio
            w > 10 and h > 5):  # Minimum dimensions
            text_regions.append((x, y, w, h))
    
    return text_regions


def adaptive_preprocessing(image_data: bytes, card_era: str = 'modern') -> bytes:
    """
    Apply preprocessing adapted to card era and condition
    
    Args:
        image_data: Raw image bytes
        card_era: 'vintage', 'classic', or 'modern'
        
    Returns:
        Preprocessed image bytes optimized for the card era
    """
    if card_era == 'vintage':
        # Vintage cards often have faded colors and poor contrast
        return preprocess_vintage_card(image_data)
    elif card_era == 'classic':
        # Classic cards may have better quality but still need enhancement
        return preprocess_classic_card(image_data)
    else:
        # Modern cards usually have good quality, light enhancement
        return enhance_image_for_ocr(image_data)


def preprocess_vintage_card(image_data: bytes) -> bytes:
    """Specialized preprocessing for vintage cards (pre-1980)"""
    image = Image.open(BytesIO(image_data))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # More aggressive enhancement for vintage cards
    # 1. Higher contrast boost
    contrast_enhancer = ImageEnhance.Contrast(image)
    enhanced = contrast_enhancer.enhance(1.6)
    
    # 2. Color saturation to bring out faded text
    color_enhancer = ImageEnhance.Color(enhanced)
    enhanced = color_enhancer.enhance(1.3)
    
    # 3. Brightness adjustment for aged cards
    brightness_enhancer = ImageEnhance.Brightness(enhanced)
    enhanced = brightness_enhancer.enhance(1.2)
    
    # 4. Strong sharpening for fuzzy text
    sharpness_enhancer = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness_enhancer.enhance(1.5)
    
    # 5. Noise reduction for print defects
    enhanced = enhanced.filter(ImageFilter.MedianFilter(size=5))
    
    output_buffer = BytesIO()
    enhanced.save(output_buffer, format='JPEG', quality=95)
    return output_buffer.getvalue()


def preprocess_classic_card(image_data: bytes) -> bytes:
    """Specialized preprocessing for classic era cards (1980-2000)"""
    image = Image.open(BytesIO(image_data))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Moderate enhancement for classic cards
    # 1. Moderate contrast boost
    contrast_enhancer = ImageEnhance.Contrast(image)
    enhanced = contrast_enhancer.enhance(1.4)
    
    # 2. Slight sharpness increase
    sharpness_enhancer = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness_enhancer.enhance(1.3)
    
    # 3. Color enhancement for better text visibility
    color_enhancer = ImageEnhance.Color(enhanced)
    enhanced = color_enhancer.enhance(1.1)
    
    # 4. Light noise reduction
    enhanced = enhanced.filter(ImageFilter.MedianFilter(size=3))
    
    output_buffer = BytesIO()
    enhanced.save(output_buffer, format='JPEG', quality=95)
    return output_buffer.getvalue()


def create_high_contrast_version(image_data: bytes) -> bytes:
    """
    Create a high-contrast version specifically for text extraction
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        High-contrast image bytes optimized for text reading
    """
    # Convert to PIL Image
    image = Image.open(BytesIO(image_data))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    
    # Convert to grayscale for better text contrast
    grayscale = image.convert('L')
    
    # Apply histogram equalization for better contrast distribution
    # Convert to numpy for processing
    img_array = np.array(grayscale)
    
    # Apply adaptive histogram equalization
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    equalized = clahe.apply(img_array)
    
    # Convert back to PIL
    enhanced = Image.fromarray(equalized, 'L')
    
    # Apply strong sharpening
    sharpness_enhancer = ImageEnhance.Sharpness(enhanced)
    enhanced = sharpness_enhancer.enhance(2.0)
    
    # Convert back to RGB
    enhanced = enhanced.convert('RGB')
    
    output_buffer = BytesIO()
    enhanced.save(output_buffer, format='JPEG', quality=100)
    return output_buffer.getvalue()