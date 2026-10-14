# Course 3 — Your First Composite API (XRD + Composition)

> **Goal:** Teach the control plane a brand-new noun — `App` — and compose an
> entire Snippy environment (ConfigMap + Deployment + Service) from **one**
> resource. You'll define your API's *schema* with an **XRD** and its
> *implementation* with a **Composition** that runs a pipeline of functions. By
> the end, `kubectl apply` of a single `App` makes a whole running app appear,
> and deleting it cleans everything up.

**You need:** the cluster from Course 2 with Crossplane running, the `snippy:0.1`
image loaded (see [`../snippy/README.md`](../snippy/README.md)), `kubectl`, and
the `crossplane` CLI.

**Time:** ~55 min.

---

## 1. Recap the pain

Course 2 gave you providers and **Managed Resources** — low-level, 1:1 handles on
external objects. Great for the platform team, but notice what a *developer* would
still have to do to run Snippy: author a ConfigMap MR, a Deployment, **and** a
Service, wire the labels and env together, and not typo any of it. That's Course
0's **Problem #2** (no safe self-service abstraction) staring right back at you.
Developers shouldn't assemble primitives. They should ask for *"an App."* Today
you build that noun.

---

## 2. The core idea: XRD = schema, Composition = implementation

Crossplane lets you define your **own** API types. Two objects do it:

- **CompositeResourceDefinition (XRD)** — the *schema* of your new API: its
  group, kind, versions, and the OpenAPI shape of `spec`/`status`. This is your
  platform's **public contract** — the only thing developers see.
- **Composition** — the *implementation*: given one composite resource (XR), what
  real resources should exist? In v2 a Composition is a **Pipeline of functions**.

```
XRD         ->  "An App has image, replicas, greeting."   (the contract)
Composition ->  "An App becomes a ConfigMap + Deployment + Service."  (the recipe)
App (XR)    ->  "Please run me one, called hello-snippy." (a request)
```

> 🧠 **v1 → v2 differences you must know:**
> - **Compositions are a function pipeline.** v2 removed native patch-and-transform
>   from core; the logic now lives in composition **functions** (mandatory). We'll
>   use the drop-in `function-patch-and-transform`.
> - **XRs are namespaced.** The XRD sets `scope: Namespaced`, so an `App` lives in
>   a namespace and is governed by ordinary RBAC.
> - **No claims.** v1 needed a separate *claim* (XRC) to give developers a
>   namespaced handle on a cluster-scoped XR. In v2 the XR itself is namespaced,
>   so claims are gone. (Course 5 covers the migration story.)
> - **Native composition.** A v2 Composition can compose **native Kubernetes
>   resources** (ConfigMap, Deployment, Service) directly — no `provider-kubernetes`
>   required. That's why Course 2's provider is optional here.

---

## 3. Install the functions

A Composition pipeline references functions by name, so the functions must be
installed first. We use two workhorses:

```bash
kubectl apply -f manifests/course-03/functions.yaml
kubectl get functions
kubectl wait function/function-patch-and-transform function/function-auto-ready \
  --for=condition=Healthy --timeout=180s
```

From `functions.yaml`:

- **`function-patch-and-transform`** (`v0.8.2`) — builds composed resources from
  templates and patches values onto them (the modern form of classic patch &
  transform).
- **`function-auto-ready`** (`v0.4.1`) — inspects the composed resources and marks
  the XR `Ready` when they're all ready, so you don't wire readiness by hand.

Functions are packages (OCI images) and run as their own pods — just like
providers. `kubectl get pods -n crossplane-system` will show them once Healthy.

---

## 4. Define the API (XRD)

```bash
kubectl apply -f manifests/course-03/xrd.yaml
kubectl get xrd
# NAME                      ESTABLISHED   OFFERED   AGE
# apps.platform.snippy.io   True          ...       10s
```

Walk through what you just declared (`xrd.yaml`):

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: apps.platform.snippy.io
spec:
  scope: Namespaced          # v2: the App lives in a namespace, RBAC governs it
  group: platform.snippy.io
  names:
    kind: App
    plural: apps
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                image:    { type: string }
                replicas: { type: integer, default: 1 }
                greeting: { type: string, default: "Hello from SnippyStack" }
              required: [image]
            status:
              type: object
              properties:
                ready: { type: boolean }
                url:   { type: string }
