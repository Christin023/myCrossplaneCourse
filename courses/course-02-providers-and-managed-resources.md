# Course 2 — Providers & Managed Resources

> **Goal:** Install your first **provider** and watch a controller reconcile the
> *outside* world toward a Kubernetes object. You'll learn that a provider is
> just a controller whose "cluster" is some external API — it ships CRDs
> (**Managed Resources**) plus a controller pod. By the end you'll have
> Crossplane creating, enforcing, and deleting a real ConfigMap, and you'll have
> watched continuous reconciliation fight you when you try to drift it.

**You need:** the cluster from Course 1 with Crossplane running, `kubectl`, and
the `crossplane` CLI. No cloud credentials required — everything here runs
against the local cluster.

**Time:** ~50 min.

---

## 1. Recap the pain

Course 1 ended with a deliberate anticlimax: you installed Crossplane and it
could do **nothing**. `kubectl get buckets...` returned *"the server doesn't
have a resource type."* You had an engine and an empty vocabulary — a reconcile
loop with nothing to reconcile. We promised the vocabulary grows the moment you
install a package. Today you install two providers and finally point that loop at
something real.

This is also where Course 0's **Problem #3** (two worlds — in-cluster things
reconcile, cloud things drift) starts to close.

---

## 2. The core idea: a provider is a controller for someone else's API

Remember the one-line definition of a Kubernetes controller from `myk8scourses`
Course 2: *a type + a loop*. The Deployment controller watches `Deployment`
objects and makes **Pods** exist, forever.

A **provider** is exactly that shape, with one twist — its "real world" is an
*external* API instead of the local Pod API:

```
Deployment controller : Deployment object  ->  Pods (in this cluster)
provider-aws          : Bucket object      ->  an S3 bucket (in AWS)
provider-kubernetes   : Object             ->  any object (in some cluster)
```

A provider delivers two things when you install it:

1. **CRDs** — one per external resource type. Each instance is a **Managed
   Resource (MR)**: a Kubernetes object that maps **1:1** to one external thing.
