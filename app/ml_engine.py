"""ML Correction Engine for unsupervised learning from user edits.

Learns from ALL user corrections during verification and applies
high-confidence corrections to GPT extraction output. GPT remains
primary - ML only overrides with 92%+ confidence.

Three model types for different field categories:
- Categorical: Naive Bayes for sport, condition, brand, is_player
- Text: Fuzzy matching for name, team, card_set, notes
- Structured: Rule-based for copyright_year, number, features, value_estimate
"""

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .correction_tracker import CorrectionTracker


@dataclass
class MLPrediction:
    """Result of an ML prediction for a field."""
    value: str
    confidence: float
    support_count: int
    model_type: str  # 'categorical', 'text', 'structured'


# Field categorization
CATEGORICAL_FIELDS = ['sport', 'condition', 'brand', 'is_player']
TEXT_FIELDS = ['name', 'team', 'card_set', 'notes']
STRUCTURED_FIELDS = ['copyright_year', 'number', 'features', 'value_estimate']

# Override thresholds (conservative to preserve GPT primacy)
THRESHOLDS = {
    'categorical': {'confidence': 0.90, 'min_support': 5},
    'text': {'confidence': 0.95, 'min_support': 8},
    'structured': {'confidence': 0.92, 'min_support': 4}
}


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def fuzzy_similarity(s1: str, s2: str) -> float:
    """Calculate fuzzy similarity between two strings (0.0 to 1.0)."""
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    distance = levenshtein_distance(s1, s2)
    return 1.0 - (distance / max_len)


