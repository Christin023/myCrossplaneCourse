# Course 11 — Write a Composition Function

> **Goal:** Retire patch-and-transform and compose your SnippyStack `App` with
> your **own code** — a Python composition function. You'll run it locally with
> an edit-run-see loop, render against it with no cluster, then package and
> install it as a real Function. By the end you'll have written the exact
> `observed → desired` transform the composition engine calls — the Crossplane
> cousin of the Kopf operator you wrote in `myk8scourses` Course 12.

**You need:** the cluster with Crossplane v2, the `crossplane` CLI, Python 3.12+,
Docker, and the repo's [`../functions/snippy-app/`](../functions/snippy-app/)
directory.

**Time:** ~55 min.

---

## 1. Recap the pain

In Course 4 you got good at `function-patch-and-transform`: `FromCompositeFieldPath`,
string `Format`, `map` transforms, `CombineToComposite`. It's powerful — until
it isn't. The moment you want *logic* — "if `replicas` is odd, add a
pod-anti-affinity rule," "reject images not from our registry," "compute a name
only when a field is set" — you're writing programs in YAML. Patch chains grow
into puzzles that no one can read and nothing can unit-test.

That's the wall. Patch-and-transform is declarative data; real platform logic
wants to be *code*. So let's write the code.

---

## 2. The concept: a function is just a gRPC server

Here's the whole secret of Crossplane v2 composition, which you glimpsed in
Course 8:

> A composition function is a **gRPC server**. The engine sends it a
> `RunFunctionRequest` containing the **observed** state (your `App` XR and any
> existing composed resources) plus the **desired** state accumulated by earlier
> pipeline steps. The function returns a `RunFunctionResponse` with an updated
> **desired** state. That's the entire contract.

`function-patch-and-transform` is *itself* just one such server that happens to
interpret patch YAML. Nothing stops you from writing a server that runs arbitrary
code instead. Same pipeline slot, same request/response, but now `if`/`for`/tests
live in your platform.

> 🧠 **This is the same `observe → compute desired state` shape as a Kubernetes
> controller.** In `myk8scourses` Course 12 your Kopf operator observed a CRD and
> created child objects. A composition function observes an XR and *returns*
> child objects for Crossplane to apply. The engine owns the apply + reconcile;
> you own only the pure transform. It's a controller with the plumbing removed.

### The quick on-ramp: inline Python, no packaging

Before building anything, know the fastest path exists: `function-python` lets
you drop a script straight into a Composition's pipeline input as a concept
sketch:

```yaml
# Conceptual — an inline function step. Great for a one-off; doesn't scale to a
# real platform you want to version and test.
pipeline:
  - step: compose
    functionRef:
      name: function-python
    input:
      apiVersion: python.fn.crossplane.io/v1beta1
      kind: Script
      script: |
        def compose(req, rsp):
            # same observed->desired idea, inline
            ...
```

Fine for experiments. But your platform deserves real code in a real repo with
tests — so we package our own function instead.

---

## 3. Read the function you'll ship

Open [`../functions/snippy-app/function.py`](../functions/snippy-app/function.py).
The heart is `FunctionRunner.RunFunction`:

```python
from crossplane.function import logging, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1


class FunctionRunner(grpcv1.FunctionRunnerService):
    async def RunFunction(self, req: fnv1.RunFunctionRequest, _) -> fnv1.RunFunctionResponse:
        rsp = response.to(req)           # carry forward desired state (see §5!)

        xr = req.observed.composite.resource     # the App the developer created
        name = xr["metadata"]["name"]
        spec = xr.get("spec", {})
        image = spec.get("image", "snippy:0.1")
        replicas = int(spec.get("replicas", 1))
        greeting = spec.get("greeting", "Hello from SnippyStack")
        ...
```

It then calls `resource.update(...)` three times to emit a **ConfigMap**
(`{name}-config`, with `data.greeting`), a **Deployment** (with the `snippy`
container, `APP_GREETING` env, `replicas`), and a **Service** (port 80 →
targetPort 8080) — the identical shape the Course 4 Composition produced, but
expressed as plain Python dicts. Finally it writes the status URL back onto the
XR:

