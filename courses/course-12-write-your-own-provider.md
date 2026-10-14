# Course 12 — Write Your Own Provider

> **Goal:** Demystify providers by building the mental model from the inside. In
> Course 7 you watched a managed resource's reconcile loop; here you implement
> the contract behind it — the four-method `ExternalClient` — against a toy
> external API. This is a code-reading, internals course: by the end you'll see
> that `provider-nop`, `provider-kubernetes`, and the giant cloud providers are
> all the *same shape*, and that shape is a loop you already understand.

**You need:** the cluster with Crossplane v2, `provider-nop` and
`provider-kubernetes` installed (from Course 2), `kubectl`, and — optionally — Go
and the `crossplane` CLI if you want to scaffold. Mostly you'll read and reason.

**Time:** ~50 min.

---

## 1. Recap the pain

So far you've only *consumed* providers: `provider-kubernetes` to apply objects,
`provider-nop` to fake a resource, the composition engine to orchestrate them.
They felt like black boxes that "just reconcile." But a platform team that can't
reason about its providers can't debug them, extend them, or trust them. And one
day the resource you need won't have a provider — then what?

The relief isn't a new feature; it's *understanding*. A provider is not magic.
It's the reconcile loop from `myk8scourses` Course 12 wrapped around someone
else's API. Today we open the box.

---

## 2. The concept: a provider = CRD + managed.Reconciler + ExternalClient

Every provider has exactly three parts:

1. **A managed resource (MR) CRD** — e.g. `Object` (provider-kubernetes),
   `NopResource` (provider-nop), `Bucket` (provider-aws-s3). The MR *is* desired
   state for one external thing.
2. **A controller** — built on **crossplane-runtime's `managed.Reconciler`**.
   You don't write the reconcile loop; crossplane-runtime provides it. It watches
   MRs, handles finalizers, status conditions, retries, and
   `managementPolicies`.
3. **An `ExternalClient`** — the *only* code you write. The generic reconciler
   calls your four methods to talk to the real external API.

> 🧠 **crossplane-runtime already wrote the loop; you only fill in the verbs.**
> This is the inversion that makes providers tractable. The hard parts —
> watching, requeueing, finalizers, condition management, exponential backoff —
> are shared library code. You implement `Observe/Create/Update/Delete` and a
> `Connect`, and you get a production-grade controller for free.

---

## 3. The ExternalClient contract (Go pseudocode)

Here's the shape, lightly simplified from the real crossplane-runtime
`managed.ExternalClient` interface. The generic reconciler calls these:

```go
// Connect builds a client for the external API, using credentials from the
// resource's ProviderConfig. Called before each reconcile.
func (c *connector) Connect(ctx context.Context, mg resource.Managed) (ExternalClient, error) {
    cr := mg.(*v1alpha1.MyResource)
    pc := c.getProviderConfig(ctx, cr.GetProviderConfigReference().Name)
    creds := c.resolveCreds(ctx, pc)          // e.g. a Secret → API token
    return &external{api: toyapi.New(creds)}, nil
}

// Observe answers: does the external resource exist, and does it match spec?
// This runs EVERY reconcile — it's the "observe" half of the loop.
func (e *external) Observe(ctx context.Context, mg resource.Managed) (ExternalObservation, error) {
    cr := mg.(*v1alpha1.MyResource)
    id := meta.GetExternalName(cr)            // read the external-name annotation
    if id == "" {
        return ExternalObservation{ResourceExists: false}, nil   // never created
    }
    obj, err := e.api.Get(ctx, id)
    if toyapi.IsNotFound(err) {
        return ExternalObservation{ResourceExists: false}, nil   // drifted away → Create
    }
    upToDate := obj.Spec == cr.Spec.ForProvider              // diff desired vs actual
    return ExternalObservation{
        ResourceExists:   true,
        ResourceUpToDate: upToDate,                           // false → Update
        ConnectionDetails: managed.ConnectionDetails{         // surfaced as a Secret
            "endpoint": []byte(obj.Endpoint),
        },
    }, nil
}

// Create is called only when Observe reported ResourceExists:false.
func (e *external) Create(ctx context.Context, mg resource.Managed) (ExternalCreation, error) {
    cr := mg.(*v1alpha1.MyResource)
    obj, err := e.api.Create(ctx, cr.Spec.ForProvider)
    meta.SetExternalName(cr, obj.ID)          // WRITE the external-name back
    return ExternalCreation{
        ConnectionDetails: managed.ConnectionDetails{"password": obj.Password},
    }, err
}

// Update is called only when Observe reported ResourceUpToDate:false.
func (e *external) Update(ctx context.Context, mg resource.Managed) (ExternalUpdate, error) {
    cr := mg.(*v1alpha1.MyResource)
    _, err := e.api.Update(ctx, meta.GetExternalName(cr), cr.Spec.ForProvider)
    return ExternalUpdate{}, err
}

// Delete is called when the MR is being deleted (reconciler handles the finalizer).
func (e *external) Delete(ctx context.Context, mg resource.Managed) (ExternalDelete, error) {
    cr := mg.(*v1alpha1.MyResource)
    err := e.api.Delete(ctx, meta.GetExternalName(cr))
    return ExternalDelete{}, err
}
```

