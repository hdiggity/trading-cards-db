"""
Predict baseball card condition from cropped back images using trained model.

This script loads the trained condition classifier and predicts the condition
of new card images. It can be used standalone or integrated into the main pipeline.
"""

import os
import sys
import pickle
import numpy as np
from pathlib import Path
from typing import Dict, Tuple, Optional
import warnings

warnings.filterwarnings('ignore')

try:
    import cv2
    from PIL import Image
except ImportError as e:
    print(f"Missing required library: {e}")
    print("Please install: pip install opencv-python pillow")
    sys.exit(1)


# Paths
BASE_DIR = Path(__file__).parent.parent
MODEL_DIR = BASE_DIR / "app" / "models"
MODEL_PATH = MODEL_DIR / "condition_classifier.pkl"


class ConditionPredictor:
    """
    Predicts baseball card condition from cropped back images.
    """

    def __init__(self, model_path: Optional[Path] = None):
        """
        Initialize the condition predictor.

        Args:
            model_path: Path to the trained model .pkl file
                       (defaults to MODEL_PATH if not provided)
        """
        self.model_path = model_path or MODEL_PATH

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model not found at {self.model_path}. "
                "Please train the model first using condition_model_trainer.py"
            )

        # Load model package
        print(f"Loading model from: {self.model_path}")
        with open(self.model_path, 'rb') as f:
            self.model_package = pickle.load(f)

        self.model = self.model_package['model']
        self.scaler = self.model_package['scaler']
        self.label_encoder = self.model_package['label_encoder']
        self.classes = self.model_package['classes']

        print(f"Model loaded successfully!")
        print(f"Model type: {self.model_package['model_name']}")
        print(f"Training accuracy: {self.model_package['test_accuracy']:.4f}")
        print(f"Supported conditions: {', '.join(self.classes)}")

    def extract_image_features(self, image_path: Path) -> np.ndarray:
        """
        Extract features from a card back image.
        This uses the exact same feature extraction as the training script.

        Args:
            image_path: Path to the card image

        Returns:
            Feature vector as numpy array
        """
        try:
            # Load image
            img = cv2.imread(str(image_path))
            if img is None:
                # Try with PIL for PNG files
                pil_img = Image.open(image_path)
                img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

            if img is None:
                raise ValueError(f"Could not load image: {image_path}")

            # Resize to standard size
            img = cv2.resize(img, (512, 512))

            features = []

            # 1. Color histogram features (RGB channels)
            for channel in range(3):
                hist = cv2.calcHist([img], [channel], None, [256], [0, 256])
                features.extend([
                    np.mean(hist),
                    np.std(hist),
                    np.median(hist),
                    np.percentile(hist, 25),
                    np.percentile(hist, 75)
                ])

            # 2. Grayscale for texture analysis
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 3. Edge detection
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges) / edges.size
            features.append(edge_density)

            # 4. Brightness and contrast
            brightness = np.mean(gray)
            contrast = np.std(gray)
            features.extend([brightness, contrast])

            # 5. Color variance
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            for channel in range(3):
                features.append(np.std(hsv[:, :, channel]))

            # 6. Local Binary Pattern-like feature
            kernel = np.array([[1, 1, 1], [1, -8, 1], [1, 1, 1]])
            lbp = cv2.filter2D(gray, cv2.CV_32F, kernel)
            features.extend([
                np.mean(np.abs(lbp)),
                np.std(np.abs(lbp))
            ])

            # 7. Corner damage detection
            h, w = gray.shape
            corner_size = 50
            corners = [
                gray[0:corner_size, 0:corner_size],
                gray[0:corner_size, w-corner_size:w],
                gray[h-corner_size:h, 0:corner_size],
                gray[h-corner_size:h, w-corner_size:w]
            ]

            for corner in corners:
                features.extend([
                    np.mean(corner),
                    np.std(corner)
                ])

            # 8. Surface uniformity
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            features.append(np.var(laplacian))

            # 9. Color saturation statistics
            saturation = hsv[:, :, 1]
            features.extend([
                np.mean(saturation),
                np.std(saturation),
                np.median(saturation)
            ])

            return np.array(features, dtype=np.float32)

        except Exception as e:
            raise RuntimeError(f"Error extracting features from {image_path}: {e}")

    def predict(self, image_path: Path) -> Dict:
        """
        Predict the condition of a card from its back image.

        Args:
            image_path: Path to the card back image

        Returns:
            Dictionary containing:
                - predicted_condition: The predicted condition label
                - confidence: Confidence score (0-1)
                - all_probabilities: Probability for each condition class
        """
        # Extract features
        features = self.extract_image_features(image_path)

        if features is None:
            return {
                'predicted_condition': None,
                'confidence': 0.0,
                'all_probabilities': {},
                'error': 'Failed to extract features'
            }

        # Reshape for single prediction
        features = features.reshape(1, -1)

        # Scale features
        features_scaled = self.scaler.transform(features)

        # Predict
        prediction = self.model.predict(features_scaled)[0]
        predicted_label = self.label_encoder.inverse_transform([prediction])[0]

        # Get probabilities if available
        if hasattr(self.model, 'predict_proba'):
            probabilities = self.model.predict_proba(features_scaled)[0]
            confidence = float(probabilities[prediction])

            # Create probability dict for all classes
            all_probs = {
                self.label_encoder.classes_[i]: float(prob)
                for i, prob in enumerate(probabilities)
            }
        else:
            confidence = 1.0
            all_probs = {predicted_label: 1.0}

        return {
            'predicted_condition': predicted_label,
            'confidence': confidence,
            'all_probabilities': all_probs,
            'error': None
        }

    def predict_batch(self, image_paths: list) -> list:
        """
        Predict conditions for multiple images.

        Args:
            image_paths: List of paths to card back images

        Returns:
            List of prediction dictionaries
        """
        results = []

        for image_path in image_paths:
            try:
                result = self.predict(Path(image_path))
                result['image_path'] = str(image_path)
                results.append(result)
            except Exception as e:
                results.append({
                    'image_path': str(image_path),
                    'predicted_condition': None,
                    'confidence': 0.0,
                    'all_probabilities': {},
                    'error': str(e)
                })

        return results


