# Course 5 — Claims, Namespaced XRs & Self-Service

> **Goal:** Hand the `App` API to a real developer — safely. In Crossplane **v2**
> XRs are namespaced, so plain Kubernetes RBAC is all you need to confine a dev
> to their own namespace while the platform team keeps ownership of the XRD and
> Composition. You'll also meet the **v1 claim model** (XRC) you no longer need,
> so you can read and migrate older codebases.

**You need:** the cluster from Course 4 with the `App` XRD, Composition, and
functions installed, plus `kubectl` with permission to create namespaces, Roles,
and RoleBindings.

**Time:** ~45 min.

---

## 1. Recap the pain

Course 4 got you a configurable, self-describing `App` API — a genuine
self-service abstraction. But look where everything lived: `default`, with you
applying it as a cluster admin. That's not self-service; that's *you* still being
the ticket queue, just with nicer YAML. If you hand `kubectl` to ten developers
as-is, every one of them can read every other team's Apps, edit the Composition,
and generally stomp around the whole cluster. The abstraction is good; the
**blast radius** is terrifying.

The promise from Course 0 was *"let them self-serve, don't become a ticket
queue"* — and that only works if a developer can safely do their thing without
being able to break everyone else's. Today you draw those fences.

---

## 2. The concept: namespaced XRs make RBAC trivial

Here is the quietly revolutionary **v1→v2 change** that this whole course rests
on:

> 🧠 **In Crossplane v2, a Composite Resource is namespaced.** An `App` lives in
> a namespace, exactly like a Deployment or a ConfigMap. That means ordinary
> Kubernetes RBAC — the same Roles and RoleBindings you learned in
> `myk8scourses` — is enough to confine a developer to their namespace. No
> special Crossplane permission model required.

Your Course 3 XRD already opted into this with one line:

```yaml
spec:
  scope: Namespaced   # v2 style — the App is a namespaced object
```

The division of labor falls out naturally:

- **Platform team (you)** owns the cluster-scoped machinery: the **XRD** (the API
  schema) and the **Composition** (its implementation). Developers never touch
  these.
- **Developers** own only the small, namespaced surface you exposed: the `App`
  object itself, in their own namespace.

That's the entire self-service story in v2 — the same mental model as handing a
team a namespace and letting them run Deployments in it.

---

## 3. Lab: give Alice a namespace she can't escape

Open [`manifests/course-05/self-service.yaml`](../manifests/course-05/self-service.yaml).
It bundles four objects: a `Namespace` `team-a`, a `Role` `app-developer`, a
`RoleBinding` to the user `dev-alice`, and one `App` (`alice-snippy`) in
`team-a`.

```bash
kubectl apply -f manifests/course-05/self-service.yaml
```

### Read the Role rule by rule

```yaml
rules:
  - apiGroups: ["platform.snippy.io"]
    resources: ["apps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services", "configmaps", "pods"]
    verbs: ["get", "list", "watch"]
```

- Rule 1 — full lifecycle control over **Apps**, but only `apps.platform.snippy.io`
  and only in `team-a` (it's a `Role`, so it's namespace-scoped). This is the
  developer's real power: create and manage their own environments.
- Rule 2 & 3 — **read-only** visibility into what an App composes (Deployments,
  Services, ConfigMaps, Pods). Alice can *see* her Deployment and *watch* her
  Pods, but can't create or edit them directly — the Composition owns those.

> 🧠 **Alice gets a verb-rich grant on the abstraction and a read-only grant on
> the primitives.** That's the self-service contract in one Role: she drives the
> high-level API; the control plane drives the low-level resources on her behalf.

### Prove the fence holds with `kubectl auth can-i`

You don't need to log in as Alice to test her permissions — impersonate her:

```bash
kubectl auth can-i create apps.platform.snippy.io -n team-a --as dev-alice
# yes

kubectl auth can-i create apps.platform.snippy.io -n default --as dev-alice
# no

kubectl auth can-i create deployments -n team-a --as dev-alice
# no  (she can only read them)
```

Yes in her namespace, no everywhere else, and no direct Deployment creation. The
fence is exactly as tall as you drew it.

### See the composed resources land in `team-a`

The `alice-snippy` App in the manifest triggers the Composition in **her**
namespace. Because v2 XRs are namespaced, the composed ConfigMap, Deployment, and
Service land right alongside it:

```bash
kubectl get app,deploy,svc,configmap -n team-a
```

Everything Alice asked for, confined to Alice's namespace, created by the control
plane — not by Alice directly.

---

## 4. Contrast: the v1 claim model you no longer need