Trace Course 7's loop in those signatures:

- **`external-name` annotation** — the stable link between your MR and the real
  external object. `Observe` *reads* it to know what to look up; `Create`
  *writes* it so future reconciles find the thing it made. Lose it and the
  provider orphans the external resource and creates a duplicate.
- **Connection details** — `Observe`/`Create` return a
  `managed.ConnectionDetails` map; crossplane-runtime writes it into a Kubernetes
  **Secret** (endpoints, passwords). This is how composed databases hand
  credentials to apps.
- **`managementPolicies`** — the field you met in
  `manifests/course-07/management-and-deletion-policies.yaml`. The reconciler
  consults it to decide which verbs it's *allowed* to call: `Observe` only
  (observe-only), no `Delete` (orphan on teardown), skip `Create`, etc. Your
  `ExternalClient` doesn't check policies — the generic reconciler gates the
  calls for you.

---

## 4. The punchline: nop and kubernetes are the same shape

Everything you've used fits this one interface:

| Provider | External API is... | `Observe` does | `Create` does |
|----------|--------------------|----------------|----------------|
| **provider-nop** | nothing (a fake) | returns the exists/upToDate you configured | no-op; just reports success |
| **provider-kubernetes** | **another Kubernetes cluster** | `GET` the target object | `kubectl apply` the object |
| provider-aws-s3 | the AWS S3 API | `HeadBucket` | `CreateBucket` |

`provider-nop` *fakes* the four methods so you can study the loop without a real
backend. `provider-kubernetes`'s "external world" happens to *be* a Kubernetes
API — so its `Observe` is a GET and its `Create` is an apply. Same contract,
different `e.api`. Once you see this, every provider on the Marketplace reads the
same way.

> 🧠 **A provider is a translator, not a special kind of program.** It translates
> the universal `Observe/Create/Update/Delete` verbs into one specific external
> API's dialect. The verbs never change; only the dialect does.

### Where real providers come from

- **The provider-template repo** (`crossplane/provider-template` on GitHub) —
  scaffolds the CRD types, the `managed.Reconciler` wiring, and empty
  `ExternalClient` stubs. You fill in the four methods.
- **Upjet** — generates entire providers from existing **Terraform providers**.
  Most big cloud providers (`provider-upjet-aws`, etc.) are Upjet-generated:
  Terraform's resource schema becomes CRDs, and Terraform's CRUD becomes the
  `ExternalClient`. That's how hundreds of resource types appear without anyone
  hand-writing each `Observe`.

---

## 5. Lab: read a real managed resource from the inside

You don't need to compile Go to *see* the contract at work. Inspect the providers
you already have.

### 5a. See the MR CRDs a provider installed

```bash
# Every provider adds MR types as CRDs — its "nouns".
kubectl get crds | grep kubernetes.crossplane.io    # provider-kubernetes: Object, ...
kubectl get crds | grep nop.crossplane.io           # provider-nop: NopResource
```

### 5b. Watch the external-name and conditions the controller wrote

Apply the nop resource from Course 2 and describe it:

```bash
kubectl apply -f manifests/course-02/nopresource.yaml
kubectl describe nopresource.nop.crossplane.io   # pick the name it created
```

Look for:

- `metadata.annotations.crossplane.io/external-name` — written by `Create`
  (§3). This is the identity link.
- `status.conditions` — `Synced` (did `Observe`/`Create`/`Update` succeed?) and
  `Ready` (does the external resource report healthy?). The generic reconciler
  sets these from your methods' return values — you never write condition code
  yourself.

### 5c. (Optional) scaffold a provider — commands as reference

If you have Go and want to see the stubs you'd fill in:

