"""
Image enhancement module for trading card processing.
"""

import cv2
import numpy as np


# Optimal settings for AI analysis
TARGET_WIDTH = 1024
TARGET_HEIGHT = 1400


def reduce_noise(img):
    """Apply noise reduction while preserving text and detail"""
    return cv2.bilateralFilter(img, 9, 75, 75)


def enhance_contrast(img):
    """Enhanced contrast optimization for AI text recognition"""
    # Convert to LAB color space and apply CLAHE
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # More aggressive CLAHE for better text clarity
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    merged = cv2.merge((cl, a, b))
    result = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    
    # Additional gamma correction for optimal brightness
    gamma = 1.2
    lookup_table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in np.arange(0, 256)]).astype("uint8")
    return cv2.LUT(result, lookup_table)


def sharpen_image(img):
    """Apply unsharp masking for crisp text and details"""
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    return cv2.filter2D(img, -1, kernel)


def color_correct(img):
    """Improve color accuracy and white balance"""
    # Convert to LAB for better color correction
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    # Auto white balance
    l = cv2.normalize(l, None, 0, 255, cv2.NORM_MINMAX)
    
    merged = cv2.merge((l, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def resize_for_analysis(img):
    """Resize to optimal dimensions for AI analysis"""
    h, w = img.shape[:2]
    aspect_ratio = w / h
    
    # Maintain aspect ratio while targeting optimal size
    if aspect_ratio > (TARGET_WIDTH / TARGET_HEIGHT):
        # Width is limiting factor
        new_width = TARGET_WIDTH
        new_height = int(TARGET_WIDTH / aspect_ratio)
    else:
        # Height is limiting factor
        new_height = TARGET_HEIGHT
        new_width = int(TARGET_HEIGHT * aspect_ratio)
    
    return cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)


def detect_card_border(image):
    """Detect card borders for perspective correction"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blur, 50, 150)

    contours, _ = cv2.findContours(
        edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    card_contour = sorted(contours, key=cv2.contourArea, reverse=True)[0]
    peri = cv2.arcLength(card_contour, True)
    approx = cv2.approxPolyDP(card_contour, 0.02 * peri, True)

    if len(approx) == 4:
        return np.squeeze(approx)
    else:
        return None


def four_point_transform(image, pts):
    """Apply perspective correction to straighten card"""
    # order points: top-left, top-right, bottom-right, bottom-left
    rect = np.zeros((4, 2), dtype="float32")

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left

    (tl, tr, br, bl) = rect

    # Compute max width and height
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = int(max(heightA, heightB))

    # Destination rectangle
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")

    # Apply perspective transform
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def process_image_opencv(img_array):
    """
    Core image processing pipeline.
    Takes OpenCV image array, returns processed image array.
    """
    # Step 1: Initial noise reduction
    denoised = reduce_noise(img_array)
    
    # Step 2: Enhance contrast for better edge detection
    enhanced = enhance_contrast(denoised)
    
    # Step 3: Detect and correct card perspective
    contour = detect_card_border(enhanced)
    if contour is not None:
        straightened = four_point_transform(enhanced, contour)
    else:
        straightened = enhanced  # fallback if contour detection fails
    
    # Step 4: Apply color correction
    color_corrected = color_correct(straightened)
    
    # Step 5: Apply final sharpening for text clarity
    sharpened = sharpen_image(color_corrected)
    
    # Step 6: Resize to optimal dimensions for AI analysis
    final_image = resize_for_analysis(sharpened)
    
    return final_image


def enhance_image_for_ocr(image_data: bytes) -> bytes:
    """
    Complete image processing pipeline optimized for AI analysis.
    Takes image bytes and returns enhanced image bytes.
    """
    # Convert bytes to numpy array for OpenCV
    image_array = np.frombuffer(image_data, np.uint8)
    original = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    
    if original is None:
        return image_data  # Return original if processing fails
    
    try:
        # Apply the core processing pipeline
        final_image = process_image_opencv(original)
        
        # Convert back to bytes (PNG for quality)
        success, encoded_img = cv2.imencode('.png', final_image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if success:
            return encoded_img.tobytes()
        else:
            return image_data  # Return original if encoding fails
    except Exception:
        return image_data  # Return original if any processing fails


def adaptive_preprocessing(image_data: bytes, card_era: str) -> bytes:
    """
    Apply era-specific preprocessing based on card characteristics.
    """
    # For now, use the standard enhancement - could be expanded for era-specific processing
    return enhance_image_for_ocr(image_data)


def create_high_contrast_version(image_data: bytes) -> bytes:
    """
    Create high contrast version for difficult-to-read cards.
    """
    # Convert bytes to numpy array for OpenCV
    image_array = np.frombuffer(image_data, np.uint8)
    original = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    
    if original is None:
        return image_data
    
    try:
        # Convert to grayscale
        gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
        
        # Apply more aggressive contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Apply threshold to create high contrast
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Convert back to 3-channel for consistency
        high_contrast = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        
        # Convert back to bytes
        success, encoded_img = cv2.imencode('.png', high_contrast, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if success:
            return encoded_img.tobytes()
        else:
            return image_data
    except Exception:
        return image_data