```python
ns = xr["metadata"].get("namespace", "default")
resource.update(
    rsp.desired.composite.resource,
    {"status": {"url": f"http://{name}.{ns}.svc.cluster.local"}},
)
response.normal(rsp, f"composed Snippy environment for {name}")
return rsp
```

Two SDK calls do all the heavy lifting:

- **`response.to(req)`** — seeds the response by **copying the incoming desired
  state** so you don't accidentally drop what earlier steps built.
- **`resource.update(target, body)`** — merges a dict into a desired resource
  slot keyed by a name you choose (`configmap`, `deployment`, `service`).

[`main.py`](../functions/snippy-app/main.py) is tiny — it just calls
`runtime.serve(FunctionRunner())`, and the SDK's runtime helper wires up the
gRPC server, TLS, logging, and flag parsing. [`requirements.txt`](../functions/snippy-app/requirements.txt)
pins `crossplane-function-sdk-python>=0.9.0` and `grpcio`.

> ⚠️ **SDK API names drift between versions.** `response.to`, `resource.update`,
> and the `proto.v1` import path are current for the `>=0.9.0` SDK pinned here.
> Older/newer SDKs rename helpers and bump the proto version (`v1beta1` → `v1`).
> Always check the SDK version in `requirements.txt` against the examples you
> copy, or you'll chase phantom import errors.

---

## 4. Lab: run it locally, render against it

### 4a. Start the function on your laptop

```bash
cd functions/snippy-app
pip install -r requirements.txt
python main.py --insecure --debug
```

`--insecure` disables mTLS so the local CLI can reach it; `--debug` logs each
request. It's now listening on `localhost:9443`. Leave it running.

### 4b. Render — the edit-run-see loop, no cluster needed

In **another terminal**, ask the CLI to run your Composition locally and print
what it *would* apply:

```bash
cd functions/snippy-app
crossplane render example/xr.yaml example/composition.yaml example/functions.yaml
```

You'll see the composed ConfigMap, Deployment, and Service printed as YAML, with
`replicas: 3` and `greeting: "Hello from my own function"` from
[`example/xr.yaml`](../functions/snippy-app/example/xr.yaml) — produced by *your*
Python, with no cluster involved.

The trick is in [`example/functions.yaml`](../functions/snippy-app/example/functions.yaml):

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-snippy-app
  annotations:
    render.crossplane.io/runtime: Development     # <-- connect to local process
spec:
  package: function-snippy-app                     # ignored for Development
```

The `render.crossplane.io/runtime: Development` annotation tells `crossplane
render` **not** to pull or run an image — instead it dials the function you're
running at `localhost:9443`. Edit `function.py`, restart `python main.py`,
re-run `render`, see the diff. That loop — code, render, inspect — is why writing
functions feels fast.

[`example/composition.yaml`](../functions/snippy-app/example/composition.yaml) is
a two-step pipeline: your `compose-snippy` step, then `function-auto-ready`.
Notice there is **no patch-and-transform input** — all the logic moved into code.

### 4c. Build and package the function

Unlike a Configuration (Course 10, no runtime), a Function ships a **runtime
image**. Build it, then embed it in the `.xpkg`:

```bash
cd functions/snippy-app
docker build -t snippy-app-fn .
crossplane xpkg build -f package --embed-runtime-image=snippy-app-fn
```

`-f package` points at [`package/crossplane.yaml`](../functions/snippy-app/package/crossplane.yaml)
(the `meta.pkg.crossplane.io/v1beta1` Function metadata, named
`function-snippy-app`), and `--embed-runtime-image` wraps your Docker image into
the package. Push it like any other package:

```bash
crossplane xpkg push xpkg.example.com/platform/function-snippy-app:v0.1.0
```

### 4d. Install it and swap the pipeline

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-snippy-app
spec:
  package: xpkg.example.com/platform/function-snippy-app:v0.1.0
EOF

kubectl get functions.pkg.crossplane.io    # wait for HEALTHY=True
```

Now update the SnippyStack Composition's pipeline to call your function instead
of patch-and-transform — exactly the shape of
`functions/snippy-app/example/composition.yaml`:

```yaml
spec:
  mode: Pipeline
  pipeline:
    - step: compose-snippy
      functionRef:
        name: function-snippy-app
    - step: ready
      functionRef:
        name: function-auto-ready
```

Apply an `App` and confirm the running Snippy is identical — same ConfigMap,
Deployment, Service — but now produced by your code:

```bash
kubectl apply -f manifests/course-03/app.yaml
kubectl get app hello-snippy -n default -o jsonpath='{.status.url}{"\n"}'
```

---

## 5. Peek under the hood: the SDK and the copy-forward rule

Two things the SDK quietly handles, straight from Course 8:

1. **gRPC + mTLS.** In-cluster, Crossplane talks to your function pod over
   gRPC on 9443 with mutual TLS. The SDK's `runtime.serve` sets this up; locally
   `--insecure` skips it. You never write transport code.

2. **The copy-forward rule.** The engine treats the function's returned desired
   state as *authoritative*. **Anything you don't carry forward, Crossplane
   deletes.** That's why `function.py`'s very first line is `rsp = response.to(req)`
   — it copies the inbound desired state (what earlier steps produced) into your
   response. Forget it, and a later re-render silently drops the resources an
   earlier step added.

> 🧠 **"Return the whole desired world, every time."** A function isn't told
> "add this resource" — it's asked "given everything observed, what should the
> complete desired set be?" Level-triggered, not edge-triggered — the same
> principle as the reconcile loop in `myk8scourses` Course 2. The engine then
> diffs your desired set against reality and acts.

---

## 6. Break it on purpose: put a rule in your platform

Add a guardrail that patch-and-transform could never express cleanly. In
`function.py`, right after reading `replicas`:

```python
        replicas = int(spec.get("replicas", 1))
        if replicas > 10:
            response.fatal(rsp, f"replicas={replicas} exceeds the SnippyStack limit of 10")
            return rsp
```

Restart the local server, bump `example/xr.yaml` to `replicas: 25`, and render:

```bash
# terminal 1
python main.py --insecure --debug
# terminal 2
crossplane render example/xr.yaml example/composition.yaml example/functions.yaml
```

Render now reports the fatal result and emits no resources — your policy is
enforced *at composition time*, in testable code, before anything hits the
cluster. Dial it back to `replicas: 3` and it composes again. That `if` statement
is the thing YAML patches can't give you.

---

## 7. Scorecard update

| # | Course 0 pain | Status after Course 11 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ XR → code → composed resources, all reconciled |
| 2 | No self-service API | ✅ the `App` API, now backed by real logic |
| 3 | Two worlds (cluster vs cloud) | ✅ one engine |
| 4 | No continuous reconciliation of external state | ✅ the MR loop (Course 7) |
| 5 | Platform not installable | ✅ Course 10; your function packages too |

No pain flips here — this course deepens the self-service API (#2) by letting it
carry arbitrary logic, and makes your platform genuinely programmable.

---

## 8. Takeaway

You implemented a composition function: a gRPC server whose `RunFunction` reads
the observed `App` and returns the desired ConfigMap + Deployment + Service, with
the status URL written back. You ran it locally and rendered with no cluster
(`render.crossplane.io/runtime: Development`), packaged it with an embedded
runtime image, installed it, and swapped it into the pipeline — then added a real
conditional patches could never express. This is the exact `observed → desired`
transform the composition engine calls on every reconcile: a Kubernetes
controller with the plumbing removed and the logic left to you.

### Cleanup

```bash
# Stop the local python process (Ctrl-C), then:
kubectl delete app --all -n default
# Optional: revert the Composition to function-patch-and-transform, or
# uninstall your function:
kubectl delete function.pkg.crossplane.io function-snippy-app --ignore-not-found
cd functions/snippy-app && rm -f *.xpkg
```

**Next:** [Course 12 — Write Your Own Provider](./course-12-write-your-own-provider.md),
where you leave composition behind and build the *other* kind of controller — a
provider — implementing the `ExternalClient` contract from Course 7 against a toy
external API.
