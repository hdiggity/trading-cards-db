"""
Train a machine learning model to predict baseball card condition from cropped back images.

This script:
1. Loads verified card back images and their condition labels from the database
2. Extracts image features using computer vision techniques
3. Trains a classifier with 70-30 train-test split
4. Saves the trained model as a .pkl file
5. Evaluates model performance on the test set
"""

import os
import sys
import sqlite3
import pickle
import numpy as np
from PIL import Image
from pathlib import Path
from typing import List, Tuple, Dict
from collections import Counter
import warnings

warnings.filterwarnings('ignore')

# Image processing and ML libraries
try:
    import cv2
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
    import joblib
except ImportError as e:
    print(f"Missing required library: {e}")
    print("Please install required packages:")
    print("pip install opencv-python scikit-learn joblib pillow numpy")
    sys.exit(1)


# Paths
BASE_DIR = Path(__file__).parent.parent
CARDS_DIR = BASE_DIR / "cards" / "verified"
IMAGE_DIR = CARDS_DIR / "verified_cropped_backs"
DB_PATH = CARDS_DIR / "trading_cards.db"
MODEL_DIR = BASE_DIR / "app" / "models"
MODEL_PATH = MODEL_DIR / "condition_classifier.pkl"

# Ensure model directory exists
MODEL_DIR.mkdir(exist_ok=True)


def normalize_condition_label(condition: str) -> str:
    """Normalize inconsistent condition labels."""
    if not condition:
        return None

    condition = condition.lower().strip()

    # Normalize 'very good' vs 'very_good'
    if condition in ['very good', 'very_good']:
        return 'very_good'

    return condition