def main():
    """Demo showing how to use the ConditionPredictor."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Predict baseball card condition from cropped back images'
    )
    parser.add_argument(
        'image_path',
        type=str,
        help='Path to card back image (or directory of images)'
    )
    parser.add_argument(
        '--model',
        type=str,
        default=str(MODEL_PATH),
        help='Path to trained model .pkl file'
    )

    args = parser.parse_args()

    # Initialize predictor
    try:
        predictor = ConditionPredictor(Path(args.model))
    except Exception as e:
        print(f"Error loading model: {e}")
        sys.exit(1)

    # Check if input is file or directory
    input_path = Path(args.image_path)

    if input_path.is_file():
        # Single file prediction
        print(f"\nPredicting condition for: {input_path.name}")
        print("-" * 60)

        result = predictor.predict(input_path)

        if result['error']:
            print(f"Error: {result['error']}")
        else:
            print(f"Predicted Condition: {result['predicted_condition']}")
            print(f"Confidence: {result['confidence']:.2%}")
            print("\nAll probabilities:")
            for condition, prob in sorted(result['all_probabilities'].items(),
                                         key=lambda x: x[1], reverse=True):
                print(f"  {condition}: {prob:.2%}")

    elif input_path.is_dir():
        # Batch prediction
        print(f"\nPredicting conditions for images in: {input_path}")
        print("-" * 60)

        # Find all image files
        image_files = []
        for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
            image_files.extend(input_path.glob(ext))

        if not image_files:
            print("No image files found in directory")
            sys.exit(1)

        print(f"Found {len(image_files)} images\n")

        # Predict batch
        results = predictor.predict_batch(image_files)

        # Print results
        for result in results:
            filename = Path(result['image_path']).name
            if result['error']:
                print(f"{filename}: ERROR - {result['error']}")
            else:
                print(f"{filename}: {result['predicted_condition']} "
                      f"(confidence: {result['confidence']:.2%})")

        # Summary statistics
        successful = [r for r in results if not r['error']]
        if successful:
            print(f"\nSummary:")
            print(f"  Successfully predicted: {len(successful)}/{len(results)}")

            condition_counts = {}
            for result in successful:
                cond = result['predicted_condition']
                condition_counts[cond] = condition_counts.get(cond, 0) + 1

            print(f"\nPredicted condition distribution:")
            for condition, count in sorted(condition_counts.items()):
                print(f"  {condition}: {count}")

    else:
        print(f"Error: {input_path} is not a valid file or directory")
        sys.exit(1)


if __name__ == "__main__":
    main()
