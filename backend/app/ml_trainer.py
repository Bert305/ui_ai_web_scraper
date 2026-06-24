"""Train a scikit-learn model from an uploaded spreadsheet.

The user picks a target column; we auto-detect (or are told) whether the problem
is classification or regression, build a robust preprocessing + model pipeline,
train/evaluate on a hold-out split, and return exact metrics plus chart-ready
data so the frontend can visualize how the model relates to the target:

  * target distribution (class balance, or a histogram for regression)
  * feature importances toward the target
  * predicted-vs-actual scatter (regression) / confusion matrix (classification)
  * residuals (regression)

No AI is involved here — the numbers come straight from scikit-learn, so they are
reproducible. We reuse the file-reading and profiling helpers from data_analyzer.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .data_analyzer import _jsonsafe, profile_dataframe, read_table

# Columns with more distinct categorical values than this are treated as free-text
# identifiers (names, URLs, ids) and excluded from the feature set — one-hot
# encoding them would explode dimensionality and leak row identity.
_MAX_CATEGORICAL_CARDINALITY = 50

# Hard cap on rows used for training so very large uploads stay responsive.
_MAX_TRAIN_ROWS = 100_000


# --------------------------------------------------------------------------- #
# Inspection (step 1 — let the user pick a target column)
# --------------------------------------------------------------------------- #
def inspect_columns(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Read the file and return a profile so the frontend can populate a target
    dropdown and suggest a sensible default task per column."""
    df = read_table(file_bytes, filename)
    profile = profile_dataframe(df)
    for col in profile["columns"]:
        series = df[col["name"]]
        col["suggested_task"] = _detect_task(series)
    return profile


# --------------------------------------------------------------------------- #
# Task auto-detection
# --------------------------------------------------------------------------- #
def _detect_task(series: pd.Series) -> str:
    """Heuristic: is predicting this column a classification or regression task?

    Non-numeric (or boolean) targets are always classification. Numeric targets
    are classification when they look like a small set of discrete labels
    (few unique, integer-like) and regression otherwise.
    """
    s = series.dropna()
    if s.empty:
        return "classification"

    if pd.api.types.is_bool_dtype(s):
        return "classification"

    if not pd.api.types.is_numeric_dtype(s):
        return "classification"

    nunique = int(s.nunique())
    if nunique <= 2:
        return "classification"

    integer_like = bool(np.all(np.equal(np.mod(s.to_numpy(dtype="float64"), 1), 0)))
    ratio = nunique / len(s)
    if integer_like and (nunique <= 15 or ratio < 0.05):
        return "classification"
    return "regression"


def _resolve_task(task: Optional[str], series: pd.Series) -> Tuple[str, bool]:
    """Return (task, auto_detected). `task` may be auto/classification/regression."""
    task = (task or "auto").strip().lower()
    if task in ("classification", "regression"):
        return task, False
    return _detect_task(series), True


# --------------------------------------------------------------------------- #
# Feature selection + preprocessing
# --------------------------------------------------------------------------- #
def _select_features(
    df: pd.DataFrame, target: str
) -> Tuple[List[str], List[str], List[str]]:
    """Split the non-target columns into usable numeric and categorical features,
    skipping constant columns, all-null columns, and high-cardinality text."""
    numeric: List[str] = []
    categorical: List[str] = []
    skipped: List[str] = []

    for name in df.columns:
        if name == target:
            continue
        series = df[name]
        if series.notna().sum() == 0 or series.nunique(dropna=True) <= 1:
            skipped.append(name)
            continue
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            numeric.append(name)
        else:
            if series.nunique(dropna=True) <= _MAX_CATEGORICAL_CARDINALITY:
                categorical.append(name)
            else:
                skipped.append(name)

    return numeric, categorical, skipped


def _build_preprocessor(numeric: List[str], categorical: List[str], scale: bool) -> ColumnTransformer:
    numeric_steps: List[Tuple[str, Any]] = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        numeric_steps.append(("scale", StandardScaler()))

    # OneHotEncoder gained `sparse_output` in sklearn 1.2; fall back for older.
    try:
        ohe = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:  # pragma: no cover - very old sklearn
        ohe = OneHotEncoder(handle_unknown="ignore", sparse=False)

    categorical_steps = [
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("onehot", ohe),
    ]

    transformers = []
    if numeric:
        transformers.append(("num", Pipeline(numeric_steps), numeric))
    if categorical:
        transformers.append(("cat", Pipeline(categorical_steps), categorical))

    return ColumnTransformer(transformers=transformers, remainder="drop")


