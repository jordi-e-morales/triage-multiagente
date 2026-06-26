"""
ML Models for Mortgage Underwriting
- XGBoost: Credit risk / probability of default
- GNN (2-layer GCN): Fraud / suspicious network detection
Models are trained on synthetic mortgage data at startup if not cached.
"""
from __future__ import annotations
import os
import pickle
import numpy as np
import warnings
warnings.filterwarnings("ignore")

MODEL_DIR = os.path.join(os.path.dirname(__file__), "cached_models")
XGB_PATH = os.path.join(MODEL_DIR, "xgboost_credit.pkl")
GNN_PATH = os.path.join(MODEL_DIR, "gnn_fraud.pkl")

# ─── Data generation ──────────────────────────────────────────────────────────

def _generate_mortgage_data(n: int = 50_000, seed: int = 42):
    rng = np.random.default_rng(seed)
    credit_score = rng.integers(500, 850, n).astype(float)
    annual_income = rng.lognormal(11.0, 0.5, n)
    loan_amount = annual_income * rng.uniform(2.0, 5.5, n)
    property_value = loan_amount / rng.uniform(0.65, 0.97, n)
    ltv = loan_amount / property_value
    monthly_debt = annual_income / 12 * rng.uniform(0.05, 0.45, n)
    monthly_income = annual_income / 12
    dti = monthly_debt / monthly_income
    employment_years = rng.exponential(7, n).clip(0, 40)
    is_self_employed = (rng.random(n) < 0.18).astype(float)
    num_late_payments = rng.integers(0, 8, n).astype(float)
    geographic_risk = rng.uniform(0, 1, n)

    # Default probability formula (realistic)
    log_odds = (
        -4.5
        + (-0.008) * credit_score
        + (-0.00001) * annual_income
        + 3.5 * ltv
        + 4.0 * dti
        + (-0.05) * employment_years
        + 0.6 * is_self_employed
        + 0.4 * num_late_payments
        + 1.2 * geographic_risk
    )
    prob_default = 1 / (1 + np.exp(-log_odds))
    default = (rng.random(n) < prob_default).astype(int)

    X = np.column_stack([
        credit_score, annual_income, loan_amount, property_value,
        ltv, dti, employment_years, is_self_employed,
        num_late_payments, geographic_risk,
    ])
    return X, default


FEATURE_NAMES = [
    "credit_score", "annual_income", "loan_amount", "property_value",
    "ltv", "dti", "employment_years", "is_self_employed",
    "num_late_payments", "geographic_risk",
]


# ─── XGBoost ──────────────────────────────────────────────────────────────────

def _train_xgboost():
    from xgboost import XGBClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score

    X, y = _generate_mortgage_data(50_000)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    return model, auc


# ─── GNN ──────────────────────────────────────────────────────────────────────

