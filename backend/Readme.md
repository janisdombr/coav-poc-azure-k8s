# `backend/` — Python K8s backend prototype (superseded)

This was the **first** COAV backend: a Python service reading Azure Event Hub with Pydantic
validation, deployed to a local Minikube cluster. It was replaced by the Java Spring Boot service
in [`coav-gui/backend/`](../coav-gui/backend/) once the technical spec's explicit requirement for
a **Java backend + JS/TS frontend** was found (TechSpec 3.1(5)). `main.py` is kept as evidence of
the migration, not as a live component.

The Minikube run commands for this prototype are preserved in
→ [docs/EXPERIMENT_HISTORY.md](../docs/EXPERIMENT_HISTORY.md#1-superseded--python-k8s-backend-prototype-backendmainpy)

← Back to [main README](../README.md)