# --------------------------------------------------------------------------- #
# Model selection
# --------------------------------------------------------------------------- #
_CLASSIFIERS = {
    "random_forest": ("Random Forest Classifier", lambda: RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)),
    "gradient_boosting": ("Gradient Boosting Classifier", lambda: GradientBoostingClassifier(random_state=42)),
    "logistic_regression": ("Logistic Regression", lambda: LogisticRegression(max_iter=1000)),
}
_REGRESSORS = {
    "random_forest": ("Random Forest Regressor", lambda: RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=-1)),
    "gradient_boosting": ("Gradient Boosting Regressor", lambda: GradientBoostingRegressor(random_state=42)),
    "linear_regression": ("Linear Regression", lambda: LinearRegression()),
}

# Models that need their inputs scaled to behave well.
_NEEDS_SCALING = {"logistic_regression", "linear_regression"}


def _resolve_model(task: str, model: Optional[str]) -> Tuple[str, str, Any]:
    """Return (model_key, display_name, estimator). `auto` -> random_forest."""
    registry = _CLASSIFIERS if task == "classification" else _REGRESSORS
    key = (model or "auto").strip().lower()
    if key in ("auto", ""):
        key = "random_forest"
    # "linear" is a task-agnostic alias the frontend can send before the task is
    # known: logistic regression for classification, linear regression otherwise.
    if key in ("linear", "logistic"):
        key = "logistic_regression" if task == "classification" else "linear_regression"
    if key not in registry:
        valid = ", ".join(registry)
        raise RuntimeError(f"Unknown model '{key}' for {task}. Choose one of: auto, {valid}.")
    display_name, factory = registry[key]
    return key, display_name, factory()


# --------------------------------------------------------------------------- #
# Feature-importance extraction
# --------------------------------------------------------------------------- #
def _feature_importances(estimator: Any, feature_names: List[str]) -> List[Dict[str, Any]]:
    """Pull importances from tree models (feature_importances_) or linear models
    (coef_), normalize, and return the top features as chart data."""
    importances: Optional[np.ndarray] = None
    if hasattr(estimator, "feature_importances_"):
        importances = np.asarray(estimator.feature_importances_, dtype="float64")
    elif hasattr(estimator, "coef_"):
        coef = np.asarray(estimator.coef_, dtype="float64")
        importances = np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef)

    if importances is None or len(importances) != len(feature_names):
        return []

    total = importances.sum()
    if total > 0:
        importances = importances / total

    pairs = sorted(zip(feature_names, importances), key=lambda p: p[1], reverse=True)
    return [
        {"x": str(name), "y": _jsonsafe(float(value))}
        for name, value in pairs[:15]
        if value > 0
    ]


def _clean_feature_name(name: str) -> str:
    """ColumnTransformer prefixes names like 'num__age' / 'cat__region_East'.
    Strip the transformer prefix for display."""
    return re.sub(r"^(num|cat)__", "", name)


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _target_distribution_chart(y: pd.Series, task: str) -> Optional[Dict[str, Any]]:
    s = y.dropna()
    if s.empty:
        return None

    if task == "classification":
        counts = s.astype(str).value_counts().head(30)
        data = [{"x": str(idx), "y": int(val)} for idx, val in counts.items()]
        return {
            "title": "Target distribution (class balance)",
            "type": "bar",
            "x_label": str(y.name),
            "y_label": "count",
            "data": data,
        }

    # regression -> histogram
    numeric = pd.to_numeric(s, errors="coerce").dropna()
    if numeric.empty:
        return None
    counts, edges = np.histogram(numeric, bins=min(20, max(5, int(np.sqrt(len(numeric))))))
    data = [
        {"x": f"{edges[i]:.2f}–{edges[i + 1]:.2f}", "y": int(counts[i])}
        for i in range(len(counts))
    ]
    return {
        "title": "Target distribution (histogram)",
        "type": "bar",
        "x_label": str(y.name),
        "y_label": "count",
        "data": data,
    }


def _regression_charts(y_true: np.ndarray, y_pred: np.ndarray) -> List[Dict[str, Any]]:
    n = min(len(y_true), 500)  # cap scatter points for the browser
    idx = np.linspace(0, len(y_true) - 1, n).astype(int) if len(y_true) > n else np.arange(len(y_true))
    actual = y_true[idx]
    pred = y_pred[idx]
    residuals = actual - pred

    pred_vs_actual = {
        "title": "Predicted vs. actual",
        "type": "scatter",
        "x_label": "actual",
        "y_label": "predicted",
        "data": [{"x": _jsonsafe(float(a)), "y": _jsonsafe(float(p))} for a, p in zip(actual, pred)],
    }
    residual_chart = {
        "title": "Residuals (actual − predicted)",
        "type": "scatter",
        "x_label": "predicted",
        "y_label": "residual",
        "data": [{"x": _jsonsafe(float(p)), "y": _jsonsafe(float(r))} for p, r in zip(pred, residuals)],
    }
    return [pred_vs_actual, residual_chart]


