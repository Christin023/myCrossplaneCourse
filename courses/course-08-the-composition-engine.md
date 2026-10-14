# Course 8 — The Composition Engine

> **Goal:** Zoom out from one Managed Resource to a whole `App` and trace it
> through the **composition engine** — the loop inside the Crossplane core pod
> that turns one composite resource into many. You'll learn the gRPC function
> protocol, how **desired state accumulates** across a pipeline, and the strict
> rules about what a function may and may not change. This is the Crossplane
> mirror of `myk8scourses` Course 8, "Life of a `kubectl apply`."

**You need:** the cluster from Courses 3–4 with the `App` XRD, the Composition,
and both functions (`function-patch-and-transform`, `function-auto-ready`)
installed, plus `kubectl` and the `crossplane` CLI.

**Time:** ~45 min.

---

## 1. Recap the pain

Course 4 showed you *that* functions compute composed resources — you wrote
patches, transforms, and watched a ConfigMap + Deployment + Service appear from a
single `App`. But you took the engine on faith. *How* does Crossplane call those
functions? In what order? What stops two functions from clobbering each other,
and why does the XR only go `Ready` when its children do?

That faith is the last bit of magic in Track B. Today we open the composition
engine the same way Course 7 opened the provider loop.

---

## 2. The flow: one App, start to finish

The composition engine is a reconcile loop living in the **crossplane core pod**
(not in any provider). It watches composite resources (XRs) — your `App` — and
runs this sequence on every tick:

```
1. OBSERVE ONCE
   Read the App XR and ALL resources it currently composes
   (the ConfigMap, Deployment, Service from last time).

2. BUILD a RunFunctionRequest
   { observed:  { composite: App, resources: {configmap, deployment, service} },
     desired:   { } (starts empty),
     input:     the function's `input:` block from the Composition,
     context:   pipeline context (shared scratch space) }

3. CALL each pipeline function IN ORDER over mTLS gRPC
   for step in composition.spec.pipeline:
       response = step.function.RunFunction(request)
       request.desired = response.desired   # <-- accumulates!
       request.context = response.context

4. APPLY
   After the LAST function, the engine takes the final desired state and
   writes it to the API server with server-side apply.
```

For our `App`, the Composition's pipeline has two steps (open
`manifests/course-04/composition-parameterized.yaml` and read the `pipeline:`
block):

1. `render-resources` → **function-patch-and-transform**: builds the ConfigMap,
   Deployment and Service from `base:` templates and applies the `patches:`.
2. `ready` → **function-auto-ready**: inspects those composed resources and marks
   the `App` Ready when they're all Ready.

> 🧠 **The engine observes once, then only talks to functions.** Functions never
> touch the API server. They receive observed + desired state as data and return
> new desired state as data. All real I/O — the single observe at the top, the
> server-side apply at the bottom — belongs to the engine. That's what makes
> functions testable and `crossplane render` possible offline.

### Desired state accumulates

This is the rule that trips everyone up:

> ⚠️ **Each function must carry forward the desired state it received.** The
> engine passes the *accumulated* desired state into every function and takes the
> *returned* desired state as the new truth. If a function drops a resource that
> an earlier function added, that resource disappears from desired state — and
> the engine will delete it on apply. Functions **add to** a shared desired
> state; they don't each produce an isolated answer.

So function-patch-and-transform adds three resources to `desired`; function-
auto-ready receives those three, leaves them intact, and only sets the XR's
readiness. If auto-ready had returned an empty desired state, the engine would
delete your ConfigMap, Deployment, and Service on the next apply.

### What a function may and may not change