2. **A controller pod** — runs in `crossplane-system`, watches those CRDs, and
   runs the `Observe → Create/Update/Delete` loop against the external API
   (you'll trace that loop in detail in Course 7).

We'll install two:

- **`provider-nop`** — a teaching provider. Its `NopResource` has **no real
  backend**; it just lets you watch the MR lifecycle and conditions in isolation,
  no credentials needed.
- **`provider-kubernetes`** — its "external API" is a Kubernetes cluster. We
  point it at the *same* cluster it runs in, so it can manage arbitrary objects
  (kind `Object`) — a perfect, free stand-in for a cloud provider.

> 🧠 **A provider is "more Kubernetes," installed at runtime.** You don't rebuild
> the API server to teach it about S3 — you create a `Provider` object, the
> package manager pulls an OCI image, installs its CRDs, and starts a controller.
> The feature list of your control plane is literally `kubectl api-resources`.

---

## 3. Install the providers

Both manifests are tiny: a `Provider` object naming the OCI package to pull.

```bash
kubectl apply -f manifests/course-02/provider-nop.yaml
kubectl apply -f manifests/course-02/provider-kubernetes.yaml
```

`provider-nop.yaml` pulls `provider-nop:v0.4.0`; `provider-kubernetes.yaml` pulls
`provider-kubernetes:v0.18.0`. The package manager now downloads each image,
unpacks the CRDs, and starts a controller pod. Watch them become healthy:

```bash
kubectl get providers
# NAME                  INSTALLED   HEALTHY   PACKAGE                                    AGE
# provider-kubernetes   True        True      .../provider-kubernetes:v0.18.0            60s
# provider-nop          True        True      .../provider-nop:v0.4.0                    60s

kubectl wait provider/provider-nop provider/provider-kubernetes \
  --for=condition=Healthy --timeout=180s
```

Now re-run the "what can my control plane do" check from Course 1 and watch the
vocabulary grow:

```bash
kubectl api-resources | grep crossplane.io | wc -l   # bigger than last course
kubectl get crds | grep nop.crossplane.io            # NopResource appeared
kubectl get crds | grep kubernetes.crossplane.io     # Object appeared
```

> 🧠 **Installing a provider is reconciliation too.** A `Provider` object is
> *desired state*; the package manager makes the controller pod *exist*. Same
> loop, one level up. You'll open this up in Course 9.

---

## 4. Give provider-kubernetes permission to act

`provider-kubernetes` runs as a pod with its **own ServiceAccount**, and by
default that SA can't touch most of the cluster. Before it can manage objects we
must grant it permissions. For a learning cluster we bind `cluster-admin`; in
production you'd scope this down (Course 13).

Here's the catch: **the provider's active ServiceAccount name is
auto-generated** (it includes a revision hash), so a hardcoded binding may not
match. Discover the real SA and bind it dynamically:

```bash
SA=$(kubectl -n crossplane-system get sa -o name \
  | grep provider-kubernetes | head -1 \
  | sed 's|serviceaccount/|crossplane-system:|')
echo "$SA"   # e.g. crossplane-system:provider-kubernetes-abc123

kubectl create clusterrolebinding provider-kubernetes-admin \
  --clusterrole cluster-admin \
  --serviceaccount="$SA"
```

> ⚠️ **Don't just `kubectl apply` the static binding and move on.**
> `providerconfig-kubernetes.yaml` *also* contains a `ClusterRoleBinding` that
> targets the SA name `provider-kubernetes`. That's a reasonable default, but if
> your generated SA differs it will silently grant nothing and your `Object` MRs
> will hang with RBAC errors. Either run the dynamic command above, or edit the
> `subjects[0].name` in that file to match the `echo "$SA"` output before
> applying.

---

## 5. Configure the provider, then make your first MR

### 5a. ProviderConfig — *how* to reach the target

Every `Object` MR needs to know which cluster to talk to. That's a
**ProviderConfig**:

```bash
kubectl apply -f manifests/course-02/providerconfig-kubernetes.yaml
```

The key field is the credential source:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: InjectedIdentity
```

**`InjectedIdentity`** means *"use the provider pod's own ServiceAccount"* — i.e.
manage **this** cluster. (For a *remote* cluster you'd reference a kubeconfig
Secret instead.) This is why Section 4's RBAC mattered: `InjectedIdentity` only
has the powers you granted that SA.

### 5b. NopResource — watch the loop with no backend

Create the backend-free MR and watch its conditions:

```bash
kubectl apply -f manifests/course-02/nopresource.yaml
kubectl get managed            # lists ALL managed resources, any provider
kubectl get nopresource hello-nop -o yaml | yq '.status.conditions'
```

The manifest *scripts* its own readiness so you can study timing:

```yaml
spec:
  forProvider:
    conditionAfter:
      - conditionType: Ready
        conditionStatus: "False"
        time: 0s
      - conditionType: Ready
        conditionStatus: "True"
        time: 10s
```

Watch `READY` flip from `False` to `True` about **10 seconds** after creation —
a simulated external resource that takes time to come up:

```bash
kubectl get nopresource hello-nop -w
# hello-nop   False   ...   (first ~10s)
# hello-nop   True    ...   (after conditionAfter fires)
```

No `providerConfigRef` is needed here — `provider-nop` has no external system to
reach. It exists purely to let you see `SYNCED` and `READY` without credentials.

### 5c. Object — a REAL managed resource

Now the real thing. This `Object` wraps an ordinary ConfigMap:

```bash
kubectl apply -f manifests/course-02/object-configmap.yaml
kubectl get object snippy-greeting
kubectl get cm snippy-greeting -o yaml
```

The MR's `spec.forProvider.manifest` is the desired state of the external object:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha2
kind: Object
metadata:
  name: snippy-greeting
spec:
  providerConfigRef:
    name: default
  forProvider:
    manifest:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: snippy-greeting
        namespace: default
      data:
        greeting: "Hello from a Crossplane-managed ConfigMap"
```

Within a second or two a **real ConfigMap** named `snippy-greeting` appears in
`default`, created by Crossplane — not by you running `kubectl create cm`.
Crossplane now *owns* it.

---

## 6. Peek under the hood

### The `crossplane.io/external-name` annotation

Look at your `Object` MR's metadata:

```bash
kubectl get object snippy-greeting -o jsonpath='{.metadata.annotations}' | yq -P
```

You'll find `crossplane.io/external-name: snippy-greeting`. **This annotation is
the bridge between the MR and its external identity.** The MR's Kubernetes name
is a local handle; the external-name is *what the thing is called in the external
system*. For a cloud bucket it would be the bucket's real name; for provider-nop
it's just the resource name. On every reconcile the provider reads this
annotation to find the object it's responsible for. You'll lean on it hard in
Course 7.

### SYNCED vs READY — two different questions

```bash
kubectl get managed
# NAME ...  SYNCED  READY ...
```

Every MR reports two conditions, and they answer different questions:

| Condition | Means | Analogy |
|-----------|-------|---------|
| **SYNCED** | The provider successfully reconciled — it talked to the external API and the request was accepted. | "The API call went through." |
| **READY**  | The external resource is actually *usable* (fully provisioned). | "The thing is up." |

A cloud database can be `SYNCED=True` (create accepted) long before `READY=True`
(provisioning finished minutes later). The `NopResource` let you see this split
on purpose: its `conditionAfter` kept `READY=False` for 10s while `SYNCED` was
true almost immediately.

### Connection details → Secrets

Many MRs produce **connection details** — endpoints, usernames, passwords — that
the provider writes into a Kubernetes **Secret**. That's how a composed app later
consumes a database's credentials without anyone copy-pasting them. Our ConfigMap
has nothing secret to emit, but keep the concept in your pocket: *MRs can hand
their outputs to the rest of the cluster as Secrets.* You'll wire this through a
Composition in later courses.

---

## 7. Break it on purpose

This is the payoff — watch *continuous reconciliation* defend your desired state.
This previews Course 0's **Problem #4** (external resources with no heartbeat):
Crossplane gives this ConfigMap a heartbeat.

### Drift it by hand

```bash
kubectl edit cm snippy-greeting
# change data.greeting to "I changed this manually" and save
kubectl get cm snippy-greeting -o jsonpath='{.data.greeting}'; echo
```

Wait a few seconds, read it again — the provider **reverts** it to
`"Hello from a Crossplane-managed ConfigMap"`. The MR's `manifest` is the source
of truth; your manual edit is drift, and drift gets corrected. This is the exact
behavior `terraform apply` *couldn't* give you in Course 0: not a pulse, a
heartbeat.

### Delete the external object

```bash
kubectl delete cm snippy-greeting
kubectl get cm snippy-greeting -w     # it comes back
```

The provider observes the ConfigMap is gone, diffs against desired state, and
**recreates** it. You cannot delete a Crossplane-managed object out from under
the control plane — only the control plane can.

### Delete the MR (the right way)

```bash
kubectl delete -f manifests/course-02/object-configmap.yaml
kubectl get cm snippy-greeting        # NotFound — the real ConfigMap is gone too
```

Deleting the **MR** deletes the external resource with it, because the default
`deletionPolicy` is `Delete`. The MR *is* the resource's lifecycle handle. (In
Course 7 you'll flip this to `Orphan` to keep an external resource after deleting
its MR.)

