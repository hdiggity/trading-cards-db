"""Visual feature extraction for card design matching.

Extracts visual fingerprints from card images to enable design-aware
corrections. When a user corrects a field (like year), the system learns
the visual appearance of that card design and only applies the correction
to visually similar cards in the future.

Features extracted:
1. Perceptual hash (pHash) - structural similarity fingerprint
2. Color histogram - dominant color distribution
3. Edge density - layout complexity measure
"""

import json
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

# Feature vector version - increment when algorithm changes
FEATURE_VERSION = 1


def extract_visual_features(image_path: str) -> Optional[Dict[str, Any]]:
    """Extract visual features from a card image.

    Args:
        image_path: Path to the card image file

    Returns:
        Dict with visual features, or None if extraction fails
    """
    try:
        img = Image.open(image_path)

        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')

        features = {
            'version': FEATURE_VERSION,
            'phash': compute_phash(img),
            'color_histogram': compute_color_histogram(img),
            'edge_density': compute_edge_density(img),
            'aspect_ratio': round(img.width / img.height, 3),
            'dominant_colors': extract_dominant_colors(img, n_colors=5)
        }

        return features

    except Exception as e:
        print(f"[visual_features] Error extracting features from {image_path}: {e}")
        return None


def compute_phash(img: Image.Image, hash_size: int = 16) -> str:
    """Compute perceptual hash of image.

    pHash is robust to scaling and minor color changes. Similar images
    will have similar hashes.
    """
    # Resize to hash_size + 1 for DCT
    img_small = img.resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    img_gray = img_small.convert('L')

    pixels = np.array(img_gray, dtype=np.float64)

    # Compute difference hash (simpler than full DCT, still effective)
    diff = pixels[:, 1:] > pixels[:, :-1]

    # Convert to hex string
    hash_bits = diff.flatten()
    hash_int = 0
    for bit in hash_bits:
        hash_int = (hash_int << 1) | int(bit)

    return format(hash_int, f'0{hash_size * hash_size // 4}x')


def compute_color_histogram(img: Image.Image, bins: int = 8) -> List[float]:
    """Compute normalized color histogram.

    Captures the overall color distribution of the card, which is often
    distinctive for different year designs.
    """
    # Resize for consistency
    img_small = img.resize((64, 64), Image.Resampling.LANCZOS)
    pixels = np.array(img_small)

    # Compute histogram for each channel
    histograms = []
    for channel in range(3):
        hist, _ = np.histogram(pixels[:, :, channel], bins=bins, range=(0, 256))
        hist = hist.astype(float)
        hist /= hist.sum() + 1e-7  # Normalize
        histograms.extend(hist.tolist())

    return [round(v, 4) for v in histograms]


def compute_edge_density(img: Image.Image) -> float:
    """Compute edge density as a measure of design complexity.

    Different card designs have different amounts of text, borders, and
    graphic elements.
    """
    # Resize and convert to grayscale
    img_small = img.resize((64, 64), Image.Resampling.LANCZOS)
    img_gray = np.array(img_small.convert('L'), dtype=np.float64)

    # Simple Sobel-like edge detection
    gx = np.abs(img_gray[:, 1:] - img_gray[:, :-1])
    gy = np.abs(img_gray[1:, :] - img_gray[:-1, :])

    # Threshold and count edges
    threshold = 30
    edge_pixels = (gx[:63, :] > threshold).sum() + (gy[:, :63] > threshold).sum()
    total_pixels = 63 * 63 * 2

    return round(edge_pixels / total_pixels, 4)