```bash
# Reference only — scaffolds a new provider skeleton from the template.
git clone https://github.com/crossplane/provider-template provider-toy
cd provider-toy
# The ExternalClient stubs live under internal/controller/<kind>/ —
# open them and you'll find Observe/Create/Update/Delete waiting for your code.
```

You'll recognize the exact signatures from §3, with `// TODO` where your toy-API
calls go.

---

## 6. Peek under the hood: it's the reconcile loop you already know

Strip away the names and a provider is `myk8scourses` Course 12's operator:

```
for each MR, forever:
    client = Connect(providerconfig)          # build external API client
    obs = Observe(mr)                          # look at the real world
    if !obs.ResourceExists:   Create(mr)       # make it
    elif !obs.ResourceUpToDate: Update(mr)     # fix it
    if mr.beingDeleted:       Delete(mr)       # (finalizer-gated)
    set conditions; requeue after interval     # heartbeat
```

Two properties make it robust, both from the Course 2 reconcile principles:

- **Level-triggered** — it acts on the *current* observed state, not on events.
  Miss an event, crash, restart — the next `Observe` still sees reality and
  corrects it. This is what gives external resources the *heartbeat* that
  Terraform's one-shot `apply` lacked (Pain #4).
- **Idempotent** — `Create` is only called when `Observe` says the thing is
  absent, so re-running the loop never double-creates. Your `ExternalClient`
  methods must be safe to call repeatedly.

> ⚠️ **The most common provider bug is a non-idempotent or wrong `Observe`.** If
> `Observe` wrongly reports `ResourceExists: false`, the reconciler calls
> `Create` again and you leak a duplicate external resource. The loop is only as
> correct as your `Observe`.

---

## 7. Break it on purpose: simulate a slow Create with nop

`provider-nop` can fake timing so you can *watch* the loop lag — exactly the kind
of experiment you can't safely run against a real cloud. Use its `conditionAfter`
to delay readiness:

```yaml
apiVersion: nop.crossplane.io/v1alpha1
kind: NopResource
metadata:
  name: slow-create
spec:
  forProvider:
    conditionAfter:
      - time: 30s
        conditionType: Ready
        conditionStatus: "True"      # pretend the external Create takes 30s to become Ready
```

```bash
kubectl apply -f - <<'EOF'
# (the YAML above)
EOF

watch kubectl get nopresource slow-create
```

For ~30 seconds the resource is `Synced=True` but `Ready=False` — the reconciler
successfully "created" it, but the external thing isn't healthy yet, so `Ready`
lags. That gap between *created* and *ready* is real on every cloud (a database
takes minutes to provision), and it's exactly why `function-auto-ready` and the
`Ready` condition exist. The loop keeps re-observing until reality catches up.

---

## 8. Scorecard update

| # | Course 0 pain | Status after Course 12 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ the MR is desired state; the provider enforces it |
| 2 | No self-service API | ✅ (Track A) |
| 3 | **Two worlds (cluster vs cloud)** | ✅ **you now see the bridge: the ExternalClient** |
| 4 | **No continuous reconciliation of external state** | ✅ **the loop you can now implement yourself** |
| 5 | Platform not installable | ✅ Course 10 |

Pains #3 and #4 aren't just *used* now — they're *understood*. You could write
the controller that fixes them.

---

## 9. Takeaway

A provider is a managed-resource CRD plus crossplane-runtime's `managed.Reconciler`
calling your `ExternalClient` — five methods: `Connect` builds the client from
the ProviderConfig, and `Observe/Create/Update/Delete` translate the universal
reconcile verbs into one external API's dialect. The external-name annotation
links MR to reality, connection details flow out as Secrets, and
`managementPolicies` gate which verbs run. `provider-nop` and
`provider-kubernetes` are the same shape with different backends, and Upjet mints
whole providers from Terraform schemas. Underneath it all is the level-triggered,
idempotent loop from `myk8scourses` Course 12 — pointed at someone else's API.

### Cleanup

```bash
kubectl delete nopresource slow-create --ignore-not-found
kubectl delete -f manifests/course-02/nopresource.yaml --ignore-not-found
# If you cloned the template:  rm -rf provider-toy
```

**Next:** [Course 13 — Production Hardening](./course-13-production-hardening.md),
the capstone: lock down RBAC, pin runtime pods, enforce deletion ordering, secure
image pulls, add observability and GitOps, and ship the whole SnippyStack control
plane for real.
