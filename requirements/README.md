# Dependency layers

The dependency files are intentionally layered by execution environment:

| File | Installed by | Contents |
| --- | --- | --- |
| `base.txt` | API and worker | LLM providers, CPU-only PyTorch, embeddings, and retrieval |
| `api.txt` | Production API and worker images | `base.txt` plus FastAPI, persistence, auth, migrations, and task runtime |
| `dev.txt` | CI and backend contributors | `api.txt` plus pytest, coverage, Ruff, and test clients |
| `ui.txt` | Historical Streamlit image only | Streamlit and its HTTP client |
| `training.txt` | Dedicated opt-in training environment | LoRA/fine-tuning extras; never installed into API/worker images |

The repository-root `requirements.txt` is a convenience alias for
`requirements/dev.txt`. Production Dockerfiles must install `api.txt`
directly.

PyTorch uses the official CPU wheel index and an explicit `+cpu` version on
Linux and Windows. This prevents pip from resolving CUDA/NVIDIA runtime
packages into CPU inference images. macOS uses the CPU wheel published on
PyPI, which does not carry the `+cpu` suffix.

Install only the layer needed for the task:

```bash
# Backend development and tests
python -m pip install -r requirements/dev.txt

# Production-compatible API/worker environment
python -m pip install -r requirements/api.txt

# Optional LoRA environment, after installing the desired runtime layer
python -m pip install -r requirements/training.txt
```
