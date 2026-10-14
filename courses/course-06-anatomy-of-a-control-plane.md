# Course 6 — Anatomy of a Control Plane

> **Goal:** Open the hood. You've been *using* Crossplane for five courses — now
> tour every pod and every object that makes it run, and discover the punchline
> of Track B: there's no magic. The composition engine, the package manager, the
> providers, the functions — all of it is **just more Kubernetes**. Every
> component is an ordinary client of the API server, and every capability is an
> API object you can `kubectl get`.

**You need:** the cluster from Course 5 with Crossplane v2, `provider-kubernetes`
and `provider-nop` installed (Course 2), the two functions (Course 3), and the
`App` XRD/Composition. No new manifests — today you **inspect what exists**.

**Time:** ~45 min.

---

## 1. Recap the pain

This isn't a pain course so much as a *curiosity* course. You've installed
Crossplane, added providers, defined an API, composed resources, and handed it
all to a developer. It works — and that can feel like magic, which is exactly the
dangerous moment. Magic you can't debug. If you don't know what's actually
running, the first time a provider pod crashes or reconciliation mysteriously
stops you'll be helpless.

So before Track B dissects the reconcile loop (Course 7) and the composition
engine (Course 8) in depth, let's take the full tour and name every moving part.
This mirrors `myk8scourses` Course 7 — *"Anatomy of a Cluster"* — where you
learned core Kubernetes is just an API server plus a handful of controllers that
are all clients of it. Crossplane is the same story, one layer up.

---

## 2. The pods: who is actually running?

```bash
kubectl get pods -n crossplane-system
```

You'll see roughly this cast (names will have random suffixes):

| Pod | What it is |
|---|---|
| `crossplane-...` | **The core.** Runs the **package manager** *and* the **composition engine** as controllers in one pod. |
| `crossplane-rbac-manager-...` | Watches new CRDs and grants Crossplane the RBAC to manage them. |
| `provider-kubernetes-...` | The `provider-kubernetes` controller (reconciles its `Object` MRs). |
| `provider-nop-...` | The `provider-nop` controller (reconciles `NopResource` MRs). |
| `function-patch-and-transform-...` | A gRPC server the composition engine calls to compute resources. |
| `function-auto-ready-...` | A gRPC server that decides when an XR is Ready. |

> 🧠 **Count the pods and notice what's *not* there.** There's no Crossplane
> database, no message bus, no hidden daemon. The core is one pod; providers and
> functions are their own pods. That's the entire backend.

---

## 3. The objects: every capability is an API resource

The pods above didn't appear by accident — each is the result of an API object
you (or a package) created. List them:

```bash
kubectl get providers,functions,configurations
```

- **Providers** — `provider-kubernetes`, `provider-nop`. Each is your *desired
  state* saying "this controller should exist."
- **Functions** — `function-patch-and-transform`, `function-auto-ready`.
- **Configurations** — none yet (you build one in Course 10).

Each installed package also has an active **revision**:

```bash
kubectl get providerrevision,functionrevision
```

> 🧠 **A `Provider` is desired state; a `ProviderRevision` is the specific
> version currently installed.** The package manager reconciles the former into
> the latter — pulls the OCI image, installs its CRDs, and creates the controller
> Deployment. Updating a package creates a *new* revision and swaps it in. You'll
> trace this whole flow in Course 9.

### The CRDs: your control plane's vocabulary

Every provider and XRD you installed added nouns to the API server:

```bash
kubectl get crds | grep -E 'snippy|kubernetes.crossplane|nop'
```

You'll see `apps.platform.snippy.io` (your XRD's doing), `objects.kubernetes.crossplane.io`
(from provider-kubernetes), and `nopresources.nop.crossplane.io` (from
provider-nop). These are the *same kind of CRD* you'd write by hand — Crossplane
didn't invent a new extension mechanism, it uses the one from `myk8scourses`
Course 11.

### The RBAC manager, explained

How does Crossplane get permission to manage a brand-new CRD like `App` the
instant your XRD creates it? The **RBAC manager**:

```bash
kubectl get clusterroles | grep crossplane
```

> 🧠 **The RBAC manager watches for new CRDs and auto-grants Crossplane access to
> them** by maintaining aggregated ClusterRoles. That's why your `App` XRD "just
> worked" without you writing a ClusterRole for it. (It's also why, back in
> Course 3, you *did* have to hand-grant access to **core** ConfigMaps and
> Services — those aren't Crossplane CRDs, so the RBAC manager leaves them alone.
> See `manifests/course-03/rbac-crossplane-aggregate.yaml`.)

