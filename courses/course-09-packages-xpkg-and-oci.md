# Course 9 — Packages, xpkg & OCI

> **Goal:** Open the box. Providers, functions, and configurations all arrive as
> `Provider`/`Function`/`Configuration` objects you've been applying on faith —
> but underneath, each is just an **OCI image** (an "xpkg") that the package
> manager pulls and reconciles into running controllers. By the end you'll know
> what's inside an xpkg, why every install spawns a `*Revision`, and why upgrades
> are safe and rollbackable — the OCI/revision model mapped onto the
> ReplicaSet/rollout model from `myk8scourses`.

**You need:** the cluster from the previous courses with at least
provider-kubernetes and the two functions installed, plus `kubectl`, the
`crossplane` CLI, and (optionally) `docker`.

**Time:** ~45 min.

---

## 1. Recap the pain

Across Courses 2–4 you ran `kubectl apply` on `Provider`, `Function`, and (soon)
`Configuration` objects, and controllers and CRDs just... appeared. You've been
installing software into your cluster from a one-line `package:` reference
without ever asking what that reference *is* or what unpacking it actually does.

That's fine until something breaks in production — a bad provider version, a
stuck upgrade, a dependency conflict — and you have no mental model of the
machinery. Today we open the box so Course 10 (building your own package) and
Course 13 (hardening) have solid ground to stand on.

---

## 2. The concept: an xpkg is an OCI image

A Crossplane package (`.xpkg`) is a plain **OCI image** — the same artifact
format as a Docker container image, livable in any OCI registry. Its layers
carry:

- **Package contents** as YAML: for a Provider, the CRDs it introduces; for a
  Configuration, your XRDs + Compositions; for a Function, its metadata.
- **`crossplane.yaml`** — the package's metadata object (`kind: Provider` /
  `Function` / `Configuration` under `meta.pkg.crossplane.io`), declaring its
  name, the minimum Crossplane version, and its `dependsOn` list. You've already
  seen two real ones:

```bash
cat configuration/crossplane.yaml                    # kind: Configuration + dependsOn functions
cat functions/snippy-app/package/crossplane.yaml     # kind: Function metadata
```

- For **providers and functions**, a reference to a **runtime image** — the
  actual controller/gRPC-server binary that will run as a pod.

So a Configuration package is "pure YAML in an OCI image," while a Provider or
Function package is "YAML + a pointer to a runtime image to run."

### What the package manager does

The **package manager** lives in the crossplane core pod. When you create a
`Provider` / `Function` / `Configuration` object, it runs a reconcile loop (yes,
again) that:

```
1. PULL the OCI image named in spec.package
2. CREATE a *Revision object:
     Provider      -> ProviderRevision
     Function      -> FunctionRevision
     Configuration -> ConfigurationRevision
3. INSTALL the YAML the image carries (CRDs, XRDs, Compositions)
4. For providers/functions: CREATE the controller/gRPC Deployment
   from the runtime image
5. RESOLVE dependencies declared in crossplane.yaml (dependsOn),
   recording them in the cluster-wide Lock
```

> 🧠 **Installing an extension is "pull an OCI image and reconcile it into
> controllers."** There is no magic installer and no package database on disk —
> it's the same observe-diff-act loop you've seen all series, where the desired
> state is "this package, at this version, is installed" and the real world is
> "these CRDs exist and this controller pod is running."

---

## 3. Lab: open the box

### See the revisions

The top-level `Provider`/`Function`/`Configuration` object is a stable *name*;
the `*Revision` is a specific *version* that's actually installed:

```bash
kubectl get provider,function,configuration
kubectl get providerrevision,functionrevision,configurationrevision
```

Note how each revision name ends in a hash — that's the resolved image digest.
Describe one to see the CRDs it owns and its health:

```bash
kubectl describe functionrevision \
  "$(kubectl get functionrevision -o name | grep auto-ready | head -1)"
```

### Read the dependency Lock

Every package's `dependsOn` edges are recorded in one cluster-wide object:

```bash
kubectl get lock.pkg.crossplane.io lock -o yaml
```

The `Lock` lists every installed package, its resolved version, and its
dependencies. It's how the package manager detects conflicts (two packages
demanding incompatible versions of a shared function) *before* installing them.

### Revision policies

Two knobs on the `Provider`/`Function`/`Configuration` spec govern revisions:

- **`revisionActivationPolicy`** — `Automatic` (default) activates a newly
  pulled revision immediately; `Manual` installs it but leaves it `Inactive`
  until you flip it, so you can stage an upgrade and cut over deliberately.
- **`revisionHistoryLimit`** — how many old, inactive revisions to retain for
  rollback (default 1). Exactly like a Deployment's `revisionHistoryLimit`.

```bash
kubectl get provider provider-kubernetes -o jsonpath='{.spec.revisionActivationPolicy}{"\n"}'
kubectl get provider provider-kubernetes -o jsonpath='{.spec.revisionHistoryLimit}{"\n"}'
```

### Inspect an image's layers

An xpkg is an OCI image, so ordinary image tools can crack it open. The
`crossplane` CLI knows the format directly:

```bash
# Pull an xpkg to your local store and inspect what's inside it:
crossplane xpkg extract --help     # explore the package-inspection subcommands
```

Conceptually, with Docker you can see it's nothing but tarred layers:

```bash
# (illustrative) a function package is a normal OCI image:
docker pull xpkg.crossplane.io/crossplane-contrib/function-auto-ready:v0.4.1
docker save xpkg.crossplane.io/crossplane-contrib/function-auto-ready:v0.4.1 \
  | tar tf -        # lists the image's layer tarballs — standard OCI, no magic
```

Inside those layers you'd find the `crossplane.yaml` metadata and the package's
YAML; the image config points at the runtime binary the controller Deployment
runs.

### Dependency resolution (foreshadowing Course 10)

Look again at `configuration/crossplane.yaml` — its `dependsOn` lists
`function-patch-and-transform` and `function-auto-ready`. When you install that
Configuration in Course 10, you will **not** install those functions by hand:
the package manager reads `dependsOn`, pulls each dependency as its own package,
and records the edges in the `Lock`. Installing one package can cascade into
several.

> 🧠 **A Configuration ships APIs, not implementations.** It carries your XRDs
> and Compositions and *declares* the functions they need; the package manager
> fetches those functions automatically. That's what makes a platform a single
> installable product (Course 0's Pain #5).

---

## 4. Peek under the hood

- **Everything is OCI, all the way down.** Providers, functions, and
  configurations share one artifact format and one registry story with your app
  images. Your platform's distribution problem becomes "push an image, pin a
  tag" — tooling you already own.
- **Revisions make upgrades safe and rollbackable.** Changing a package's
  `spec.package` tag makes the package manager pull a new image and create a new
  `*Revision`; the old revision lingers (up to `revisionHistoryLimit`) so you can
  revert. This is **exactly** the Deployment → ReplicaSet relationship from
  `myk8scourses` Course 2: the stable object (Deployment / Provider) points at an
  immutable snapshot (ReplicaSet / *Revision), and rollout/rollback is just
  switching which snapshot is active.
- **The package manager is just another controller.** It reconciles `Provider`/
  `Function`/`Configuration` desired state into pulled images, installed CRDs,
  and running Deployments — the same loop shape as every other course.
- **v1 vs v2 note.** Functions-as-packages are central in v2 because functions
  are mandatory (Course 8); in v1 you could run a Composition with no function
  packages at all. The package *mechanism*, though, is unchanged across versions.

---

## 5. Break it on purpose

### Break A: delete a revision and watch it respawn

```bash
# Pick a provider revision:
REV=$(kubectl get providerrevision -o name | head -1)
kubectl delete $REV

# The package manager notices the desired Provider still wants it, and recreates it:
kubectl get providerrevision -w
#   a fresh revision reappears within seconds
```

The top-level `Provider` object is desired state; deleting its revision is drift,
and the loop heals it — just like deleting a Pod under a Deployment.

### Break B: pin, then bump, a version

```bash
# Watch the current revision set:
kubectl get functionrevision

# Bump function-auto-ready to a different patch (adjust to a real tag):
kubectl patch function function-auto-ready --type merge \
  -p '{"spec":{"package":"xpkg.crossplane.io/crossplane-contrib/function-auto-ready:v0.4.1"}}'

# A new FunctionRevision appears for the new digest; the old one goes Inactive
# (retained per revisionHistoryLimit) instead of vanishing:
kubectl get functionrevision
```

You'll see the new revision become `Active` and `Healthy`, the previous one
retained as a rollback target — a rollout, modeled as objects you can inspect
with `kubectl get`.

> ⚠️ **Deleting the top-level object is different from deleting a revision.**
> Removing a revision is self-healing drift; removing the `Provider`/`Function`/
> `Configuration` itself is a real uninstall — it tears down the revisions, their
> CRDs, and the controller Deployment. Mind which one you're deleting in a shared
> cluster.

---

## 6. Scorecard update

| # | Course 0 pain | Status after Course 9 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ a pinned image tag per package *is* the source |
| 2 | No self-service API | ✅ Courses 3–5 + delivered as packages |
| 3 | Two worlds (cluster vs cloud) | ✅ providers packaged like everything else |
| 4 | No continuous reconciliation of external state | ✅ Course 7 |
| 5 | **Platform not installable** | 🔜 the mechanism is now clear — Course 10 builds one |

The last pain, #5, is one step from solved: you now understand the *format* and
the *installer*; Course 10 packages the SnippyStack platform into one.

---

## 7. Takeaway

Providers, functions, and configurations are all **OCI images** (xpkgs) whose
layers carry package YAML plus a `crossplane.yaml` metadata object — and, for
providers and functions, a reference to a runtime image. The package manager, a
controller in the core pod, reconciles each `Provider`/`Function`/`Configuration`
object by pulling the image, creating an immutable `*Revision`, installing the
CRDs/XRDs/Compositions it carries, and (for providers/functions) starting a
controller Deployment — resolving `dependsOn` dependencies into the cluster-wide
`Lock` along the way. Revisions give you safe, rollbackable upgrades, exactly as
ReplicaSets do for Deployments in `myk8scourses`. Installing a Crossplane
extension is nothing more exotic than "pull an image and reconcile it into
controllers."

**Next:** [Course 10 — Build a Configuration Package](./course-10-build-a-configuration-package.md),
where you turn the SnippyStack API into a versioned xpkg and finally cross off
Pain #5.