```

Three things to notice:

1. **`scope: Namespaced`** — the headline v2 feature. Once established, `App` is a
   normal namespaced kind you can `kubectl get` like any other.
2. **The schema is your whole contract.** `image` is required; `replicas` and
   `greeting` have **defaults**, so a developer can omit them. Everything else
   about Snippy (ports, labels, the three objects) is hidden.
3. **`status`** fields (`ready`, `url`) are what the control plane reports *back*.

Once `ESTABLISHED=True`, the `App` CRD exists in the API server:

```bash
kubectl api-resources | grep platform.snippy.io
kubectl explain app.spec            # your own API, self-documenting
```

---

## 5. Let Crossplane compose core resources (RBAC)

Crossplane composes resources using its **own ServiceAccount**. That SA can manage
Deployments out of the box, but **not** arbitrary core resources like ConfigMaps
and Services. We grant that with a ClusterRole that *aggregates* into Crossplane's
primary role:

```bash
kubectl apply -f manifests/course-03/rbac-crossplane-aggregate.yaml
```

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: crossplane:aggregate-snippystack
  labels:
    rbac.crossplane.io/aggregate-to-crossplane: "true"   # the magic label
rules:
  - apiGroups: [""]
    resources: ["configmaps", "services"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

The `rbac.crossplane.io/aggregate-to-crossplane: "true"` label tells Crossplane's
RBAC manager to fold these rules into the Crossplane SA automatically — no
restart, no editing the core role. You'll meet the RBAC manager properly in
Courses 6 and 13.

> ⚠️ **Skip this and your `App` will half-materialize.** The Deployment appears,
> but the ConfigMap and Service hang, and `crossplane beta trace` shows RBAC
> `Forbidden` events on the composed resources. If you see that, this is the fix.

---

## 6. Define the implementation (Composition)

```bash
kubectl apply -f manifests/course-03/composition.yaml
kubectl get composition
```

Walk through the structure of `composition.yaml`:

```yaml
spec:
  compositeTypeRef:
    apiVersion: platform.snippy.io/v1alpha1   # which XR this implements
    kind: App
  mode: Pipeline                              # v2: a pipeline of functions
  pipeline:
    - step: render-resources
      functionRef: { name: function-patch-and-transform }
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: configmap   { ... }
          - name: deployment  { ... }
          - name: service     { ... }
    - step: ready
      functionRef: { name: function-auto-ready }
```

- **`compositeTypeRef`** binds this Composition to the `App` kind from your XRD.
- **`mode: Pipeline`** runs an ordered list of steps; each step calls a function.
- The **`render-resources`** step feeds `function-patch-and-transform` three
  resource templates (`base`) plus **patches** that copy fields from the `App` XR
  onto them.
- The **`ready`** step runs `function-auto-ready` to set the XR's readiness from
  its children.

The patches are `FromCompositeFieldPath` — "read a field from the XR, write it
onto the composed resource." A few real ones from the file:

```yaml
# ConfigMap name becomes "<app>-config"; its data.greeting comes from the XR
- type: FromCompositeFieldPath
  fromFieldPath: metadata.name
  toFieldPath: metadata.name
  transforms:
    - type: string
      string: { type: Format, fmt: "%s-config" }
- type: FromCompositeFieldPath
  fromFieldPath: spec.greeting
  toFieldPath: data.greeting

# Deployment gets replicas, image, and the greeting as APP_GREETING
- { type: FromCompositeFieldPath, fromFieldPath: spec.replicas,
    toFieldPath: spec.replicas }
- { type: FromCompositeFieldPath, fromFieldPath: spec.image,
    toFieldPath: spec.template.spec.containers[0].image }
- { type: FromCompositeFieldPath, fromFieldPath: spec.greeting,
    toFieldPath: spec.template.spec.containers[0].env[0].value }
```

> 🧠 **One `App` field can fan out to many places.** `metadata.name` is patched
> onto the Deployment's name, its `selector.matchLabels.app`, *and* its Pod
> template label — and onto the Service's selector — so two Apps in one namespace
> never cross-wire their Pods. The XR is the single source of truth; the patches
> distribute it. (Course 4 goes deep on patches and transforms.)

---

## 7. Create an App — watch a whole environment appear

This is the moment. One resource, one request:

```bash
kubectl apply -f manifests/course-03/app.yaml
```

```yaml
apiVersion: platform.snippy.io/v1alpha1
kind: App
metadata:
  name: hello-snippy
  namespace: default
spec:
  image: snippy:0.1
  replicas: 2
  greeting: "Hello from my first composite API"