| Target | Function may change it? |
|--------|-------------------------|
| XR **status** | ✅ yes (e.g. write `status.url`, `status.ready`) |
| Composed resource **metadata / spec** | ✅ yes (that's the whole job) |
| XR **spec** | ❌ no — that's the user's intent, read-only to functions |
| Composed resource **status** | ❌ no — that's observed reality, owned by the real controllers |

`function-auto-ready` lives entirely in the allowed column: it *reads* composed
resource status (observed reality) and *writes* XR status readiness.

---

## 3. Lab: watch the engine work

Make sure an `App` exists (from Course 3/4):

```bash
kubectl apply -f manifests/course-03/app.yaml
```

### Trace the whole tree

```bash
crossplane beta trace app hello-snippy -n default
```

You'll see the `App` XR at the root and the composed ConfigMap, Deployment and
Service hanging beneath it, each with its `SYNCED` / `READY` columns — the engine
observes exactly this tree in step 1 of the flow.

### Compositions are revisioned

Every time you edit a Composition, Crossplane snapshots it as a
**CompositionRevision**:

```bash
kubectl get compositionrevision
kubectl get compositionrevision \
  -l crossplane.io/composition-name=app.platform.snippy.io
```

> 🧠 **Why revisions?** An in-flight XR is pinned to the revision it started
> reconciling against, so editing a Composition can't yank the rug out from under
> hundreds of live `App`s mid-reconcile. New and updated XRs roll forward to the
> newest revision; the old revision sticks around for stability and rollback —
> the same safety pattern as Deployment ReplicaSets (Course 9).

### Read the pipeline's own events

```bash
kubectl describe app hello-snippy -n default | sed -n '/Events:/,$p'
```

The engine emits events as it runs the pipeline — composed resources created,
functions invoked, readiness changes. This is your first stop when a composition
misbehaves.

### Re-run `crossplane render` and read the annotations

`crossplane render` runs the *exact same* pipeline the engine runs, but offline
and printed to stdout — the ideal way to see the engine's output without
touching the cluster:

```bash
crossplane render \
  manifests/course-03/app.yaml \
  manifests/course-04/composition-parameterized.yaml \
  manifests/course-03/functions.yaml
```

In the output, look at the composed resources' metadata:

- **`crossplane.io/composition-resource-name`** — the annotation that ties each
  rendered object back to its `name:` entry in the Composition (`configmap`,
  `deployment`, `service`). The engine uses it to match observed resources to
  desired ones across reconciles, so it updates the right object instead of
  creating duplicates.
- **`ownerReferences`** — each composed resource is owned by the `App` XR, so
  deleting the `App` garbage-collects all three children automatically.

### Required resources and context (the extras)

- **Required resources** — a function can ask the engine to fetch *existing*
  cluster resources it needs to read (e.g. a shared config). The engine fetches
  them and re-runs the pipeline, up to **5 iterations**, until the set of
  requested resources is stable. Functions still never read the API server
  themselves; they *ask the engine* to.
- **Pipeline context** — a shared scratch space threaded through every function
  (`request.context` → `response.context`), so an early function can leave notes
  a later one reads, without inventing a composed resource to carry them.

---

## 4. Peek under the hood

- **Functions are gRPC servers.** Each `Function` package runs as a long-lived
  pod exposing a single RPC: `RunFunction(RunFunctionRequest) ->
  RunFunctionResponse`. The engine dials it over **mTLS** — both sides present
  certificates — so the function pipeline is authenticated and encrypted even
  within the cluster.
- **Functions are pure(ish).** Their contract is
  `(observed, desired, input, context) -> (desired, context)`. No clocks, no
  network to the API server, no hidden state. That purity is why `crossplane
  render` can reproduce the engine's exact output on your laptop, and why
  functions are unit-testable (you'll write one in Course 11).
- **The engine owns all side effects.** One observe at the top, one server-side
  apply at the bottom. Server-side apply means the engine declares field
  ownership, so it can share objects with other controllers without endless
  update fights.
- **v1 vs v2.** In Crossplane v1, native patch-and-transform was built into the
  engine and functions were optional. In **v2, functions are mandatory** — every
  Composition is `mode: Pipeline` and *all* resource rendering happens in
  functions, even classic patch-and-transform (now shipped as
  `function-patch-and-transform`). The engine itself computes nothing; it only
  orchestrates functions.

---

## 5. Break it on purpose

Drop the readiness step and watch the `App` never report Ready.

```bash
# Edit the live Composition and delete the final `ready` pipeline step
# (the function-auto-ready step):
kubectl edit composition app.platform.snippy.io
#   remove:
#     - step: ready
#       functionRef:
#         name: function-auto-ready
```

Now nothing in the pipeline sets XR readiness from composed readiness:

```bash
kubectl get app hello-snippy -n default
#   READY stays empty/False even though the Deployment and Service are healthy
crossplane beta trace app hello-snippy -n default
#   children are READY=True, but the App root is not
```

The composed resources are perfectly healthy — the engine just has no function
telling it to roll their readiness up to the XR. Restore the step:

```bash
kubectl apply -f manifests/course-04/composition-parameterized.yaml
sleep 10
kubectl get app hello-snippy -n default        # READY=True again
```

> 🧠 **Readiness is a decision, not an observation.** The engine won't guess when
> your `App` is "ready" — a function must assert it. `function-auto-ready`
> encodes the simplest useful policy ("ready when all children are ready"), but
> you could write a function that waits for an extra health check or ignores an
> optional resource. The engine stays policy-free.

---

## 6. Scorecard update

| # | Course 0 pain | Status after Course 8 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ XR spec drives the whole pipeline deterministically |
| 2 | **No self-service API** | ✅ the engine turns one `App` into a full environment |
| 3 | Two worlds (cluster vs cloud) | ✅ functions can compose MRs and native objects alike |
| 4 | No continuous reconciliation of external state | ✅ Course 7 (the MR loop) + this loop around it |
| 5 | Platform not installable | ⏭️ Course 10 (Configuration packages) |

---

## 7. Takeaway

The composition engine is a reconcile loop in the core pod: it observes the XR
and its children once, builds a `RunFunctionRequest`, calls each pipeline
function over mTLS gRPC in order, and server-side-applies the final desired
state. Desired state **accumulates** — every function must carry forward what
earlier functions added or the engine deletes it. Functions may change XR status
and composed spec/metadata, but never XR spec or composed status. Compositions
are revisioned so live XRs stay stable across edits, and `function-auto-ready`
is what rolls child readiness up to the `App`. It's `kubectl apply`'s life story
from `myk8scourses` Course 8, retold one level up — the engine orchestrates
functions the way the API server orchestrates admission and controllers.

**Next:** [Course 9 — Packages, xpkg & OCI](./course-09-packages-xpkg-and-oci.md),
where we discover that providers, functions, *and* configurations are all just
OCI images — and open the box.
