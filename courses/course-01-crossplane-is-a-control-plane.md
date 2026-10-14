# Course 1 — Crossplane Is a Control Plane

> **Goal:** Install Crossplane into your cluster and discover the single most
> important fact about it: it is **just more Kubernetes**. It adds a reconcile
> engine and some CRDs — and, deliberately, *nothing you can use yet*. By the end
> you'll understand the thesis of the whole series: Kubernetes is a control plane
> for containers; Crossplane turns it into a control plane for **anything with an
> API**.

**You need:** the cluster from Course 0, `kubectl`, `helm`, and the `crossplane`
CLI (see [`../README.md`](../README.md) prerequisites).

**Time:** ~45 min.

---

## 1. Recap the pain

Course 0 left you drowning in copy-pasted YAML, with no single source of truth,
no self-service API, and cloud resources living in a separate, drift-prone world.
You concluded you need a *control plane* that reconciles everything behind an API
you can offer others. Today you install the thing that provides it.

---

## 2. The core idea: Crossplane is Kubernetes, extended

Recall the mental model from `myk8scourses`:

```
Kubernetes = an API server (desired state in etcd) + controllers that
             reconcile the real world toward that state, forever.
```

A Deployment controller watches Deployment objects and makes Pods exist.
That's it — "a type + a loop."

**Crossplane adds two kinds of extension to that same machine:**

1. **Providers** — controllers whose "real world" is an *external* API (AWS,
   GCP, Azure, a database, another cluster). They reconcile external resources
   exactly like the Deployment controller reconciles Pods.
2. **Composition** — a way to define your *own* high-level API types (like
   `App`) that fan out into many other resources.

Crucially, Crossplane invents **no new control plane**. It runs *inside* your
Kubernetes cluster, stores everything in the *same* etcd, and speaks the *same*
API. Everything you learned about CRDs, controllers, RBAC, and reconciliation in
`myk8scourses` applies unchanged. That's the whole trick.

---

## 3. Install Crossplane

Crossplane installs with Helm into its own namespace.

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace

kubectl -n crossplane-system get pods
```

Wait for the `crossplane` and `crossplane-rbac-manager` pods to be `Running`:

```bash
kubectl -n crossplane-system wait --for=condition=Ready pod --all --timeout=120s
```

Check the version (this series targets **v2**):

```bash
crossplane version        # client + server; server should report v2.x
```

---

## 4. What did that actually add?

Here's the surprise: **you still can't provision anything.** Look at what Helm
installed — it's all Kubernetes-native.

### New CRDs (new API types, no instances yet)

```bash
kubectl get crds | grep crossplane.io
```

You'll see types like `providers.pkg.crossplane.io`,
`functions.pkg.crossplane.io`, `configurations.pkg.crossplane.io`, and the
`apiextensions.crossplane.io` group (XRDs, Compositions). These are **empty
nouns** — the vocabulary for installing extensions and defining APIs. None of
them manages a cloud resource on its own.

### New controllers (new loops, nothing to reconcile yet)

```bash
kubectl -n crossplane-system get deploy
```

- **crossplane** — the core: runs the package manager and the composition engine
  (you'll meet both in Track B).
- **crossplane-rbac-manager** — automatically maintains the RBAC that lets
  Crossplane and its providers operate (Course 6, 13).

That's it. You installed an **engine and an empty vocabulary**. The analogy: you
just installed `kubectl`+controllers for a cluster with no Deployments yet. The
power comes when you teach it about the outside world (Course 2) and define your
own APIs (Course 3).

> 🧠 **Everything is an API object.** `kubectl get crds | grep crossplane`
> *is* the feature list of your control plane right now. In Course 2 that list
> grows the moment you install a provider — because a provider is just *more
> CRDs + a controller*, delivered as a package.

---

## 5. Peek under the hood: the package model

Why can't you provision anything yet? Because Crossplane core ships almost no
opinions. Capabilities arrive as **packages** — OCI images you install at
runtime:

| Package kind | Adds | You'll install one in |
|--------------|------|------------------------|
| **Provider** | CRDs for external resources + a controller pod to reconcile them | Course 2 |
| **Function** | a gRPC server that computes composed resources | Course 3–4 |
| **Configuration** | your own XRDs + Compositions, bundled | Course 10 |

When you create a `Provider` object, the package manager (inside the `crossplane`
pod) pulls the image, installs the CRDs it contains, and starts a controller
pod. This is reconciliation again: a `Provider` is desired state; the package
manager makes the controller *exist*. You'll trace this in Course 9.

---

## 6. Break it on purpose — prove it's inert (and prove it's Kubernetes)

### Try to use a resource that doesn't exist yet

```bash
kubectl get buckets.s3.aws.upbound.io
# error: the server doesn't have a resource type "buckets"
```

Right — no provider installed, so that noun doesn't exist. Crossplane out of the
box knows *nothing* about AWS. Capabilities are opt-in packages.

### Prove it stores state like any Kubernetes object

Everything Crossplane does is a normal API object in etcd. Watch Crossplane's own
config objects react to the API:

```bash
kubectl get lock.pkg.crossplane.io -o yaml | head -n 20   # the package dependency lock
kubectl api-resources | grep crossplane.io | wc -l         # how many new nouns exist
```

There are no hidden databases, no side channels. If you learned to debug
Kubernetes with `kubectl get/describe/events`, you already know how to debug
Crossplane.

### Delete and reinstall (optional)

```bash
helm uninstall crossplane -n crossplane-system
kubectl get crds | grep crossplane.io    # CRDs may linger until GC'd
helm install crossplane crossplane-stable/crossplane -n crossplane-system
```

Nothing dramatic happens — because you haven't given it anything to manage yet.
That changes in Course 2.

---

## 7. Scorecard update

| # | Course 0 pain | Status after Course 1 |
|---|---------------|------------------------|
| 1 | No single source of truth | ⏳ engine installed; state will live in etcd |
| 2 | No self-service API | ⏭️ Course 3 (define your own type) |
| 3 | Two worlds (cluster vs cloud) | ⏭️ Course 2 (providers) |
| 4 | No continuous reconciliation of external state | ⏭️ Course 2, 7 |
| 5 | Platform not installable | ⏭️ Course 10 (packages) |

---

## 8. Takeaway

Crossplane is not a separate system bolted onto Kubernetes — it *is* Kubernetes,
extended with a package manager, a composition engine, and the ability to run
controllers (providers) that reconcile external APIs. Installing it adds an
engine and an empty vocabulary; every capability after this is a **package** you
opt into. The reconcile loop you already trust is about to point at the whole
world.

**Next:** [Course 2 — Providers & Managed Resources](./course-02-providers-and-managed-resources.md),
where you install your first provider and watch a controller make the *outside*
world match a Kubernetes object.