---

## 4. Peek under the hood: controllers vs. Deployments

Two different mechanisms are at work, and telling them apart is the key insight:

```
┌─ crossplane (one pod) ──────────────────────┐
│  • package manager  (a controller)          │   creates ▼
│  • composition engine (a controller)        │
└──────────────────────────────────────────────┘
         creates / manages ▼
┌─────────────────────┐  ┌──────────────────────────┐
│ provider Deployments │  │ function Deployments      │
│ (provider-kubernetes,│  │ (patch-and-transform,     │
│  provider-nop)       │  │  auto-ready)              │
└─────────────────────┘  └──────────────────────────┘
```

- The **composition engine** and the **package manager** are *controllers inside
  the single core pod* — loops watching XRs and packages respectively.
- **Providers and functions are separate Deployments** that the package manager
  *created* when you applied those `Provider`/`Function` objects. Confirm it:

```bash
kubectl get deploy -n crossplane-system
```

Every provider and function has a normal Deployment with a ReplicaSet and Pods —
nothing special, nothing Crossplane-specific about how they're scheduled.

> 🧠 **Everything is a client of the API server; there are no hidden back
> channels.** The composition engine reads XRs and writes composed resources
> *through the API server*. Providers read their MRs *through the API server*.
> Functions are called by the engine over gRPC but return desired state that the
> engine applies *through the API server*. Just like core Kubernetes, the API
> server is the single source of truth and the only meeting point.

---

## 5. Break it on purpose

Because providers and functions are ordinary Deployments, they behave like
ordinary Deployments — prove it.

### Kill a provider pod; watch it come back

```bash
kubectl delete pod -n crossplane-system -l pkg.crossplane.io/provider=provider-kubernetes
kubectl get pods -n crossplane-system -w   # Ctrl-C after it's Running again
```

The Deployment's ReplicaSet notices a missing Pod and reschedules it — the same
self-healing you saw for Snippy in `myk8scourses`. A provider crash is just a Pod
crash.

### Scale the core to zero; watch reconciliation stop

```bash
kubectl -n crossplane-system scale deploy crossplane --replicas=0

# With the engine gone, changes to an App are NOT acted on:
kubectl patch app snippy-dev -n default --type merge -p '{"spec":{"replicas":7}}' 2>/dev/null || \
  echo "(apply an App first if you cleaned up; the point is the engine is down)"
kubectl get deploy -A | grep snippy    # the Deployment does NOT change to 7
```

> ⚠️ **With the core scaled to zero, the composition engine isn't running, so XRs
> stop reconciling.** The API objects still exist in etcd — your desired state is
> safe — but nothing is driving reality toward it. This is the control-plane
> equivalent of pausing the heartbeat.

Restore it:

```bash
kubectl -n crossplane-system scale deploy crossplane --replicas=1
kubectl -n crossplane-system rollout status deploy crossplane
# Now the pending App change converges — the engine catches up on reconcile.
```

The engine comes back, re-observes every XR, and converges the Deployment to its
declared state. Nothing was lost because, as always, the truth lived in the API
server — not in the pod.

---

## 6. Scorecard update

No new pains fall today — this is an internals tour — but understanding the
anatomy is what lets you *trust* the earlier wins and operate them in production.

| # | Course 0 pain | Status after Course 6 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ confirmed — it's the API server/etcd, nothing hidden |
| 2 | No self-service abstraction | ✅ solved (Course 4–5) |
| 3 | Two worlds (cluster vs cloud) | ⏭️ Course 7 (the provider reconcile loop) |
| 4 | No continuous reconciliation of external state | ⏭️ Course 7 |
| 5 | Platform not installable | ⏭️ Course 10 (packages) |

---

## 7. Takeaway

Crossplane is **more Kubernetes, not a sidecar system**. The core is a single pod
running two controllers — the package manager and the composition engine; every
provider and function is an ordinary Deployment that the package manager created;
every capability is a CRD or package object you can `kubectl get`; and the RBAC
manager quietly grants access to new CRDs so it all hangs together. There are no
hidden databases and no back channels — every component is a client of the one
API server, exactly like the cluster anatomy from `myk8scourses` Course 7. If you
can debug Kubernetes, you can debug Crossplane.

**Next:** [Course 7 — The Life of a Managed Resource](./course-07-life-of-a-managed-resource.md),
where you follow a single Managed Resource through the provider's reconcile loop —
`Observe → Create/Update/Delete` — and watch a controller keep an *external*
object matching your intent.
