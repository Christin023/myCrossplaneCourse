# Builds the function's RUNTIME image — the gRPC server Crossplane runs in a pod.
# `crossplane xpkg build --embed-runtime-image` wraps this into the .xpkg package
# alongside package/crossplane.yaml.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY function.py main.py ./

# Crossplane talks to the function over gRPC on 9443 (mTLS in-cluster).
EXPOSE 9443
ENTRYPOINT ["python", "main.py"]