class NaiveBayesClassifier:
    """Simple Naive Bayes classifier with Laplace smoothing."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha  # Laplace smoothing parameter
        self.class_counts: Dict[str, int] = defaultdict(int)
        self.feature_counts: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        self.total_samples = 0
        self.vocabulary: Dict[str, set] = defaultdict(set)

    def fit(self, X: List[Dict[str, str]], y: List[str]):
        """Train the classifier on feature dicts and labels."""
        self.class_counts.clear()
        self.feature_counts.clear()
        self.vocabulary.clear()
        self.total_samples = len(y)

        for features, label in zip(X, y):
            self.class_counts[label] += 1
            for feature_name, feature_value in features.items():
                if feature_value:
                    self.feature_counts[label][feature_name][str(feature_value).lower()] += 1
                    self.vocabulary[feature_name].add(str(feature_value).lower())

    def predict_proba(self, features: Dict[str, str]) -> Dict[str, float]:
        """Return probability distribution over classes."""
        if self.total_samples == 0:
            return {}

        log_probs = {}
        for label, count in self.class_counts.items():
            # Prior probability
            log_prob = math.log((count + self.alpha) /
                               (self.total_samples + self.alpha * len(self.class_counts)))

            # Likelihood for each feature
            for feature_name, feature_value in features.items():
                if feature_value and feature_name in self.vocabulary:
                    fv = str(feature_value).lower()
                    vocab_size = len(self.vocabulary[feature_name])
                    feature_count = self.feature_counts[label][feature_name].get(fv, 0)
                    total_for_label = sum(self.feature_counts[label][feature_name].values())
                    # Laplace smoothed probability
                    prob = (feature_count + self.alpha) / (total_for_label + self.alpha * vocab_size)
                    log_prob += math.log(prob)

            log_probs[label] = log_prob

        # Convert log probs to probabilities
        if not log_probs:
            return {}

        max_log = max(log_probs.values())
        probs = {k: math.exp(v - max_log) for k, v in log_probs.items()}
        total = sum(probs.values())
        return {k: v / total for k, v in probs.items()}

    def predict(self, features: Dict[str, str]) -> Tuple[Optional[str], float]:
        """Predict class and confidence for features."""
        probs = self.predict_proba(features)
        if not probs:
            return None, 0.0
        best_class = max(probs, key=probs.get)
        return best_class, probs[best_class]


class TextMapper:
    """Fuzzy matching mapper for text field corrections."""

    def __init__(self):
        # Exact mappings: gpt_value -> (corrected_value, count)
        self.exact_mappings: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Context-aware mappings: (gpt_value, brand, sport) -> (corrected_value, count)
        self.context_mappings: Dict[Tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def fit(self, training_data: List[Dict[str, Any]]):
        """Build mappings from training data."""
        self.exact_mappings.clear()
        self.context_mappings.clear()

        for item in training_data:
            orig = (item.get('original_value') or '').lower().strip()
            corr = (item.get('corrected_value') or '').lower().strip()
            if not orig or not corr or orig == corr:
                continue

            # Exact mapping
            self.exact_mappings[orig][corr] += 1

            # Context-aware mapping
            brand = (item.get('brand') or '').lower().strip()
            sport = (item.get('sport') or '').lower().strip()
            context_key = (orig, brand, sport)
            self.context_mappings[context_key][corr] += 1

    def predict(
        self,
        gpt_value: str,
        brand: Optional[str] = None,
        sport: Optional[str] = None,
        min_support: int = 2
    ) -> Optional[MLPrediction]:
        """Find best correction for GPT value."""
        if not gpt_value:
            return None

        gpt_lower = gpt_value.lower().strip()

        # Try context-aware mapping first
        if brand or sport:
            brand_lower = (brand or '').lower().strip()
            sport_lower = (sport or '').lower().strip()
            context_key = (gpt_lower, brand_lower, sport_lower)
            if context_key in self.context_mappings:
                corrections = self.context_mappings[context_key]
                if corrections:
                    best = max(corrections.items(), key=lambda x: x[1])
                    if best[1] >= min_support:
                        total = sum(corrections.values())
                        confidence = best[1] / total
                        return MLPrediction(
                            value=best[0],
                            confidence=confidence,
                            support_count=best[1],
                            model_type='text'
                        )

        # Fall back to exact mapping
        if gpt_lower in self.exact_mappings:
            corrections = self.exact_mappings[gpt_lower]
            if corrections:
                best = max(corrections.items(), key=lambda x: x[1])
                if best[1] >= min_support:
                    total = sum(corrections.values())
                    confidence = best[1] / total
                    return MLPrediction(
                        value=best[0],
                        confidence=confidence,
                        support_count=best[1],
                        model_type='text'
                    )

        # Try fuzzy matching against known corrections
        best_match = None
        best_similarity = 0.0
        best_count = 0

        for orig, corrections in self.exact_mappings.items():
            similarity = fuzzy_similarity(gpt_lower, orig)
            if similarity >= 0.85:  # High similarity threshold
                best_corr = max(corrections.items(), key=lambda x: x[1])
                if best_corr[1] >= min_support:
                    # Weight by similarity and support count
                    score = similarity * math.log(best_corr[1] + 1)
                    if score > best_similarity:
                        best_similarity = score
                        best_match = best_corr[0]
                        best_count = best_corr[1]

        if best_match and best_count >= min_support:
            # Fuzzy matches get lower confidence
            total_for_orig = sum(self.exact_mappings.get(gpt_lower, {}).values()) or best_count
            confidence = min(0.90, best_count / total_for_orig * 0.85)
            return MLPrediction(
                value=best_match,
                confidence=confidence,
                support_count=best_count,
                model_type='text'
            )

        return None


class StructuredValidator:
    """Rule-based validator for structured fields."""

    def __init__(self):
        # Pattern frequency maps
        self.year_patterns: Dict[str, int] = defaultdict(int)
        self.number_patterns: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.feature_vocabulary: Dict[str, int] = defaultdict(int)
        self.value_corrections: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def fit(self, field: str, training_data: List[Dict[str, Any]]):
        """Build validators from training data."""
        if field == 'copyright_year':
            self._fit_year(training_data)
        elif field == 'number':
            self._fit_number(training_data)
        elif field == 'features':
            self._fit_features(training_data)
        elif field == 'value_estimate':
            self._fit_value(training_data)

    def _fit_year(self, training_data: List[Dict[str, Any]]):
        """Learn year correction patterns."""
        self.year_patterns.clear()
        for item in training_data:
            corr = item.get('corrected_value')
            if corr and re.match(r'^\d{4}$', str(corr)):
                self.year_patterns[str(corr)] += 1

    def _fit_number(self, training_data: List[Dict[str, Any]]):
        """Learn card number patterns by brand."""
        self.number_patterns.clear()
        for item in training_data:
            brand = (item.get('brand') or 'unknown').lower().strip()
            corr = item.get('corrected_value')
            if corr:
                self.number_patterns[brand][str(corr)] += 1

    def _fit_features(self, training_data: List[Dict[str, Any]]):
        """Build feature vocabulary from corrections."""
        self.feature_vocabulary.clear()
        for item in training_data:
            corr = item.get('corrected_value', '')
            if corr and corr != 'none':
                for feature in str(corr).lower().split(','):
                    feature = feature.strip()
                    if feature and feature != 'none':
                        self.feature_vocabulary[feature] += 1

    def _fit_value(self, training_data: List[Dict[str, Any]]):
        """Learn value estimate corrections."""
        self.value_corrections.clear()
        for item in training_data:
            orig = (item.get('original_value') or '').strip()
            corr = (item.get('corrected_value') or '').strip()
            if orig and corr and orig != corr:
                self.value_corrections[orig][corr] += 1

    def predict(
        self,
        field: str,
        gpt_value: str,
        context: Dict[str, Any],
        min_support: int = 4
    ) -> Optional[MLPrediction]:
        """Validate and potentially correct a structured field value."""
        if field == 'copyright_year':
            return self._predict_year(gpt_value, min_support)
        elif field == 'number':
            brand = context.get('brand', 'unknown')
            return self._predict_number(gpt_value, brand, min_support)
        elif field == 'features':
            return self._predict_features(gpt_value, min_support)
        elif field == 'value_estimate':
            return self._predict_value(gpt_value, min_support)
        return None

    def _predict_year(self, gpt_value: str, min_support: int) -> Optional[MLPrediction]:
        """Validate copyright year."""
        if not gpt_value:
            return None

        # Check if valid 4-digit year
        if not re.match(r'^\d{4}$', str(gpt_value)):
            # Try to extract year from value
            match = re.search(r'\d{4}', str(gpt_value))
            if match:
                extracted = match.group()
                if self.year_patterns.get(extracted, 0) >= min_support:
                    total = sum(self.year_patterns.values())
                    confidence = self.year_patterns[extracted] / total
                    return MLPrediction(
                        value=extracted,
                        confidence=min(0.95, confidence),
                        support_count=self.year_patterns[extracted],
                        model_type='structured'
                    )
        return None

    def _predict_number(self, gpt_value: str, brand: str, min_support: int) -> Optional[MLPrediction]:
        """Validate card number format for brand."""
        if not gpt_value:
            return None

        brand_lower = (brand or 'unknown').lower().strip()
        brand_patterns = self.number_patterns.get(brand_lower, {})

        # Check if exact match in learned patterns
        if gpt_value in brand_patterns:
            count = brand_patterns[gpt_value]
            if count >= min_support:
                total = sum(brand_patterns.values())
                confidence = count / total
                return MLPrediction(
                    value=gpt_value,
                    confidence=confidence,
                    support_count=count,
                    model_type='structured'
                )

        return None

    def _predict_features(self, gpt_value: str, min_support: int) -> Optional[MLPrediction]:
        """Validate and normalize features."""
        if not gpt_value or gpt_value.lower() == 'none':
            return None

        # Parse features and validate against vocabulary
        features = [f.strip().lower() for f in str(gpt_value).split(',')]
        valid_features = []

        for feature in features:
            if feature and feature != 'none':
                # Check if in vocabulary
                if self.feature_vocabulary.get(feature, 0) >= min_support:
                    valid_features.append(feature)

        if valid_features:
            normalized = ','.join(sorted(set(valid_features)))
            if normalized != gpt_value.lower():
                # Calculate confidence based on feature support
                avg_support = sum(self.feature_vocabulary.get(f, 0) for f in valid_features) / len(valid_features)
                confidence = min(0.90, avg_support / 20)  # Scale to reasonable confidence
                return MLPrediction(
                    value=normalized,
                    confidence=confidence,
                    support_count=int(avg_support),
                    model_type='structured'
                )

        return None

    def _predict_value(self, gpt_value: str, min_support: int) -> Optional[MLPrediction]:
        """Correct value estimate based on learned patterns."""
        if not gpt_value:
            return None

        gpt_stripped = gpt_value.strip()
        if gpt_stripped in self.value_corrections:
            corrections = self.value_corrections[gpt_stripped]
            if corrections:
                best = max(corrections.items(), key=lambda x: x[1])
                if best[1] >= min_support:
                    total = sum(corrections.values())
                    confidence = best[1] / total
                    return MLPrediction(
                        value=best[0],
                        confidence=confidence,
                        support_count=best[1],
                        model_type='structured'
                    )

        return None


class MLCorrectionEngine:
    """Main ML engine that learns from user corrections and applies
    predictions."""

    def __init__(
        self,
        corrections_db: str = "data/corrections.db",
        models_dir: str = "data/ml_models"
    ):
        self.corrections_db = corrections_db
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # Model storage
        self.categorical_models: Dict[str, NaiveBayesClassifier] = {}
        self.text_mappers: Dict[str, TextMapper] = {}
        self.structured_validators: Dict[str, StructuredValidator] = {}

        # Metadata
        self.model_version: Optional[str] = None
        self.last_train_time: Optional[datetime] = None

        # Load or train models
        self._load_or_train_models()

    def _load_or_train_models(self):
        """Load existing models or train new ones if needed."""
        metadata_path = self.models_dir / "metadata.json"

        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                self.model_version = metadata.get('version')
                self.last_train_time = datetime.fromisoformat(
                    metadata['last_train_time']
                ) if metadata.get('last_train_time') else None
                self._load_models()
                return
            except Exception as e:
                print(f"Failed to load models: {e}")

        # Train fresh models
        self._train_all_models()

    def _load_models(self):
        """Load trained models from disk."""
        # Load categorical models
        for field in CATEGORICAL_FIELDS:
            model_path = self.models_dir / f"categorical_{field}.json"
            if model_path.exists():
                with open(model_path, 'r') as f:
                    data = json.load(f)
                model = NaiveBayesClassifier()
                model.class_counts = defaultdict(int, data.get('class_counts', {}))
                model.total_samples = data.get('total_samples', 0)
                # Reconstruct nested defaultdicts
                model.feature_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
                for label, features in data.get('feature_counts', {}).items():
                    for feat_name, values in features.items():
                        for val, count in values.items():
                            model.feature_counts[label][feat_name][val] = count
                model.vocabulary = defaultdict(set)
                for feat_name, values in data.get('vocabulary', {}).items():
                    model.vocabulary[feat_name] = set(values)
                self.categorical_models[field] = model

        # Load text mappers
        for field in TEXT_FIELDS:
            mapper_path = self.models_dir / f"text_{field}.json"
            if mapper_path.exists():
                with open(mapper_path, 'r') as f:
                    data = json.load(f)
                mapper = TextMapper()
                mapper.exact_mappings = defaultdict(lambda: defaultdict(int))
                for k, v in data.get('exact_mappings', {}).items():
                    mapper.exact_mappings[k] = defaultdict(int, v)
                mapper.context_mappings = defaultdict(lambda: defaultdict(int))
                for k, v in data.get('context_mappings', {}).items():
                    # Convert string key back to tuple
                    key = tuple(json.loads(k))
                    mapper.context_mappings[key] = defaultdict(int, v)
                self.text_mappers[field] = mapper

        # Load structured validators
        for field in STRUCTURED_FIELDS:
            validator_path = self.models_dir / f"structured_{field}.json"
            if validator_path.exists():
                with open(validator_path, 'r') as f:
                    data = json.load(f)
                validator = StructuredValidator()
                validator.year_patterns = defaultdict(int, data.get('year_patterns', {}))
                validator.number_patterns = defaultdict(lambda: defaultdict(int))
                for brand, patterns in data.get('number_patterns', {}).items():
                    validator.number_patterns[brand] = defaultdict(int, patterns)
                validator.feature_vocabulary = defaultdict(int, data.get('feature_vocabulary', {}))
                validator.value_corrections = defaultdict(lambda: defaultdict(int))
                for k, v in data.get('value_corrections', {}).items():
                    validator.value_corrections[k] = defaultdict(int, v)
                self.structured_validators[field] = validator

    def _save_models(self):
        """Save trained models to disk."""
        # Save categorical models
        for field, model in self.categorical_models.items():
            model_path = self.models_dir / f"categorical_{field}.json"
            data = {
                'class_counts': dict(model.class_counts),
                'total_samples': model.total_samples,
                'feature_counts': {
                    label: {
                        feat_name: dict(values)
                        for feat_name, values in features.items()
                    }
                    for label, features in model.feature_counts.items()
                },
                'vocabulary': {k: list(v) for k, v in model.vocabulary.items()}
            }
            with open(model_path, 'w') as f:
                json.dump(data, f)

        # Save text mappers
        for field, mapper in self.text_mappers.items():
            mapper_path = self.models_dir / f"text_{field}.json"
            data = {
                'exact_mappings': {k: dict(v) for k, v in mapper.exact_mappings.items()},
                'context_mappings': {
                    json.dumps(k): dict(v) for k, v in mapper.context_mappings.items()
                }
            }
            with open(mapper_path, 'w') as f:
                json.dump(data, f)

        # Save structured validators
        for field, validator in self.structured_validators.items():
            validator_path = self.models_dir / f"structured_{field}.json"
            data = {
                'year_patterns': dict(validator.year_patterns),
                'number_patterns': {k: dict(v) for k, v in validator.number_patterns.items()},
                'feature_vocabulary': dict(validator.feature_vocabulary),
                'value_corrections': {k: dict(v) for k, v in validator.value_corrections.items()}
            }
            with open(validator_path, 'w') as f:
                json.dump(data, f)

        # Save metadata
        metadata = {
            'version': self.model_version,
            'last_train_time': self.last_train_time.isoformat() if self.last_train_time else None,
            'categorical_fields': CATEGORICAL_FIELDS,
            'text_fields': TEXT_FIELDS,
            'structured_fields': STRUCTURED_FIELDS
        }
        with open(self.models_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)

    def _train_all_models(self):
        """Train all model types from corrections database."""
        tracker = CorrectionTracker(self.corrections_db)

        # Check if we have enough data
        total = tracker.get_total_corrections_count()
        if total < 10:
            print(f"Insufficient training data ({total} corrections). Skipping training.")
            return

        print(f"Training ML models on {total} corrections...")

        # Train categorical models
        for field in CATEGORICAL_FIELDS:
            self._train_categorical_model(field, tracker)

        # Train text mappers
        for field in TEXT_FIELDS:
            self._train_text_mapper(field, tracker)

        # Train structured validators
        for field in STRUCTURED_FIELDS:
            self._train_structured_validator(field, tracker)

        # Update metadata
        self.model_version = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.last_train_time = datetime.now()

        # Save models
        self._save_models()

        # Record training metadata
        accuracy_stats = {}
        for field in CATEGORICAL_FIELDS + TEXT_FIELDS:
            stats = tracker.get_ml_accuracy_stats(field)
            if stats['accuracy'] is not None:
                accuracy_stats[field] = stats['accuracy']

        tracker.record_training_metadata(self.model_version, accuracy_stats)

        print(f"ML models trained successfully. Version: {self.model_version}")

    def _train_categorical_model(self, field: str, tracker: CorrectionTracker):
        """Train Naive Bayes model for a categorical field."""
        training_data = tracker.get_training_data(field)
        if len(training_data) < 5:
            return

        # Build feature vectors and labels
        X = []
        y = []
        for item in training_data:
            features = {
                'original': item.get('original_value', ''),
                'brand': item.get('brand', ''),
                'sport': item.get('sport', ''),
                'year': item.get('year', '')
            }
            label = item.get('corrected_value', '')
            if label:
                X.append(features)
                y.append(label)

        if len(y) >= 5:
            model = NaiveBayesClassifier()
            model.fit(X, y)
            self.categorical_models[field] = model

    def _train_text_mapper(self, field: str, tracker: CorrectionTracker):
        """Build text mapper for a text field."""
        training_data = tracker.get_training_data(field)
        if len(training_data) < 5:
            return

        mapper = TextMapper()
        mapper.fit(training_data)
        self.text_mappers[field] = mapper

    def _train_structured_validator(self, field: str, tracker: CorrectionTracker):
        """Build structured validator for a structured field."""
        training_data = tracker.get_training_data(field)
        if len(training_data) < 3:
            return

        validator = StructuredValidator()
        validator.fit(field, training_data)
        self.structured_validators[field] = validator

    def predict(
        self,
        field: str,
        gpt_value: str,
        context: Dict[str, Any]
    ) -> Optional[MLPrediction]:
        """Generate prediction for a single field.

        Args:
            field: Field name to predict
            gpt_value: Current GPT extraction value
            context: Card context (brand, sport, year, etc.)

        Returns:
            MLPrediction if confidence meets threshold, None otherwise
        """
        if not gpt_value:
            return None

        prediction = None

        if field in CATEGORICAL_FIELDS:
            prediction = self._predict_categorical(field, gpt_value, context)
        elif field in TEXT_FIELDS:
            prediction = self._predict_text(field, gpt_value, context)
        elif field in STRUCTURED_FIELDS:
            prediction = self._predict_structured(field, gpt_value, context)

        return prediction

    def _predict_categorical(
        self,
        field: str,
        gpt_value: str,
        context: Dict[str, Any]
    ) -> Optional[MLPrediction]:
        """Predict categorical field value."""
        if field not in self.categorical_models:
            return None

        model = self.categorical_models[field]
        features = {
            'original': gpt_value.lower().strip() if gpt_value else '',
            'brand': (context.get('brand') or '').lower().strip(),
            'sport': (context.get('sport') or '').lower().strip(),
            'year': str(context.get('copyright_year') or '')
        }

        predicted, confidence = model.predict(features)
        if predicted and confidence >= THRESHOLDS['categorical']['confidence']:
            # Calculate support count from class_counts
            support = model.class_counts.get(predicted, 0)
            if support >= THRESHOLDS['categorical']['min_support']:
                return MLPrediction(
                    value=predicted,
                    confidence=confidence,
                    support_count=support,
                    model_type='categorical'
                )
        return None

    def _predict_text(
        self,
        field: str,
        gpt_value: str,
        context: Dict[str, Any]
    ) -> Optional[MLPrediction]:
        """Predict text field value."""
        if field not in self.text_mappers:
            return None

        mapper = self.text_mappers[field]
        prediction = mapper.predict(
            gpt_value,
            brand=context.get('brand'),
            sport=context.get('sport'),
            min_support=THRESHOLDS['text']['min_support']
        )

        if prediction and prediction.confidence >= THRESHOLDS['text']['confidence']:
            return prediction
        return None

    def _predict_structured(
        self,
        field: str,
        gpt_value: str,
        context: Dict[str, Any]
    ) -> Optional[MLPrediction]:
        """Predict structured field value."""
        if field not in self.structured_validators:
            return None

        validator = self.structured_validators[field]
        prediction = validator.predict(
            field,
            gpt_value,
            context,
            min_support=THRESHOLDS['structured']['min_support']
        )

        if prediction and prediction.confidence >= THRESHOLDS['structured']['confidence']:
            return prediction
        return None

    def predict_all_fields(
        self,
        card_data: Dict[str, Any],
        gpt_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply ML predictions to all fields where confidence exceeds
        threshold.

        Args:
            card_data: Current card data (will be modified)
            gpt_data: Original GPT extraction for reference

        Returns:
            Modified card_data with ML predictions applied
        """
        result = card_data.copy()

        # Build context from card data
        context = {
            'brand': card_data.get('brand'),
            'sport': card_data.get('sport'),
            'copyright_year': card_data.get('copyright_year'),
            'card_set': card_data.get('card_set'),
            'name': card_data.get('name')
        }

        all_fields = CATEGORICAL_FIELDS + TEXT_FIELDS + STRUCTURED_FIELDS

        for field in all_fields:
            gpt_value = card_data.get(field)
            if not gpt_value:
                continue

            prediction = self.predict(field, str(gpt_value), context)

            if prediction and prediction.value != str(gpt_value).lower().strip():
                # Apply ML override
                result[field] = prediction.value
                result[f'_ml_{field}_applied'] = True
                result[f'_ml_{field}_confidence'] = prediction.confidence
                result[f'_ml_{field}_gpt_value'] = gpt_value
                result[f'_ml_{field}_support'] = prediction.support_count

                # Log prediction for accuracy tracking
                tracker = CorrectionTracker(self.corrections_db)
                tracker.log_ml_prediction(
                    field=field,
                    gpt_value=str(gpt_value),
                    ml_prediction=prediction.value,
                    confidence=prediction.confidence
                )

        return result

    def retrain_if_needed(self) -> bool:
        """Check criteria and retrain automatically if needed.

        Returns:
            True if retraining occurred, False otherwise
        """
        tracker = CorrectionTracker(self.corrections_db)
        should_train, reason = tracker.should_retrain()

        if should_train:
            print(f"Retraining ML models. Reason: {reason}")
            self._train_all_models()
            return True

        return False


# Singleton instance
_engine: Optional[MLCorrectionEngine] = None


def get_ml_engine() -> MLCorrectionEngine:
    """Get singleton ML engine instance."""
    global _engine
    if _engine is None:
        _engine = MLCorrectionEngine()
    return _engine


def reset_ml_engine():
    """Reset the singleton instance (useful for testing)."""
    global _engine
    _engine = None
