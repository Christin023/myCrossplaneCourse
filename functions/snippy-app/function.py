"""A composition function for SnippyStack, written in Python.

This replaces function-patch-and-transform with real code. It reads an `App`
composite resource (XR) and emits the three composed resources that make up a
Snippy environment: a ConfigMap, a Deployment, and a Service.

A composition function is just a gRPC server. Crossplane calls RunFunction with
the OBSERVED state (the XR and any existing composed resources) and the DESIRED
state accumulated so far; the function returns an updated DESIRED state. The
crossplane-function SDK sets up gRPC, TLS, and (de)serialization for you — you
only write the compose logic in RunFunction below.

Run locally for development:
    pip install -r requirements.txt
    python main.py --insecure --debug
Then in another terminal, render against it:
    crossplane render example/xr.yaml example/composition.yaml example/functions.yaml
"""

import grpc
from crossplane.function import logging, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1


class FunctionRunner(grpcv1.FunctionRunnerService):
    """Implements the Crossplane composition function contract."""

    def __init__(self):
        self.log = logging.get_logger()

    async def RunFunction(self, req: fnv1.RunFunctionRequest, _) -> fnv1.RunFunctionResponse:
        # response.to() copies the incoming desired state into our response.
        # A function MUST carry forward desired state it wants to keep — anything
        # it drops, Crossplane deletes. The SDK handles the copy for us.
        rsp = response.to(req)

        # Observed state of the App XR the developer created.
        xr = req.observed.composite.resource
        name = xr["metadata"]["name"]
        spec = xr.get("spec", {})
        image = spec.get("image", "snippy:0.1")
        replicas = int(spec.get("replicas", 1))
        greeting = spec.get("greeting", "Hello from SnippyStack")

        # --- ConfigMap -----------------------------------------------------
        resource.update(
            rsp.desired.resources["configmap"].resource,
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": f"{name}-config"},
                "data": {"greeting": greeting},
            },
        )

        # --- Deployment ----------------------------------------------------
        resource.update(
            rsp.desired.resources["deployment"].resource,
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name},
                "spec": {
                    "replicas": replicas,
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "containers": [
                                {
                                    "name": "snippy",
                                    "image": image,
                                    "ports": [{"containerPort": 8080}],
                                    "env": [{"name": "APP_GREETING", "value": greeting}],
                                }
                            ]
                        },
                    },
                },
            },
        )

        # --- Service -------------------------------------------------------
        resource.update(
            rsp.desired.resources["service"].resource,
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name},
                "spec": {
                    "selector": {"app": name},
                    "ports": [{"port": 80, "targetPort": 8080}],
                },
            },
        )

        # Report the Service URL back on the XR's status.
        ns = xr["metadata"].get("namespace", "default")
        resource.update(
            rsp.desired.composite.resource,
            {"status": {"url": f"http://{name}.{ns}.svc.cluster.local"}},
        )

        response.normal(rsp, f"composed Snippy environment for {name}")
        self.log.info("composed", app=name, replicas=replicas, image=image)
        return rsp
