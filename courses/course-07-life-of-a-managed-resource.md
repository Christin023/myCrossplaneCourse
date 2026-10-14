# Course 7 — Life of a Managed Resource

> **Goal:** Stop treating the provider as magic. Trace a single **Managed
> Resource** end-to-end through the reconcile loop every Crossplane provider
> runs, and master the two levers that control that loop: `managementPolicies`
> and `deletionPolicy`. By the end you'll be able to *import* existing
> infrastructure read-only, keep an external object alive after deleting its MR,
> and explain exactly why drift gets corrected (or doesn't).

**You need:** the cluster from Course 2 with **provider-kubernetes** installed
and its `default` ProviderConfig applied, plus `kubectl` and the `crossplane`
CLI. This is Track B — we mostly *inspect* and reason; the only new manifests
live in `manifests/course-07/`.

**Time:** ~45 min.

---

## 1. Recap the pain

In Course 2 you installed a provider, created an `Object` Managed Resource, and
watched a real ConfigMap appear — then watched it *heal* when you edited it by
hand. It felt like magic. You left with a nagging question: *what is the
controller actually doing on every tick, and how do I tell it to back off when I
don't want it bulldozing an existing resource?*

That nagging question is Course 0's **Pain #4** — "no continuous reconciliation
of external state" — and today we finish it off. We're going to open the loop,
name every verb inside it, and then bend the loop to our will.

---

## 2. The ExternalClient contract: Observe → Create / Update / Delete

Every Crossplane provider — AWS, GCP, Azure, provider-kubernetes, the
teaching provider-nop — implements the *same* tiny interface. In Go it's called
the **`ExternalClient`**, and it has four methods:

```
Observe(mr)  -> { ResourceExists, ResourceUpToDate, ConnectionDetails }
Create(mr)   -> make the external object; record its identity
Update(mr)   -> reconcile the external object back to spec.forProvider
Delete(mr)   -> remove the external object
```

That's the whole contract. `crossplane-runtime`'s **`managed.Reconciler`**
wraps those four methods in a loop and runs it for *every* MR of *every*
provider. The loop, in pseudocode:

```
on every reconcile tick for a Managed Resource mr:
    observation = Observe(mr)

    if mr is being deleted (deletionTimestamp set):
        if deletionPolicy == Delete and "Delete" allowed:
            Delete(mr)
        remove finalizer   # let Kubernetes GC the MR object
        return

    if not observation.ResourceExists:
        if "Create" allowed:
            Create(mr)
        return

    if not observation.ResourceUpToDate:
        if "Update" allowed:
            Update(mr)
        return

    # exists and matches desired state: nothing to do
    writeConnectionDetails(observation.ConnectionDetails)
    setCondition(Synced=True, Ready=True)
```

> 🧠 **You have seen this loop before.** This is the exact shape of the Kopf
> operator you built by hand in `myk8scourses` Course 12, and the self-healing
> reconcile heartbeat from its Course 2. Observe → diff → act, forever. Crossplane
> didn't invent a new idea; it standardized the loop so every provider author
> fills in only the four verbs and gets the loop for free.

### The external-name bridge

An MR is a Kubernetes object with a `metadata.name` (e.g. `snippy-greeting`).
The external system has its *own* idea of identity (a ConfigMap named
`snippy-greeting`, an S3 bucket named `acme-logs-7f3a`, an RDS instance ARN).
The link between the two is the annotation:

```
crossplane.io/external-name: <the external system's real identifier>
```

On `Create`, the provider stamps this annotation with whatever the external API
calls the thing. On every later `Observe`, the provider reads the annotation to
know *which* external object to go look at. If you set it yourself **before**
creation, you're telling the provider "this is the name to use" — which is how
you adopt pre-existing objects (we do this below).

### Connection details and the two conditions

- **Connection details** — on `Observe`/`Create`, a provider can emit secrets
  (endpoints, passwords, kubeconfigs) which Crossplane writes into a Kubernetes
  `Secret`. Downstream resources consume them.
- **`Synced`** — "the controller successfully ran the loop and reconciled the
  external API." A reconcile error flips `Synced=False`.
- **`Ready`** — "the external object actually exists and is usable." A database
  can be `Synced=True` (we issued the create) but `Ready=False` (still
  provisioning).

```bash
kubectl get object snippy-greeting -o json \
  | jq '.status.conditions'
```

---

## 3. Lab: the two levers

Both levers live on the MR's `spec`. Read the comments in the manifest — they
spell out every option:

```bash
cat manifests/course-07/management-and-deletion-policies.yaml
kubectl apply -f manifests/course-07/management-and-deletion-policies.yaml
```

This applies two `Object` MRs (kind `Object`, apiVersion
`kubernetes.crossplane.io/v1alpha2`):

- `orphan-demo` with `deletionPolicy: Orphan`
- `partial-mgmt-demo` with `managementPolicies: ["Observe","Create","Update"]`

### Lever 1 — `deletionPolicy: Orphan`

`deletionPolicy` answers one question: *when I delete the MR, what happens to the
external object?* `Delete` (the default) tears it down; `Orphan` leaves it
behind and simply forgets about it.

```bash
# The provider created a real ConfigMap named orphan-demo:
kubectl get configmap orphan-demo

# Delete the Managed Resource...
kubectl delete object orphan-demo

# ...and the ConfigMap is still there, now unmanaged:
kubectl get configmap orphan-demo        # STILL EXISTS 🎉
```

> 🧠 **Orphan is your "detach, don't destroy" button.** Decommissioning a
> platform? Flip MRs to `Orphan`, delete them, and the real cloud resources keep
> serving traffic while Crossplane steps away. The reverse of the import you'll
> do below.

### Lever 2 — `managementPolicies` without `Delete`

`managementPolicies` is the finer-grained lever: it lists *which of the four
verbs* the provider may perform. `["*"]` is full control (the default).
`partial-mgmt-demo` uses `["Observe","Create","Update"]` — manage it fully, but
**never delete the external object**, even if the MR's `deletionPolicy` says
`Delete`.

```bash
kubectl get configmap partial-mgmt-demo        # created ✅
kubectl delete object partial-mgmt-demo
kubectl get configmap partial-mgmt-demo        # STILL EXISTS — Delete was withheld
```

Same visible outcome as Orphan, different mechanism: Orphan is about the deletion
*moment*; `managementPolicies` is a standing statement of authority across the
whole lifecycle.

### Lever 3 — observe-only import

The most powerful move: adopt an object the provider did **not** create, and
promise never to touch it. First make something out-of-band, then import it:

```bash
# Create a ConfigMap behind Crossplane's back:
kubectl create configmap preexisting --from-literal=owner=someone-else

# Import it read-only (managementPolicies: ["Observe"]):
cat manifests/course-07/observe-only.yaml
kubectl apply -f manifests/course-07/observe-only.yaml

# The MR finds and reports it...
kubectl get object observe-preexisting
kubectl describe object observe-preexisting | sed -n '/Status/,$p'

# ...but the real ConfigMap is untouched — owner is still someone-else:
kubectl get configmap preexisting -o jsonpath='{.data.owner}'; echo
```

With `["Observe"]` the loop runs `Observe` and then short-circuits: `Create`,
`Update`, and `Delete` are all forbidden. This is how you safely bring years of
click-ops infrastructure under a control plane *without* a single risky write —
a read-only mirror first, write access later.

> ⚠️ **Observe-only never writes — not even the first time.** If the external
> object doesn't exist, an `["Observe"]` MR will sit `Synced=False` forever
> rather than create it. That's the point: it's a mirror, not a manager.

---

## 4. Peek under the hood

- **Four verbs = CRUD on the external API.** `Create`/`Observe`/`Update`/`Delete`
  map one-to-one onto POST/GET/PUT/DELETE of whatever API the provider wraps —
  the AWS SDK, the Kubernetes API, a database's admin API. The *loop* is
  identical everywhere; only the four verb implementations differ per resource.
- **Level-triggered, not edge-triggered.** The loop never says "a change
  happened, do X." It says "here is the *current* desired state and the *current*
  observed state — make them match." That's why it's **idempotent**: running
  `Observe`→`Update` ten times converges to the same result, and a missed event
  is harmless because the next tick re-observes everything from scratch.
- **One reconciler to rule them all.** `managed.Reconciler` in
  `crossplane-runtime` owns requeuing, finalizers, the external-name annotation,
  connection-secret writing, and condition-setting. A provider author implements
  `ExternalClient` and *nothing else* about the loop. This is why a brand-new
  provider behaves exactly like provider-aws on day one.
- **Finalizers gate deletion.** The MR carries a finalizer so that deleting the
  Kubernetes object doesn't vanish before the provider gets a chance to run
  `Delete` (or deliberately skip it, per the policies above).

```bash
# Watch the loop's bookkeeping on a live MR:
kubectl get object snippy-greeting -o yaml | sed -n '/metadata:/,/spec:/p'
#   look for: finalizers, crossplane.io/external-name annotation
```

---

## 5. Break it on purpose

### Break A: hand-edit an observed-only resource

```bash
kubectl patch configmap preexisting --type merge \
  -p '{"data":{"owner":"i-changed-this"}}'

# Give the provider a few reconcile ticks, then look:
sleep 15
kubectl get configmap preexisting -o jsonpath='{.data.owner}'; echo
#   -> i-changed-this   (the provider left it ALONE; Update is forbidden)
```

Contrast with Course 2's fully-managed `snippy-greeting`, where the same edit got
reverted within seconds. Same provider, same loop — the only difference is the
`managementPolicies` lever.

### Break B: remove `Update` and watch drift stop being corrected

Take a fully-managed resource and strip its authority to update:

```bash
# snippy-greeting from Course 2 is fully managed. Remove Update:
kubectl patch object snippy-greeting --type merge \
  -p '{"spec":{"managementPolicies":["Observe","Create","Delete"]}}'

# Now drift the real ConfigMap by hand:
kubectl patch configmap snippy-greeting --type merge \
  -p '{"data":{"greeting":"drifted!"}}'

sleep 15
kubectl get configmap snippy-greeting -o jsonpath='{.data.greeting}'; echo
#   -> drifted!   (NOT corrected — the provider may Observe the drift but cannot Update)
```

The MR will happily report that it *sees* the mismatch, but with `Update`
withheld it has no authority to fix it. Restore full control to re-enable
self-healing:

```bash
kubectl patch object snippy-greeting --type merge \
  -p '{"spec":{"managementPolicies":["*"]}}'
sleep 15
kubectl get configmap snippy-greeting -o jsonpath='{.data.greeting}'; echo
#   -> back to the managed value
```

> 🧠 **Reconciliation is a *delegated authority*, not a law of physics.** The
> loop corrects drift only for the verbs you grant. `managementPolicies` is how
> you dial that authority from "read-only mirror" all the way to "total owner,"
> per resource.

---

## 6. Scorecard update

| # | Course 0 pain | Status after Course 7 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ MR spec in etcd is the source; loop enforces it |
| 2 | No self-service API | ✅ Courses 3–5 (XRDs, Compositions, namespaced XRs) |
| 3 | Two worlds (cluster vs cloud) | ✅ one loop reconciles any external API |
| 4 | **No continuous reconciliation of external state** | ✅ **solved — the Observe→Create/Update/Delete heartbeat** |
| 5 | Platform not installable | ⏭️ Course 10 (Configuration packages) |

Pain #4 is now fully crossed off: you've seen the heartbeat, named its verbs, and
proved you can turn each one on and off.

---

## 7. Takeaway

A Managed Resource is a Kubernetes object plus a four-verb reconcile loop:
`Observe` decides existence and drift; `Create`/`Update`/`Delete` act. The
`crossplane.io/external-name` annotation bridges the MR's name to the external
object's real identity, connection details flow into a Secret, and `Synced`/
`Ready` tell you how the loop is going. Two levers steer the loop's authority —
`deletionPolicy` (what happens on delete) and `managementPolicies` (which verbs
are allowed) — letting you import read-only, orphan on teardown, or own
completely. It's the same observe-diff-act loop you already trust from Kubernetes,
pointed at the outside world.

### Cleanup

```bash
kubectl delete object partial-mgmt-demo observe-preexisting --ignore-not-found
kubectl delete configmap preexisting orphan-demo partial-mgmt-demo --ignore-not-found
```

**Next:** [Course 8 — The Composition Engine](./course-08-the-composition-engine.md),
where we zoom out from one MR to a whole `App` and trace it through the gRPC
function pipeline that computes it.