```

Watch the control plane do the assembly you used to do by hand:

```bash
kubectl get app hello-snippy                 # your API
kubectl get composite                        # the composite resource (XR)
kubectl get cm,deploy,svc -l crossplane.io/composite=hello-snippy
# a ConfigMap (hello-snippy-config), a Deployment (hello-snippy),
# and a Service (hello-snippy) — all materialized for you
```

Wait for readiness, then see Snippy itself:

```bash
kubectl wait app/hello-snippy --for=condition=Ready --timeout=120s
kubectl port-forward svc/hello-snippy 8080:80
# browse http://localhost:8080 — Snippy prints its POD_NAME and your greeting
```

The greeting you set in `spec.greeting` flowed → ConfigMap → `APP_GREETING` env →
the running container. That round trip *is* the proof your composite API works.

Finally, see the whole tree in one command:

```bash
crossplane beta trace app hello-snippy
# App/hello-snippy
# ├─ ConfigMap/hello-snippy-config   Synced  Ready
# ├─ Deployment/hello-snippy         Synced  Ready
# └─ Service/hello-snippy            Synced  Ready
```

---

## 8. Peek under the hood

### ownerReferences wire the App to its children

```bash
kubectl get deploy hello-snippy -o jsonpath='{.metadata.ownerReferences}' | yq -P
```

Each composed resource carries an **ownerReference** back to the composite. This
is the *exact* garbage-collection mechanism you saw in `myk8scourses` Course 2,
where a Deployment owned its ReplicaSet which owned its Pods: delete the owner and
Kubernetes cascades the delete to the children. Crossplane didn't invent a new
cleanup system — it reuses Kubernetes' own.

### The composition-resource-name annotation

```bash
kubectl get cm hello-snippy-config \
  -o jsonpath='{.metadata.annotations.crossplane\.io/composition-resource-name}'; echo
# -> configmap
```

Each child is stamped with the `name` you gave it in the Composition's `resources`
list (`configmap`, `deployment`, `service`). That's how the composition engine
matches an *observed* child to its *desired* template on the next reconcile,
instead of recreating duplicates. You'll trace this matching in Course 8.

---

## 9. Break it on purpose

### Delete a composed resource — composition heals it

```bash
kubectl delete deploy hello-snippy
kubectl get deploy hello-snippy -w     # the composition engine recreates it
```

Same heartbeat you saw in Course 2, now one level up: the XR's desired state
includes that Deployment, so deleting it is drift, and drift gets corrected.

### Delete the App — everything is garbage-collected

```bash
kubectl delete app hello-snippy
kubectl get cm,deploy,svc -l crossplane.io/composite=hello-snippy
# all gone — the ownerReferences cascaded the delete
```

Delete the one noun and the entire environment disappears cleanly. Compare that to
Course 0, where tearing down an environment meant hunting three objects across a
namespace and hoping you got them all.

> 🧠 **This is Problem #2 dissolving.** A developer never touched a Deployment,
> a label selector, or an env var. They applied an `App` with three fields and got
> a correct, running, self-healing environment — and removed it just as cleanly.

---

## 10. Scorecard update

| # | Course 0 pain | Status after Course 3 |
|---|---------------|------------------------|
| 1 | No single source of truth | ⏳ the `App` XR is now the single source for a whole environment |
| 2 | No self-service API | ⏳ you built the `App` API; developers get self-service in Course 5 |
| 3 | Two worlds (cluster vs cloud) | ✅ (Course 2) — and now native resources compose through the same engine |
| 4 | No continuous reconciliation of external state | ✅ composed resources self-heal (you deleted the Deployment; it came back) |
| 5 | Platform not installable | ⏭️ Course 10 (bundle this XRD + Composition as a package) |

---

## 11. Takeaway

You taught the control plane a new noun. An **XRD** declared the `App` schema —
your public contract, `scope: Namespaced`, `image` required, sensible defaults —
and a **Composition** (a v2 function **Pipeline**) implemented it, fanning one
`App` into a ConfigMap + Deployment + Service with `FromCompositeFieldPath`
patches and `function-auto-ready`. One `kubectl apply` built a running Snippy;
one `kubectl delete` cleaned it up via ownerReferences — the same GC you already
knew. Problems #1 and #2 are now visibly in motion.

But your `App` is still a little rigid — the patches are hardcoded, and you
haven't really *played* with transforms, defaults, or multiple environments.
Next, you make the `App` genuinely configurable and learn to render it locally
without a cluster round-trip.

### Cleanup

```bash
kubectl delete -f manifests/course-03/app.yaml --ignore-not-found
# leave the XRD, Composition, functions, and RBAC installed — Course 4 builds
# directly on them. To fully reset:
# kubectl delete -f manifests/course-03/composition.yaml --ignore-not-found
# kubectl delete -f manifests/course-03/xrd.yaml --ignore-not-found
# kubectl delete -f manifests/course-03/rbac-crossplane-aggregate.yaml --ignore-not-found
# kubectl delete -f manifests/course-03/functions.yaml --ignore-not-found
```

**Next:** [Course 4 — Compositions II: Functions, Patch & Transform](./course-04-compositions-functions-patch-transform.md),
where you make the `App` fully configurable and render it locally with
`crossplane render` — no cluster round-trip.