def load_data_from_db() -> List[Tuple[str, str]]:
    """
    Load image filenames and their condition labels from the database.

    Returns:
        List of tuples (image_filename, condition_label)
    """
    print(f"Loading data from database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Query cards with both cropped_back_file and condition
    query = """
        SELECT cropped_back_file, condition
        FROM cards_complete
        WHERE cropped_back_file IS NOT NULL
        AND condition IS NOT NULL
        AND condition != ''
    """

    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()

    # Normalize condition labels
    data = [(filename, normalize_condition_label(condition))
            for filename, condition in results if normalize_condition_label(condition)]

    print(f"Loaded {len(data)} cards with condition labels")

    # Show distribution
    condition_counts = Counter([condition for _, condition in data])
    print("\nCondition distribution:")
    for condition, count in sorted(condition_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {condition}: {count}")

    return data


def extract_image_features(image_path: Path) -> np.ndarray:
    """
    Extract comprehensive features from a card back image.

    Features extracted:
    - Color histogram statistics (mean, std for each channel)
    - Texture features (edge detection statistics)
    - Brightness and contrast metrics
    - Color variance and saturation
    - Corner/edge damage indicators
    - Surface uniformity metrics

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

        # Resize to standard size for consistent feature extraction
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

        # 2. Convert to grayscale for texture analysis
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 3. Edge detection (Canny) - damaged cards have more irregular edges
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges) / edges.size
        features.append(edge_density)

        # 4. Brightness and contrast
        brightness = np.mean(gray)
        contrast = np.std(gray)
        features.extend([brightness, contrast])

        # 5. Color variance (damaged cards may have discoloration)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        for channel in range(3):
            features.append(np.std(hsv[:, :, channel]))

        # 6. Local Binary Pattern (texture)
        # Simplified LBP-like feature
        kernel = np.array([[1, 1, 1], [1, -8, 1], [1, 1, 1]])
        lbp = cv2.filter2D(gray, cv2.CV_32F, kernel)
        features.extend([
            np.mean(np.abs(lbp)),
            np.std(np.abs(lbp))
        ])

        # 7. Corner damage detection (check corners for damage)
        h, w = gray.shape
        corner_size = 50
        corners = [
            gray[0:corner_size, 0:corner_size],  # Top-left
            gray[0:corner_size, w-corner_size:w],  # Top-right
            gray[h-corner_size:h, 0:corner_size],  # Bottom-left
            gray[h-corner_size:h, w-corner_size:w]  # Bottom-right
        ]

        for corner in corners:
            features.extend([
                np.mean(corner),
                np.std(corner)
            ])

        # 8. Surface uniformity (damaged cards have less uniform surfaces)
        # Use Laplacian variance as a measure of blur/sharpness
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
        print(f"Error extracting features from {image_path}: {e}")
        return None


def prepare_dataset(data: List[Tuple[str, str]]) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Prepare feature matrix X and label array y from the data.

    Args:
        data: List of (filename, condition) tuples

    Returns:
        X: Feature matrix (n_samples, n_features)
        y: Label array (n_samples,)
        valid_files: List of filenames that were successfully processed
    """
    print("\nExtracting features from images...")

    X_list = []
    y_list = []
    valid_files = []

    for i, (filename, condition) in enumerate(data):
        if (i + 1) % 20 == 0:
            print(f"Processing {i + 1}/{len(data)} images...")

        image_path = IMAGE_DIR / filename

        if not image_path.exists():
            print(f"Warning: Image not found: {image_path}")
            continue

        features = extract_image_features(image_path)

        if features is not None:
            X_list.append(features)
            y_list.append(condition)
            valid_files.append(filename)

    print(f"Successfully extracted features from {len(X_list)}/{len(data)} images")

    X = np.array(X_list)
    y = np.array(y_list)

    return X, y, valid_files


def train_model(X: np.ndarray, y: np.ndarray) -> Dict:
    """
    Train a condition classification model with 70-30 train-test split.

    Args:
        X: Feature matrix
        y: Label array

    Returns:
        Dictionary containing model, scaler, encoder, and evaluation metrics
    """
    print("\n" + "="*60)
    print("Training Condition Classification Model")
    print("="*60)

    # Check class distribution
    unique, counts = np.unique(y, return_counts=True)
    class_distribution = dict(zip(unique, counts))

    # Filter out classes with too few samples (need at least 2 for train-test split)
    min_samples_required = 3  # Need at least 3 to split properly
    filtered_indices = []
    removed_classes = []

    for i, label in enumerate(y):
        if class_distribution[label] >= min_samples_required:
            filtered_indices.append(i)
        else:
            if label not in removed_classes:
                removed_classes.append(label)
                print(f"\nWarning: Removing class '{label}' (only {class_distribution[label]} samples, need >= {min_samples_required})")

    if filtered_indices:
        X = X[filtered_indices]
        y = y[filtered_indices]
    else:
        print("Error: No classes have enough samples for training")
        sys.exit(1)

    # Encode labels
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)

    print(f"\nLabel mapping (after filtering):")
    for i, label in enumerate(label_encoder.classes_):
        count = np.sum(y == label)
        print(f"  {i}: {label} ({count} samples)")

    # Check if stratification is possible
    unique_encoded, counts_encoded = np.unique(y_encoded, return_counts=True)
    can_stratify = all(count >= 2 for count in counts_encoded)

    # Split data (70-30 train-test split)
    if can_stratify:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=0.30, random_state=42, stratify=y_encoded
        )
    else:
        print("\nWarning: Cannot use stratified split, using random split instead")
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=0.30, random_state=42
        )

    print(f"\nDataset split:")
    print(f"  Training samples: {len(X_train)} (70%)")
    print(f"  Testing samples: {len(X_test)} (30%)")

    # Standardize features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Train multiple models and compare
    print("\nTraining models...")

    models = {
        'Random Forest': RandomForestClassifier(
            n_estimators=200,
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        ),
        'Gradient Boosting': GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        )
    }

    best_model = None
    best_score = 0
    best_name = None

    for name, model in models.items():
        print(f"\nTraining {name}...")
        model.fit(X_train_scaled, y_train)

        # Evaluate on test set
        test_score = model.score(X_test_scaled, y_test)
        print(f"  Test accuracy: {test_score:.4f}")

        # Cross-validation on training set
        cv_scores = cross_val_score(model, X_train_scaled, y_train, cv=5)
        print(f"  CV accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")

        if test_score > best_score:
            best_score = test_score
            best_model = model
            best_name = name

    print(f"\nBest model: {best_name} with test accuracy: {best_score:.4f}")

    # Detailed evaluation
    print("\n" + "="*60)
    print("Model Evaluation")
    print("="*60)

    y_pred = best_model.predict(X_test_scaled)

    print("\nClassification Report:")
    print(classification_report(
        y_test, y_pred,
        target_names=label_encoder.classes_,
        zero_division=0
    ))

    print("\nConfusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(cm)

    # Feature importance (if available)
    if hasattr(best_model, 'feature_importances_'):
        importances = best_model.feature_importances_
        top_indices = np.argsort(importances)[-10:][::-1]
        print("\nTop 10 most important features:")
        for idx in top_indices:
            print(f"  Feature {idx}: {importances[idx]:.4f}")

    # Package everything together
    model_package = {
        'model': best_model,
        'scaler': scaler,
        'label_encoder': label_encoder,
        'model_name': best_name,
        'test_accuracy': best_score,
        'feature_count': X.shape[1],
        'classes': label_encoder.classes_.tolist(),
        'confusion_matrix': cm.tolist(),
        'classification_report': classification_report(
            y_test, y_pred,
            target_names=label_encoder.classes_,
            output_dict=True,
            zero_division=0
        )
    }

    return model_package


def save_model(model_package: Dict, output_path: Path):
    """Save the trained model package to disk."""
    print(f"\nSaving model to: {output_path}")

    with open(output_path, 'wb') as f:
        pickle.dump(model_package, f)

    print(f"Model saved successfully!")
    print(f"Model size: {output_path.stat().st_size / 1024:.2f} KB")


def main():
    """Main training pipeline."""
    print("Baseball Card Condition Classifier Training")
    print("="*60)

    # Check paths
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    if not IMAGE_DIR.exists():
        print(f"Error: Image directory not found at {IMAGE_DIR}")
        sys.exit(1)

    # Load data
    data = load_data_from_db()

    if len(data) < 10:
        print("Error: Not enough training data (minimum 10 samples required)")
        sys.exit(1)

    # Prepare dataset
    X, y, valid_files = prepare_dataset(data)

    if len(X) < 10:
        print("Error: Not enough valid samples after feature extraction")
        sys.exit(1)

    # Train model
    model_package = train_model(X, y)

    # Save model
    save_model(model_package, MODEL_PATH)

    print("\n" + "="*60)
    print("Training Complete!")
    print("="*60)
    print(f"\nModel saved to: {MODEL_PATH}")
    print(f"Model type: {model_package['model_name']}")
    print(f"Test accuracy: {model_package['test_accuracy']:.4f}")
    print(f"Classes: {', '.join(model_package['classes'])}")
    print(f"\nYou can now use this model to predict card conditions on new images.")


if __name__ == "__main__":
    main()