> ⚠️ **`deletionPolicy: Delete` is the default and it's load-bearing.** In
> production, deleting an MR for a database deletes the database. This is why
> Course 13 covers `Usage` (deletion ordering) and why you protect real MRs with
> care.

---

## 8. Scorecard update

| # | Course 0 pain | Status after Course 2 |
|---|---------------|------------------------|
| 1 | No single source of truth | ⏳ the MR's `manifest` is now the source of truth for one object |
| 2 | No self-service API | ⏭️ Course 3 (define your own `App` type) |
| 3 | Two worlds (cluster vs cloud) | ✅ a provider reconciles the "external" world like Pods — one engine, one loop |
| 4 | No continuous reconciliation of external state | ⏳ you *saw* it (revert/recreate); formalized in Course 7 |
| 5 | Platform not installable | ⏭️ Course 10 (packages) |

---

## 9. Takeaway

A **provider** is nothing exotic: it's the reconcile loop you already trust,
wrapped around someone else's API. Install it and your control plane learns new
nouns (CRDs); each instance is a **Managed Resource** that maps 1:1 to one
external thing, bridged by the `crossplane.io/external-name` annotation and
guarded by two conditions — `SYNCED` (call accepted) and `READY` (thing up). You
proved it's a heartbeat, not a pulse: hand-edit or delete the backing object and
the provider puts it back. That's Problem #3 closed and Problem #4 previewed.

But notice: you still manage *one primitive at a time*. A developer who wants
"a Snippy environment" would need a ConfigMap MR **and** a Deployment **and** a
Service, assembled correctly — the very toil of Course 0's Problem #2. Next, you
teach the control plane a higher-level noun.

### Cleanup

```bash
# remove the teaching MRs (safe: no cloud cost)
kubectl delete -f manifests/course-02/nopresource.yaml --ignore-not-found
kubectl delete -f manifests/course-02/object-configmap.yaml --ignore-not-found

# leave the providers + ProviderConfig installed — Course 3 does not need
# provider-kubernetes (v2 composes native resources directly), but keeping them
# costs nothing. To fully remove:
# kubectl delete clusterrolebinding provider-kubernetes-admin
# kubectl delete -f manifests/course-02/providerconfig-kubernetes.yaml
# kubectl delete -f manifests/course-02/provider-kubernetes.yaml
# kubectl delete -f manifests/course-02/provider-nop.yaml
```

**Next:** [Course 3 — Your First Composite API](./course-03-your-first-composite-api.md),
where you teach the control plane the noun `App` and compose a whole Snippy
environment from a single resource.
