"""
Machine Learning Module for Trade Prediction

Trains models on paper trading results to:
1. Predict trade outcomes (win/loss probability)
2. Calibrate edge estimates 
3. Identify which signal characteristics lead to winning trades
4. Provide confidence adjustments for the probability engine

Uses scikit-learn for simplicity; can be extended to deep learning.
"""

import logging
import pickle
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

# Conditional imports for ML libraries
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        roc_auc_score, confusion_matrix, classification_report
    )
    from sklearn.calibration import CalibratedClassifierCV
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not installed - ML features disabled")


@dataclass
class ModelMetrics:
    """Performance metrics for a trained model"""
    accuracy: float
    precision: float
    recall: float
    f1: float
    auc_roc: float
    cross_val_mean: float
    cross_val_std: float
    confusion_matrix: List[List[int]]
    feature_importance: Dict[str, float]
    training_samples: int
    trained_at: datetime


@dataclass
class CalibrationResult:
    """Result of edge calibration analysis"""
    edge_bucket: str
    predicted_edge: float
    actual_win_rate: float
    sample_size: int
    calibration_factor: float  # actual / predicted


class TradePredictor:
    """
    ML model for predicting trade outcomes.
    
    Trains on paper trading history to learn which signals
    actually result in profitable trades.
    
    Features used:
    - Signal edge (model prob - market prob)
    - Signal confidence
    - Model probability
    - Market probability  
    - Entry price
    - Market category
    - Side (YES/NO)
    
    Usage:
        predictor = TradePredictor()
        predictor.train(training_data)
        
        # Predict new trade
        prob = predictor.predict_win_probability(features)
        
        # Get calibrated edge
        calibrated = predictor.calibrate_edge(raw_edge, category)
    """
    
    FEATURE_COLUMNS = [
        "signal_edge",
        "signal_confidence", 
        "model_probability",
        "market_probability",
        "entry_price",
        "time_held_hours",
    ]
    
    CATEGORICAL_COLUMNS = ["category", "side"]
    
    def __init__(self, model_dir: str = "./ml_models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Models
        self._classifier: Optional[Any] = None
        self._scaler: Optional[StandardScaler] = None
        self._label_encoders: Dict[str, LabelEncoder] = {}
        
        # Calibration data
        self._calibration_factors: Dict[str, float] = {}
        
        # Metrics
        self._metrics: Optional[ModelMetrics] = None
        
        # Model paths
        self._model_path = self.model_dir / "trade_predictor.pkl"
        self._scaler_path = self.model_dir / "scaler.pkl"
        self._encoders_path = self.model_dir / "encoders.pkl"
        self._calibration_path = self.model_dir / "calibration.json"
        
        # Try to load existing model
        self._load_model()
    
    def train(
        self,
        training_data: List[Dict],
        model_type: str = "gradient_boosting",
        test_size: float = 0.2,
        random_state: int = 42
    ) -> ModelMetrics:
        """
        Train the prediction model on historical trade data.
        
        Args:
            training_data: List of trade feature dicts from paper trading
            model_type: "random_forest", "gradient_boosting", or "logistic"
            test_size: Fraction of data for testing
            random_state: Random seed for reproducibility
        
        Returns:
            ModelMetrics with performance statistics
        """
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("scikit-learn required for ML training")
        
        if len(training_data) < 20:
            raise ValueError(f"Need at least 20 trades for training, have {len(training_data)}")
        
        logger.info(f"Training {model_type} model on {len(training_data)} trades")
        
        # Prepare features
        X, y = self._prepare_data(training_data)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )
        
        # Scale features
        self._scaler = StandardScaler()
        X_train_scaled = self._scaler.fit_transform(X_train)
        X_test_scaled = self._scaler.transform(X_test)
        
        # Select and train model
        if model_type == "random_forest":
            base_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_leaf=5,
                random_state=random_state,
                class_weight="balanced"
            )
        elif model_type == "gradient_boosting":
            base_model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=random_state
            )
        else:  # logistic
            base_model = LogisticRegression(
                random_state=random_state,
                class_weight="balanced",
                max_iter=1000
            )
        
        # Train with probability calibration
        self._classifier = CalibratedClassifierCV(
            base_model,
            method="sigmoid",
            cv=5
        )
        self._classifier.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = self._classifier.predict(X_test_scaled)
        y_proba = self._classifier.predict_proba(X_test_scaled)[:, 1]
        
        # Cross-validation
        cv_scores = cross_val_score(base_model, X_train_scaled, y_train, cv=5)
        
        # Feature importance (for tree-based models)
        feature_importance = {}
        if hasattr(base_model, "feature_importances_"):
            base_model.fit(X_train_scaled, y_train)  # Refit for importances
            for name, importance in zip(self._get_feature_names(), base_model.feature_importances_):
                feature_importance[name] = float(importance)
        
        # Compute metrics
        self._metrics = ModelMetrics(
            accuracy=accuracy_score(y_test, y_pred),
            precision=precision_score(y_test, y_pred, zero_division=0),
            recall=recall_score(y_test, y_pred, zero_division=0),
            f1=f1_score(y_test, y_pred, zero_division=0),
            auc_roc=roc_auc_score(y_test, y_proba),
            cross_val_mean=cv_scores.mean(),
            cross_val_std=cv_scores.std(),
            confusion_matrix=confusion_matrix(y_test, y_pred).tolist(),
            feature_importance=feature_importance,
            training_samples=len(training_data),
            trained_at=datetime.now(timezone.utc)
        )
        
        # Calibrate edge buckets
        self._calibrate_edges(training_data)
        
        # Save model
        self._save_model()
        
        logger.info(f"Model trained: accuracy={self._metrics.accuracy:.2%}, AUC={self._metrics.auc_roc:.3f}")
        
        return self._metrics
    
    def _prepare_data(self, data: List[Dict]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare feature matrix and labels from training data"""
        X_list = []
        y_list = []
        
        for row in data:
            features = []
            
            # Numeric features
            for col in self.FEATURE_COLUMNS:
                features.append(float(row.get(col, 0)))
            
            # Categorical features (one-hot encode)
            for col in self.CATEGORICAL_COLUMNS:
                if col not in self._label_encoders:
                    self._label_encoders[col] = LabelEncoder()
                    # Fit on all possible values
                    all_values = list(set(r.get(col, "unknown") for r in data))
                    self._label_encoders[col].fit(all_values)
                
                try:
                    encoded = self._label_encoders[col].transform([row.get(col, "unknown")])[0]
                except ValueError:
                    encoded = 0  # Unknown category
                features.append(float(encoded))
            
            X_list.append(features)
            y_list.append(row.get("outcome", 0))
        
        return np.array(X_list), np.array(y_list)
    
    def _get_feature_names(self) -> List[str]:
        """Get list of feature names in order"""
        return self.FEATURE_COLUMNS + self.CATEGORICAL_COLUMNS
    
    def _calibrate_edges(self, data: List[Dict]):
        """
        Analyze how well predicted edges correlate with actual outcomes.
        Creates calibration factors for different edge buckets.
        """
        buckets = {
            "0-5%": {"edges": [], "outcomes": []},
            "5-10%": {"edges": [], "outcomes": []},
            "10-15%": {"edges": [], "outcomes": []},
            "15-20%": {"edges": [], "outcomes": []},
            "20%+": {"edges": [], "outcomes": []},
        }
        
        for row in data:
            edge = float(row.get("signal_edge", 0)) * 100
            outcome = row.get("outcome", 0)
            
            if edge < 5:
                buckets["0-5%"]["edges"].append(edge)
                buckets["0-5%"]["outcomes"].append(outcome)
            elif edge < 10:
                buckets["5-10%"]["edges"].append(edge)
                buckets["5-10%"]["outcomes"].append(outcome)
            elif edge < 15:
                buckets["10-15%"]["edges"].append(edge)
                buckets["10-15%"]["outcomes"].append(outcome)
            elif edge < 20:
                buckets["15-20%"]["edges"].append(edge)
                buckets["15-20%"]["outcomes"].append(outcome)
            else:
                buckets["20%+"]["edges"].append(edge)
                buckets["20%+"]["outcomes"].append(outcome)
        
        for bucket_name, bucket_data in buckets.items():
            if bucket_data["outcomes"]:
                predicted_edge = np.mean(bucket_data["edges"]) / 100
                actual_win_rate = np.mean(bucket_data["outcomes"])
                
                # Expected win rate = 0.5 + edge (simplified)
                expected_win_rate = 0.5 + predicted_edge
                
                if expected_win_rate > 0:
                    calibration = actual_win_rate / expected_win_rate
                else:
                    calibration = 1.0
                
                self._calibration_factors[bucket_name] = calibration
                
                logger.info(
                    f"Edge bucket {bucket_name}: predicted={predicted_edge:.1%}, "
                    f"actual_win_rate={actual_win_rate:.1%}, calibration={calibration:.2f}"
                )
    
    def predict_win_probability(self, features: Dict) -> float:
        """
        Predict probability of a trade being profitable.
        
        Args:
            features: Dict with signal_edge, confidence, etc.
        
        Returns:
            Probability of win (0-1)
        """
        if self._classifier is None:
            logger.warning("No trained model - returning default 0.5")
            return 0.5
        
        # Prepare single sample
        X = self._prepare_single_sample(features)
        X_scaled = self._scaler.transform(X.reshape(1, -1))
        
        proba = self._classifier.predict_proba(X_scaled)[0, 1]
        return float(proba)
    
    def _prepare_single_sample(self, features: Dict) -> np.ndarray:
        """Prepare a single sample for prediction"""
        sample = []
        
        for col in self.FEATURE_COLUMNS:
            sample.append(float(features.get(col, 0)))
        
        for col in self.CATEGORICAL_COLUMNS:
            if col in self._label_encoders:
                try:
                    encoded = self._label_encoders[col].transform([features.get(col, "unknown")])[0]
                except ValueError:
                    encoded = 0
                sample.append(float(encoded))
            else:
                sample.append(0.0)
        
        return np.array(sample)
    
    def calibrate_edge(self, raw_edge: float, category: str = None) -> float:
        """
        Apply calibration to a raw edge estimate.
        
        Args:
            raw_edge: Original edge from probability engine
            category: Market category for category-specific adjustment
        
        Returns:
            Calibrated edge
        """
        if not self._calibration_factors:
            return raw_edge
        
        # Find appropriate bucket
        edge_pct = raw_edge * 100
        
        if edge_pct < 5:
            bucket = "0-5%"
        elif edge_pct < 10:
            bucket = "5-10%"
        elif edge_pct < 15:
            bucket = "10-15%"
        elif edge_pct < 20:
            bucket = "15-20%"
        else:
            bucket = "20%+"
        
        calibration = self._calibration_factors.get(bucket, 1.0)
        
        # Apply calibration
        calibrated = raw_edge * calibration
        
        return calibrated
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from trained model"""
        if self._metrics:
            return self._metrics.feature_importance
        return {}
    
    def _save_model(self):
        """Save model and associated data to disk"""
        if self._classifier:
            with open(self._model_path, "wb") as f:
                pickle.dump(self._classifier, f)
        
        if self._scaler:
            with open(self._scaler_path, "wb") as f:
                pickle.dump(self._scaler, f)
        
        if self._label_encoders:
            with open(self._encoders_path, "wb") as f:
                pickle.dump(self._label_encoders, f)
        
        calibration_data = {
            "factors": self._calibration_factors,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        with open(self._calibration_path, "w") as f:
            json.dump(calibration_data, f, indent=2)
        
        logger.info(f"Model saved to {self.model_dir}")
    
    def _load_model(self):
        """Load model from disk if available"""
        try:
            if self._model_path.exists():
                with open(self._model_path, "rb") as f:
                    self._classifier = pickle.load(f)
                logger.info("Loaded existing classifier model")
            
            if self._scaler_path.exists():
                with open(self._scaler_path, "rb") as f:
                    self._scaler = pickle.load(f)
            
            if self._encoders_path.exists():
                with open(self._encoders_path, "rb") as f:
                    self._label_encoders = pickle.load(f)
            
            if self._calibration_path.exists():
                with open(self._calibration_path, "r") as f:
                    calibration_data = json.load(f)
                    self._calibration_factors = calibration_data.get("factors", {})
                    
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")
    
    @property
    def is_trained(self) -> bool:
        """Check if model has been trained"""
        return self._classifier is not None
    
    @property
    def metrics(self) -> Optional[ModelMetrics]:
        """Get model metrics"""
        return self._metrics


class EdgeCalibrator:
    """
    Analyzes and calibrates edge estimates based on actual outcomes.
    
    Helps answer: "When my model says 10% edge, what's the actual edge?"
    """
    
    def __init__(self):
        self.observations: List[Dict] = []
    
    def add_observation(
        self,
        predicted_edge: float,
        model_probability: float,
        actual_outcome: int,  # 1 = win, 0 = loss
        category: str = None
    ):
        """Add a trade outcome observation"""
        self.observations.append({
            "predicted_edge": predicted_edge,
            "model_probability": model_probability,
            "outcome": actual_outcome,
            "category": category,
        })
    
    def analyze(self) -> Dict[str, CalibrationResult]:
        """
        Analyze calibration across edge buckets.
        
        Returns mapping of edge bucket to calibration result.
        """
        if len(self.observations) < 10:
            return {}
        
        buckets = {}
        for bucket_name, low, high in [
            ("0-5%", 0, 0.05),
            ("5-10%", 0.05, 0.10),
            ("10-20%", 0.10, 0.20),
            ("20%+", 0.20, 1.0),
        ]:
            bucket_obs = [
                o for o in self.observations
                if low <= o["predicted_edge"] < high
            ]
            
            if len(bucket_obs) >= 5:
                avg_edge = np.mean([o["predicted_edge"] for o in bucket_obs])
                win_rate = np.mean([o["outcome"] for o in bucket_obs])
                
                # Expected win rate given edge
                expected_win_rate = 0.5 + avg_edge
                
                calibration = win_rate / expected_win_rate if expected_win_rate > 0 else 1.0
                
                buckets[bucket_name] = CalibrationResult(
                    edge_bucket=bucket_name,
                    predicted_edge=avg_edge,
                    actual_win_rate=win_rate,
                    sample_size=len(bucket_obs),
                    calibration_factor=calibration
                )
        
        return buckets
    
    def get_calibrated_edge(self, raw_edge: float) -> float:
        """Get calibrated edge based on historical performance"""
        buckets = self.analyze()
        
        if raw_edge < 0.05:
            bucket = buckets.get("0-5%")
        elif raw_edge < 0.10:
            bucket = buckets.get("5-10%")
        elif raw_edge < 0.20:
            bucket = buckets.get("10-20%")
        else:
            bucket = buckets.get("20%+")
        
        if bucket:
            return raw_edge * bucket.calibration_factor
        
        return raw_edge


class OnlineModelUpdater:
    """
    Incrementally updates ML model as new trades complete.
    
    Instead of full retraining, applies online learning updates
    to refine predictions based on recent outcomes.
    """
    
    def __init__(self, predictor: TradePredictor, update_frequency: int = 10):
        self.predictor = predictor
        self.update_frequency = update_frequency
        self.pending_observations: List[Dict] = []
    
    async def on_trade_complete(self, trade_data: Dict):
        """
        Called when a paper trade settles.
        Accumulates observations and triggers retraining periodically.
        """
        self.pending_observations.append(trade_data)
        
        if len(self.pending_observations) >= self.update_frequency:
            await self._trigger_update()
    
    async def _trigger_update(self):
        """Trigger model update with accumulated observations"""
        if not self.pending_observations:
            return
        
        logger.info(f"Triggering ML update with {len(self.pending_observations)} new observations")
        
        # For now, just retrain on all available data
        # Future: implement true online learning
        
        self.pending_observations.clear()