Before v2, this was *much* harder, and the awkwardness explains a lot of older
Crossplane docs. Open
[`manifests/course-05/legacy-claim-example.yaml`](../manifests/course-05/legacy-claim-example.yaml)
— **reference only, do not apply it next to the namespaced App**.

In v1, XRs were **cluster-scoped**. Since you can't safely hand developers
cluster-scoped objects, Crossplane introduced a second type — a **Claim** (XRC) —
that *was* namespaced. A developer created a namespaced `AppClaim`; Crossplane
generated and bound a matching cluster-scoped `XApp`. The XRD opted into this
split with `scope: LegacyCluster` and `claimNames`:

```yaml
spec:
  scope: LegacyCluster     # cluster-scoped XR + a namespaced claim
  names:
    kind: XApp             # the cluster-scoped composite
    plural: xapps
  claimNames:
    kind: AppClaim         # the namespaced claim developers created
    plural: appclaims
```

So every logical "app" was really **two objects** — a namespaced `AppClaim` the
developer saw and a cluster-scoped `XApp` the engine managed — kept in sync by
Crossplane. It worked, but it meant two kinds, two names, confusing `kubectl get`
output, and a model that didn't look like anything else in Kubernetes.

> 🧠 **v2 collapsed the split.** The XR is simply namespaced, so there's no need
> for a separate claim type at all. One kind (`App`), one object, in the
> developer's namespace, governed by vanilla RBAC. If you see `scope:
> LegacyCluster`, `claimNames`, or an `XSomething`/`SomethingClaim` pair in a
> codebase, you're reading **v1** — and you now know what it was working around.

> ⚠️ **One more v2 change to know: connection details.** In v1, an XR's
> connection secret was auto-managed by Crossplane. In v2, connection secrets are
> produced by the **composed resources** (surfaced through the pipeline), not
> auto-managed on the XR. If you're migrating, don't expect the old automatic XR
> connection secret — wire it through composition instead.

---

## 5. Break it on purpose

Try to do things Alice shouldn't be able to do, as Alice:

```bash
# Create an App outside her namespace — denied.
kubectl apply --as dev-alice -f - <<'EOF'
apiVersion: platform.snippy.io/v1alpha1
kind: App
metadata:
  name: sneaky
  namespace: default
spec:
  image: snippy:0.1
EOF
# Error from server (Forbidden): ... cannot create resource "apps" in namespace "default"

# Peek at the platform team's Composition — denied.
kubectl get composition --as dev-alice
# Error from server (Forbidden): ... "dev-alice" cannot list resource "compositions"

# Edit a Deployment directly in her own namespace — denied (read-only).
kubectl scale deploy alice-snippy -n team-a --replicas=9 --as dev-alice
# Error from server (Forbidden): ... cannot patch resource "deployments"
```

Three attempts, three `Forbidden`s — and crucially, Alice can still do her actual
job (create and tune Apps in `team-a`). She wants more replicas? She edits her
**App**, not the Deployment:

```bash
kubectl patch app alice-snippy -n team-a --type merge \
  -p '{"spec":{"replicas":9}}' --as dev-alice   # allowed — it's her App
```

The control plane then scales the Deployment on her behalf. Self-service with
guardrails, exactly as promised.

---

## 6. Scorecard update

Developers now have a safe, confined, self-service API — the platform team owns
the implementation, devs own only their namespaced `App`. Pains #1 and #2 are
fully put to bed.

| # | Course 0 pain | Status after Course 5 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ **solved** — each App is the git-backed source for its env |
| 2 | No self-service abstraction | ✅ **solved** — namespaced `App` + RBAC = safe self-service |
| 3 | Two worlds (cluster vs cloud) | ⏭️ Course 7 (providers reconcile external state) |
| 4 | No continuous reconciliation of external state | ⏭️ Course 7 |
| 5 | Platform not installable | ⏭️ Course 10 (Configuration packages) |

---

## 7. Takeaway

Self-service in Crossplane v2 is almost anticlimactic, and that's the point:
because XRs are **namespaced**, you confine developers with the *exact same* RBAC
you already know from `myk8scourses` — a `Role` on `apps.platform.snippy.io` in
their namespace, read-only on the primitives, nothing cluster-wide. The platform
team keeps the XRD and Composition; developers get a small, safe surface. The v1
**claim** model existed only to work around cluster-scoped XRs, and v2 deleted
that complexity entirely. Your platform is now something you can genuinely hand
to other teams.

### Cleanup

```bash
kubectl delete -f manifests/course-05/self-service.yaml
# This removes team-a (and the alice-snippy App + its composed resources with it).
```

**Next:** [Course 6 — Anatomy of a Control Plane](./course-06-anatomy-of-a-control-plane.md),
where you open the hood and tour every pod and object in the control plane you've
been building — and discover it's just more Kubernetes.