def extract_dominant_colors(img: Image.Image, n_colors: int = 5) -> List[List[int]]:
    """Extract dominant colors using simple quantization.

    Captures the main colors of the card design (border color,
    background color, team colors, etc.)
    """
    # Resize for speed
    img_small = img.resize((32, 32), Image.Resampling.LANCZOS)
    pixels = np.array(img_small).reshape(-1, 3)

    # Simple k-means-like clustering
    # Quantize colors to reduce complexity
    quantized = (pixels // 32) * 32 + 16

    # Count unique colors
    color_counts = {}
    for pixel in quantized:
        key = tuple(pixel.tolist())
        color_counts[key] = color_counts.get(key, 0) + 1

    # Sort by frequency
    sorted_colors = sorted(color_counts.items(), key=lambda x: -x[1])

    # Return top N colors
    return [list(color) for color, count in sorted_colors[:n_colors]]


def compute_visual_similarity(features1: Dict, features2: Dict) -> float:
    """Compute similarity score between two feature sets.

    Returns a score from 0.0 (completely different) to 1.0 (identical).
    """
    if not features1 or not features2:
        return 0.0

    # Check version compatibility
    if features1.get('version') != features2.get('version'):
        return 0.0

    scores = []
    weights = []

    # pHash similarity (Hamming distance)
    phash1 = features1.get('phash', '')
    phash2 = features2.get('phash', '')
    if phash1 and phash2 and len(phash1) == len(phash2):
        # Convert hex to binary and count differences
        try:
            int1 = int(phash1, 16)
            int2 = int(phash2, 16)
            hamming = bin(int1 ^ int2).count('1')
            max_bits = len(phash1) * 4
            phash_sim = 1.0 - (hamming / max_bits)
            scores.append(phash_sim)
            weights.append(3.0)  # High weight for structural similarity
        except ValueError:
            pass

    # Color histogram similarity (cosine similarity)
    hist1 = features1.get('color_histogram', [])
    hist2 = features2.get('color_histogram', [])
    if hist1 and hist2 and len(hist1) == len(hist2):
        h1 = np.array(hist1)
        h2 = np.array(hist2)
        dot = np.dot(h1, h2)
        norm1 = np.linalg.norm(h1)
        norm2 = np.linalg.norm(h2)
        if norm1 > 0 and norm2 > 0:
            hist_sim = dot / (norm1 * norm2)
            scores.append(hist_sim)
            weights.append(2.0)  # Medium weight for color

    # Edge density similarity
    edge1 = features1.get('edge_density', 0)
    edge2 = features2.get('edge_density', 0)
    edge_diff = abs(edge1 - edge2)
    edge_sim = max(0, 1.0 - edge_diff * 5)  # 0.2 difference = 0 similarity
    scores.append(edge_sim)
    weights.append(1.0)  # Lower weight

    # Dominant color similarity
    colors1 = features1.get('dominant_colors', [])
    colors2 = features2.get('dominant_colors', [])
    if colors1 and colors2:
        color_sim = compute_dominant_color_similarity(colors1, colors2)
        scores.append(color_sim)
        weights.append(1.5)

    if not scores:
        return 0.0

    # Weighted average
    total_weight = sum(weights)
    weighted_sum = sum(s * w for s, w in zip(scores, weights))

    return round(weighted_sum / total_weight, 4)


def compute_dominant_color_similarity(colors1: List[List[int]], colors2: List[List[int]]) -> float:
    """Compare dominant color palettes."""
    if not colors1 or not colors2:
        return 0.0

    # For each color in palette 1, find closest match in palette 2
    total_distance = 0
    for c1 in colors1:
        min_dist = float('inf')
        for c2 in colors2:
            dist = sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5
            min_dist = min(min_dist, dist)
        total_distance += min_dist

    # Normalize by max possible distance (sqrt(3 * 255^2) * n_colors)
    max_distance = 441.67 * len(colors1)  # sqrt(3) * 255
    similarity = 1.0 - (total_distance / max_distance)

    return max(0, similarity)


def features_to_json(features: Dict) -> str:
    """Serialize features to JSON string for database storage."""
    return json.dumps(features, separators=(',', ':'))


def features_from_json(json_str: str) -> Optional[Dict]:
    """Deserialize features from JSON string."""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None


def get_visual_signature(features: Dict) -> str:
    """Generate a compact signature string for quick matching.

    This is used as a first-pass filter before computing full
    similarity. Cards with very different signatures won't be compared
    in detail.
    """
    if not features:
        return ""

    parts = []

    # Include pHash prefix (first 8 chars)
    phash = features.get('phash', '')
    if phash:
        parts.append(f"p:{phash[:8]}")

    # Include edge density bucket
    edge = features.get('edge_density', 0)
    edge_bucket = int(edge * 10)  # 0-10
    parts.append(f"e:{edge_bucket}")

    # Include dominant color summary
    colors = features.get('dominant_colors', [])
    if colors and len(colors) > 0:
        # Just use first dominant color, quantized
        c = colors[0]
        r, g, b = c[0] // 64, c[1] // 64, c[2] // 64
        parts.append(f"c:{r}{g}{b}")

    return "|".join(parts)
