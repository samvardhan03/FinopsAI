# FinOps AI 🤖☁️

<p align="center">
  <strong>Enterprise-Grade Multi-Cloud Cost Optimization Platform</strong>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-quickstart">Quickstart</a> •
  <a href="#-providers">Providers</a> •
  <a href="#-ai-engine">AI Engine</a> •
  <a href="#-configuration">Configuration</a> •
  <a href="#-contributing">Contributing</a>
</p>

---

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Multi-Cloud](https://img.shields.io/badge/Multi--Cloud-Azure%20%7C%20AWS%20%7C%20GCP-orange)

> **Stop paying for cloud resources nobody uses.** FinOps AI scans your multi-cloud
> infrastructure, detects orphaned resources, estimates waste, and provides AI-powered
> recommendations — saving enterprises an average of **30% on cloud spend**.

## 🚀 Features

| Feature | Description |
|---------|-------------|
| **Multi-Cloud Scanning** | Azure, AWS, and GCP — one unified interface |
| **14+ Resource Types** | Snapshots, disks, VMs, IPs, NICs, LBs, RDS, App Services, and more |
| **AI/ML Engine** | Isolation Forest anomaly detection + Prophet cost forecasting |
| **Smart Recommendations** | Prioritized, actionable savings with effort/risk ratings |
| **Policy Engine** | YAML-driven governance with approval workflows |
| **Dependency Graph** | NetworkX-powered safe-deletion analysis |
| **Rich Reports** | HTML (dark theme), JSON, CSV, and Slack notifications |
| **Beautiful CLI** | Click + Rich with color-coded output and progress bars |

## ⚡ Quickstart

### Install

```bash
# Core package
pip install finops-ai

# With cloud providers
pip install finops-ai[azure]     # Azure only
pip install finops-ai[aws]       # AWS only
pip install finops-ai[gcp]       # GCP only
pip install finops-ai[all]       # All providers + ML

# Development
pip install finops-ai[dev]
```

### First Scan

```bash
# Generate a config file
finops-ai init

# Scan Azure (uses CLI auth by default)
finops-ai scan --provider azure

# Scan all providers
finops-ai scan --provider all

# Scan with JSON report
finops-ai scan --provider azure --output json --report my_report.json

# Check version and installed providers
finops-ai version
```

### Python API

```python
from finops_ai.core.auth_manager import AuthManager
from finops_ai.providers.azure.snapshot_manager import AzureSnapshotManager

# Authenticate
credential = AuthManager.get_azure_credential()

# Scan for orphaned snapshots
manager = AzureSnapshotManager(credential)
result = manager.scan()

print(f"Found {result.total_resources} orphaned snapshots")
print(f"Estimated savings: ${result.total_estimated_cost:.2f}/month")

for resource in result.resources:
    print(f"  {resource.name}: ${resource.estimated_monthly_cost:.2f}/mo ({resource.age_days} days old)")
```

## ☁️ Providers

### Azure (7 Resource Types)
- **Snapshots** — Orphaned managed snapshots (source disk deleted)
- **Disks** — Unattached managed disks (with SKU-aware pricing)
- **Network** — Unused public IPs, detached NICs, idle load balancers
- **VMs** — Zombie VMs (stopped/deallocated > N days)
- **Storage** — Idle blob containers (>90 days no modification)
- **App Service Plans** — Plans with zero web apps
- **Resource Groups** — Empty resource groups

### AWS (4 Resource Types)
- **EC2** — Stopped instances (zombie VMs) + unused security groups
- **EBS** — Unattached volumes + orphaned snapshots (source volume deleted)
- **Network** — Unassociated Elastic IPs + idle ALBs/NLBs
- **RDS** — Orphaned manual snapshots (source DB deleted)

### GCP (3 Resource Types)
- **Compute** — Orphaned snapshots + unattached disks + stopped VMs
- **Network** — Reserved (unused) static IPs (regional + global)
- **Storage** — Empty Cloud Storage buckets

## 🧠 AI Engine

```python
from finops_ai.ml.anomaly_detector import AnomalyDetector
from finops_ai.ml.cost_forecaster import CostForecaster
from finops_ai.ml.recommender import SmartRecommender

# Anomaly detection (Isolation Forest)
detector = AnomalyDetector(contamination=0.1)
anomalies = detector.detect(resources)

# Cost forecasting (Linear/Prophet)
forecaster = CostForecaster()
forecast = forecaster.forecast_from_snapshots(historical_data, forecast_days=30)

# Smart recommendations
recommender = SmartRecommender()
report = recommender.analyze(resources)
print(f"Total savings: ${report.total_annual_savings:,.2f}/year")
```

## ⚙️ Configuration

Generate a config file with `finops-ai init`, then customize:

```yaml
dry_run: true
log_level: INFO

providers:
  azure:
    enabled: true
    auth:
      method: cli  # cli | managed_identity | service_principal
    subscription_id: ""

  aws:
    enabled: true
    auth:
      method: profile
    regions: [us-east-1, us-west-2]

  gcp:
    enabled: true
    auth:
      method: adc
    project_id: my-project

policies:
  policies_dir: ./policies
  enforce: false

ml:
  enabled: true
  anomaly_detection: true
  cost_forecasting: true
```

## 🏗️ Architecture

```
src/finops_ai/
├── __init__.py              # Package root
├── cli.py                   # Click + Rich CLI
├── config.py                # Pydantic Settings configuration
├── core/
│   ├── auth_manager.py      # Multi-cloud authentication
│   ├── base_manager.py      # Abstract base + data models
│   ├── graph_analyzer.py    # Dependency graph (NetworkX)
│   └── policy_engine.py     # YAML governance policies
├── providers/
│   ├── azure/               # 7 Azure resource managers
│   ├── aws/                 # 4 AWS resource managers
│   └── gcp/                 # 3 GCP resource managers
├── ml/
│   ├── anomaly_detector.py  # Isolation Forest
│   ├── cost_forecaster.py   # Prophet / linear regression
│   └── recommender.py       # Smart recommendations
├── reporters/
│   ├── json_reporter.py     # JSON export
│   ├── csv_reporter.py      # CSV export
│   ├── html_reporter.py     # Standalone dark-theme HTML
│   └── slack_reporter.py    # Slack webhook (Block Kit)
└── utils/
    ├── logger.py             # Rich logging + JSON audit
    └── cost_calculator.py    # Cross-cloud pricing
```

## 🧪 Testing

```bash
# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=finops_ai --cov-report=html
```

## 📋 Migrating from TerraSnap-Govern

The original TerraSnap-Govern code has been preserved in `legacy/`. To migrate:

```bash
# Old way
python scripts/azure_snapshot_cleanup.py --subscription-id $SUB_ID

# New way
finops-ai scan --provider azure --resource-type snapshot -s $SUB_ID
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Install dev dependencies: `pip install -e ".[dev]"`
4. Make changes and add tests
5. Run linting: `ruff check src/`
6. Run tests: `pytest tests/ -v`
7. Submit a pull request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with ❤️ for FinOps practitioners everywhere
</p>