def _train_gnn():
    """
    2-layer Graph Convolutional Network for fraud ring detection.
    Nodes = loan applications; edges = shared attributes (same employer,
    same address, similar income). Fraud nodes are those in suspicious clusters.
    """
    import torch
    import torch.nn.functional as F
    from torch_geometric.nn import GCNConv
    from torch_geometric.data import Data
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(42)
    n_nodes = 2000
    X, y = _generate_mortgage_data(n_nodes, seed=99)

    # Build edges: connect nodes that share similar credit score + income buckets
    credit_bucket = (X[:, 0] // 50).astype(int)
    income_bucket = (np.log(X[:, 1] + 1) // 0.5).astype(int)
    edge_src, edge_dst = [], []
    bucket_map: dict = {}
    for i in range(n_nodes):
        key = (credit_bucket[i], income_bucket[i])
        if key not in bucket_map:
            bucket_map[key] = []
        for j in bucket_map[key][:5]:  # max 5 edges per node
            edge_src.append(i); edge_dst.append(j)
            edge_src.append(j); edge_dst.append(i)
        bucket_map[key].append(i)

    edge_index = torch.tensor([edge_src, edge_dst], dtype=torch.long)
    node_features = torch.tensor(X, dtype=torch.float32)
    labels = torch.tensor(y, dtype=torch.long)

    # Fraud label: default AND in a suspicious cluster (geographic_risk > 0.7)
    fraud_label = torch.tensor(
        ((y == 1) & (X[:, 9] > 0.7)).astype(int), dtype=torch.long
    )

    data = Data(x=node_features, edge_index=edge_index, y=fraud_label)

    class GCN(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = GCNConv(10, 32)
            self.conv2 = GCNConv(32, 16)
            self.lin = torch.nn.Linear(16, 2)

        def forward(self, x, edge_index):
            x = F.relu(self.conv1(x, edge_index))
            x = F.dropout(x, p=0.3, training=self.training)
            x = F.relu(self.conv2(x, edge_index))
            return self.lin(x)

    model = GCN()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    # Train / test split
    train_mask = torch.zeros(n_nodes, dtype=torch.bool)
    train_mask[:1600] = True
    test_mask = ~train_mask

    for epoch in range(100):
        model.train()
        optimizer.zero_grad()
        out = model(data.x, data.edge_index)
        loss = F.cross_entropy(out[train_mask], data.y[train_mask])
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        out = model(data.x, data.edge_index)
        probs = F.softmax(out, dim=1)[:, 1].numpy()

    auc = roc_auc_score(data.y[test_mask].numpy(), probs[test_mask.numpy()])

    # Save model weights as state dict (pickle-safe)
    return {"state_dict": model.state_dict(), "auc": auc, "n_features": 10}


# ─── Load / train ─────────────────────────────────────────────────────────────

_xgb_model = None
_gnn_data = None
_xgb_auc = 0.0
_gnn_auc = 0.0


def ensure_models_loaded():
    global _xgb_model, _gnn_data, _xgb_auc, _gnn_auc
    os.makedirs(MODEL_DIR, exist_ok=True)

    if _xgb_model is None:
        if os.path.exists(XGB_PATH):
            with open(XGB_PATH, "rb") as f:
                data = pickle.load(f)
                _xgb_model = data["model"]
                _xgb_auc = data["auc"]
        else:
            _xgb_model, _xgb_auc = _train_xgboost()
            with open(XGB_PATH, "wb") as f:
                pickle.dump({"model": _xgb_model, "auc": _xgb_auc}, f)

    if _gnn_data is None:
        if os.path.exists(GNN_PATH):
            with open(GNN_PATH, "rb") as f:
                _gnn_data = pickle.load(f)
                _gnn_auc = _gnn_data["auc"]
        else:
            _gnn_data = _train_gnn()
            _gnn_auc = _gnn_data["auc"]
            with open(GNN_PATH, "wb") as f:
                pickle.dump(_gnn_data, f)


def get_model_status() -> dict:
    return {
        "xgboost_loaded": _xgb_model is not None,
        "gnn_loaded": _gnn_data is not None,
        "xgb_auc": round(_xgb_auc, 3),
        "gnn_auc": round(_gnn_auc, 3),
    }


# ─── Inference ────────────────────────────────────────────────────────────────

def predict_credit_risk(
    credit_score: float,
    annual_income: float,
    loan_amount: float,
    property_value: float,
    employment_years: float,
    is_self_employed: bool,
    num_late_payments: int = 0,
    geographic_risk: float = 0.3,
) -> dict:
    """Returns probability of default and feature importances."""
    ensure_models_loaded()
    ltv = loan_amount / max(property_value, 1)
    monthly_income = annual_income / 12
    # Estimate monthly debt from DTI context
    monthly_debt = monthly_income * 0.25  # placeholder; refined in pipeline
    dti = monthly_debt / max(monthly_income, 1)

    X = np.array([[
        credit_score, annual_income, loan_amount, property_value,
        ltv, dti, employment_years, float(is_self_employed),
        float(num_late_payments), geographic_risk,
    ]])

    prob_default = float(_xgb_model.predict_proba(X)[0, 1])
    importances = _xgb_model.feature_importances_
    feature_impact = {
        name: round(float(imp), 4)
        for name, imp in zip(FEATURE_NAMES, importances)
    }

    return {
        "probability_of_default": round(prob_default, 4),
        "credit_risk_score": round((1 - prob_default) * 100, 1),
        "feature_importances": feature_impact,
        "model": "XGBoost",
        "auc": round(_xgb_auc, 3),
    }


def predict_fraud_risk(
    credit_score: float,
    annual_income: float,
    loan_amount: float,
    property_value: float,
    employment_years: float,
    is_self_employed: bool,
    geographic_risk: float = 0.3,
) -> dict:
    """Returns GNN-based fraud probability for a single applicant node."""
    import torch
    import torch.nn.functional as F
    from torch_geometric.nn import GCNConv

    ensure_models_loaded()

    class GCN(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = GCNConv(10, 32)
            self.conv2 = GCNConv(32, 16)
            self.lin = torch.nn.Linear(16, 2)

        def forward(self, x, edge_index):
            x = F.relu(self.conv1(x, edge_index))
            x = F.relu(self.conv2(x, edge_index))
            return self.lin(x)

    model = GCN()
    model.load_state_dict(_gnn_data["state_dict"])
    model.eval()

    ltv = loan_amount / max(property_value, 1)
    dti = 0.25  # approximate
    node_features = torch.tensor([[
        credit_score, annual_income, loan_amount, property_value,
        ltv, dti, employment_years, float(is_self_employed), 0.0, geographic_risk,
    ]], dtype=torch.float32)
    # Self-loop only for single-node inference
    edge_index = torch.tensor([[0], [0]], dtype=torch.long)

    with torch.no_grad():
        out = model(node_features, edge_index)
        probs = F.softmax(out, dim=1)[0]
        fraud_prob = float(probs[1])

    return {
        "fraud_probability": round(fraud_prob, 4),
        "fraud_risk_score": round(fraud_prob * 100, 1),
        "model": "GNN (2-layer GCN)",
        "auc": round(_gnn_auc, 3),
    }