def _confusion_chart(y_true: np.ndarray, y_pred: np.ndarray, labels: List[Any]) -> Dict[str, Any]:
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        "title": "Confusion matrix",
        "type": "matrix",
        "labels": [str(label) for label in labels],
        "matrix": [[int(v) for v in row] for row in matrix],
    }


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
    return {
        "accuracy": _jsonsafe(round(float(accuracy_score(y_true, y_pred)), 4)),
        "f1_weighted": _jsonsafe(round(float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 4)),
        "precision_weighted": _jsonsafe(round(float(precision_score(y_true, y_pred, average="weighted", zero_division=0)), 4)),
        "recall_weighted": _jsonsafe(round(float(recall_score(y_true, y_pred, average="weighted", zero_division=0)), 4)),
    }


def _regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return {
        "r2": _jsonsafe(round(float(r2_score(y_true, y_pred)), 4)),
        "mae": _jsonsafe(round(float(mean_absolute_error(y_true, y_pred)), 4)),
        "rmse": _jsonsafe(round(rmse, 4)),
    }


def _metric_kpis(task: str, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn the raw metrics into labelled KPI cards the frontend already renders."""
    if task == "classification":
        spec = [
            ("Accuracy", "accuracy", "share of correct predictions on held-out data"),
            ("F1 (weighted)", "f1_weighted", "balance of precision and recall across classes"),
            ("Precision (weighted)", "precision_weighted", "of predicted positives, how many were right"),
            ("Recall (weighted)", "recall_weighted", "of actual positives, how many were found"),
        ]
        return [
            {"label": label, "value": metrics[key], "formatted": f"{metrics[key] * 100:.1f}%", "description": desc}
            for label, key, desc in spec
            if metrics.get(key) is not None
        ]

    spec = [
        ("R²", "r2", "fraction of variance explained (1.0 is perfect)"),
        ("MAE", "mae", "mean absolute error in target units"),
        ("RMSE", "rmse", "root mean squared error in target units"),
    ]
    out = []
    for label, key, desc in spec:
        value = metrics.get(key)
        if value is None:
            continue
        formatted = f"{value:.3f}" if key == "r2" else f"{value:,.3f}"
        out.append({"label": label, "value": value, "formatted": formatted, "description": desc})
    return out


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def _build_summary(
    task: str, model_name: str, target: str, metrics: Dict[str, Any], n_features: int, n_rows: int
) -> str:
    if task == "classification":
        headline = f"{metrics.get('accuracy', 0) * 100:.1f}% accuracy"
    else:
        headline = f"R² of {metrics.get('r2', 0):.3f}"
    return (
        f"Trained a {model_name} to predict '{target}' ({task}) on {n_rows:,} rows "
        f"using {n_features} engineered features. On a held-out test split it reached {headline}."
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def train_model(
    file_bytes: bytes,
    filename: str,
    target: str,
    task: Optional[str] = None,
    model: Optional[str] = None,
    test_size: float = 0.2,
    include_python: bool = False,
) -> Dict[str, Any]:
    if not target or not target.strip():
        raise RuntimeError("No target column selected — pick the column you want to predict.")
    target = target.strip()

    df = read_table(file_bytes, filename)
    if target not in df.columns:
        raise RuntimeError(f"Target column '{target}' is not in the file. Columns: {', '.join(map(str, df.columns))}")

    # Drop rows with a missing target — we can't learn or score those.
    df = df[df[target].notna()].copy()
    if len(df) < 10:
        raise RuntimeError("Need at least 10 rows with a non-empty target to train a model.")

    if len(df) > _MAX_TRAIN_ROWS:
        df = df.sample(_MAX_TRAIN_ROWS, random_state=42).reset_index(drop=True)

    resolved_task, auto_detected = _resolve_task(task, df[target])

    numeric, categorical, skipped = _select_features(df, target)
    if not numeric and not categorical:
        raise RuntimeError("No usable feature columns found (all were constant, empty, or high-cardinality text).")

    X = df[numeric + categorical]
    y = df[target]

    if resolved_task == "classification":
        y = y.astype(str)
        class_counts = y.value_counts()
        if len(class_counts) < 2:
            raise RuntimeError("The target has only one class — classification needs at least two.")
    else:
        y = pd.to_numeric(y, errors="coerce")
        mask = y.notna()
        X, y = X[mask], y[mask]
        if len(y) < 10:
            raise RuntimeError("The target could not be parsed as numbers for regression. Try classification instead.")

    test_size = min(max(float(test_size or 0.2), 0.1), 0.5)

    # Stratify classification splits when every class has at least 2 samples.
    stratify = None
    if resolved_task == "classification" and y.value_counts().min() >= 2:
        stratify = y

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=stratify
    )

    model_key, model_name, estimator = _resolve_model(resolved_task, model)
    preprocessor = _build_preprocessor(numeric, categorical, scale=model_key in _NEEDS_SCALING)
    pipeline = Pipeline([("prep", preprocessor), ("model", estimator)])
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_test_arr = y_test.to_numpy()

    # Resolve engineered feature names for importance reporting.
    try:
        raw_names = list(pipeline.named_steps["prep"].get_feature_names_out())
        feature_names = [_clean_feature_name(n) for n in raw_names]
    except Exception:
        feature_names = numeric + categorical

    importances = _feature_importances(pipeline.named_steps["model"], feature_names)

    charts: List[Dict[str, Any]] = []
    dist = _target_distribution_chart(df[target], resolved_task)
    if dist:
        charts.append(dist)
    if importances:
        charts.append({
            "title": "Feature importance (toward the target)",
            "type": "bar",
            "x_label": "feature",
            "y_label": "importance",
            "data": importances,
        })

    if resolved_task == "classification":
        metrics = _classification_metrics(y_test_arr, y_pred)
        labels = sorted(pd.unique(np.concatenate([y_test_arr, y_pred])).tolist(), key=str)
        charts.append(_confusion_chart(y_test_arr, y_pred, labels))
    else:
        metrics = _regression_metrics(y_test_arr, y_pred)
        charts.extend(_regression_charts(y_test_arr.astype("float64"), np.asarray(y_pred, dtype="float64")))

    kpis = _metric_kpis(resolved_task, metrics)
    summary = _build_summary(resolved_task, model_name, target, metrics, len(feature_names), len(X_train))

    python_code = (
        _render_python(filename, target, resolved_task, model_key, numeric, categorical, test_size)
        if include_python
        else None
    )

    return {
        "target": target,
        "task": resolved_task,
        "task_auto_detected": auto_detected,
        "model_key": model_key,
        "model_name": model_name,
        "n_rows_used": int(len(X)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_features": len(feature_names),
        "feature_columns": numeric + categorical,
        "skipped_columns": skipped,
        "metrics": metrics,
        "kpis": kpis,
        "charts": charts,
        "summary": summary,
        "python_code": python_code,
    }


# --------------------------------------------------------------------------- #
# Reproducible Python script (deterministic — mirrors the pipeline above)
# --------------------------------------------------------------------------- #
def _render_python(
    filename: str,
    target: str,
    task: str,
    model_key: str,
    numeric: List[str],
    categorical: List[str],
    test_size: float,
) -> str:
    if task == "classification":
        imports = {
            "random_forest": "from sklearn.ensemble import RandomForestClassifier as Model",
            "gradient_boosting": "from sklearn.ensemble import GradientBoostingClassifier as Model",
            "logistic_regression": "from sklearn.linear_model import LogisticRegression as Model",
        }[model_key]
        ctor = {
            "random_forest": "Model(n_estimators=200, random_state=42, n_jobs=-1)",
            "gradient_boosting": "Model(random_state=42)",
            "logistic_regression": "Model(max_iter=1000)",
        }[model_key]
        metric_imports = (
            "from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, ConfusionMatrixDisplay"
        )
        eval_block = (
            "    print('Accuracy:', round(accuracy_score(y_test, y_pred), 4))\n"
            "    print('F1 (weighted):', round(f1_score(y_test, y_pred, average='weighted', zero_division=0), 4))\n"
            "    print('Confusion matrix:\\n', confusion_matrix(y_test, y_pred))"
        )
        target_prep = "    y = df[TARGET].astype(str)"
        # Confusion-matrix heatmap = predicted vs. actual classes.
        plot_block = (
            "    # Confusion-matrix heatmap (predicted vs. actual classes)\n"
            "    fig, ax = plt.subplots(figsize=(6, 5))\n"
            "    ConfusionMatrixDisplay.from_predictions(y_test, y_pred, ax=ax, cmap='Blues',\n"
            "                                            colorbar=False, xticks_rotation=45)\n"
            f"    ax.set_title({repr(f'Predicted vs. actual: {target}')})\n"
            "    fig.tight_layout(); fig.savefig('predicted_vs_actual.png', dpi=150); plt.close(fig)\n"
            "    print('Saved predicted_vs_actual.png')"
        )
    else:
        imports = {
            "random_forest": "from sklearn.ensemble import RandomForestRegressor as Model",
            "gradient_boosting": "from sklearn.ensemble import GradientBoostingRegressor as Model",
            "linear_regression": "from sklearn.linear_model import LinearRegression as Model",
        }[model_key]
        ctor = {
            "random_forest": "Model(n_estimators=200, random_state=42, n_jobs=-1)",
            "gradient_boosting": "Model(random_state=42)",
            "linear_regression": "Model()",
        }[model_key]
        metric_imports = "from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error"
        eval_block = (
            "    print('R2:', round(r2_score(y_test, y_pred), 4))\n"
            "    print('MAE:', round(mean_absolute_error(y_test, y_pred), 4))\n"
            "    print('RMSE:', round(mean_squared_error(y_test, y_pred) ** 0.5, 4))"
        )
        target_prep = "    y = pd.to_numeric(df[TARGET], errors='coerce')\n    df = df[y.notna()]; y = y.dropna()"
        # Predicted-vs-actual scatter with a y=x perfect-fit reference line.
        plot_block = (
            "    # Predicted vs. actual (points on the dashed line are perfect predictions)\n"
            "    fig, ax = plt.subplots(figsize=(6, 6))\n"
            "    ax.scatter(y_test, y_pred, alpha=0.6, edgecolors='none')\n"
            "    lo = float(min(y_test.min(), y_pred.min()))\n"
            "    hi = float(max(y_test.max(), y_pred.max()))\n"
            "    ax.plot([lo, hi], [lo, hi], 'r--', linewidth=1, label='perfect prediction')\n"
            "    ax.set_xlabel('Actual'); ax.set_ylabel('Predicted'); ax.legend()\n"
            f"    ax.set_title({repr(f'Predicted vs. actual: {target}')})\n"
            "    fig.tight_layout(); fig.savefig('predicted_vs_actual.png', dpi=150); plt.close(fig)\n"
            "    print('Saved predicted_vs_actual.png')"
        )

    scale = model_key in _NEEDS_SCALING
    numeric_steps = "[('impute', SimpleImputer(strategy='median'))" + (
        ", ('scale', StandardScaler())]" if scale else "]"
    )
    safe_name = filename or "data.csv"
    fi_title = repr(f"Feature importance toward {target}")

    return f'''#!/usr/bin/env python3
"""Reproducible training script for predicting {target!r} ({task}).

Mirrors the Train Model tool's pipeline, so its metrics match.

Setup:
    pip install pandas scikit-learn matplotlib openpyxl
Run:
    python train_model.py [path-to-data-file]
"""
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import train_test_split
{imports}
{metric_imports}

DATA_FILE = sys.argv[1] if len(sys.argv) > 1 else {safe_name!r}
TARGET = {target!r}
NUMERIC = {numeric!r}
CATEGORICAL = {categorical!r}
TEST_SIZE = {test_size!r}


def load_table(path):
    name = path.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(path)
    if name.endswith(".json"):
        return pd.read_json(path)
    sep = "\\t" if name.endswith(".tsv") else ","
    return pd.read_csv(path, sep=sep)


def main():
    df = load_table(DATA_FILE)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df[TARGET].notna()].copy()
{target_prep}

    X = df[NUMERIC + CATEGORICAL]
    num_pipe = Pipeline({numeric_steps})
    cat_pipe = Pipeline([('impute', SimpleImputer(strategy='most_frequent')),
                         ('onehot', OneHotEncoder(handle_unknown='ignore'))])
    pre = ColumnTransformer([('num', num_pipe, NUMERIC), ('cat', cat_pipe, CATEGORICAL)])
    pipe = Pipeline([('prep', pre), ('model', {ctor})])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=42)
    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)

    print("=== Metrics (held-out test split) ===")
{eval_block}

    print("\\n=== Plots ===")
{plot_block}

    model = pipe.named_steps['model']
    if hasattr(model, 'feature_importances_'):
        names = pipe.named_steps['prep'].get_feature_names_out()
        imp = sorted(zip(names, model.feature_importances_), key=lambda p: p[1], reverse=True)[:15]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh([n for n, _ in imp][::-1], [v for _, v in imp][::-1])
        ax.set_title({fi_title})
        fig.tight_layout(); fig.savefig('feature_importance.png', dpi=150); plt.close(fig)
        print('Saved feature_importance.png')


if __name__ == "__main__":
    main()
'''
