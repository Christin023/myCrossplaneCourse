# Course 10 — Build a Configuration Package

> **Goal:** Take the SnippyStack API you've been editing as loose YAML — an XRD
> plus a Composition — and turn it into a **versioned, installable OCI package**:
> a Crossplane *Configuration*. By the end, standing up your entire platform on a
> brand-new cluster is one `kubectl apply` of a single `Configuration` resource,
> and Crossplane pulls in the functions it needs by itself.

**You need:** the cluster from the previous courses with Crossplane v2 installed,
the `crossplane` CLI, a container registry you can push to (or a local one), and
the repo's [`../configuration/`](../configuration/) directory.

**Time:** ~45 min.

---

## 1. Recap the pain

Through Track A you built a real platform: a `platform.snippy.io/App` API (the
XRD) and a Composition that fans it out into a ConfigMap, Deployment, and
Service. It works beautifully — on *your* laptop, in *this* cluster, applied in
*the right order*, as long as you remember to install the two functions first.

That's exactly **Pain #5** from Course 0: *your platform isn't a versioned,
installable product.* It's a folder of YAML and a tribal-knowledge install
order. A new region, a new team, a disaster-recovery cluster — each one means
"copy these files, apply the functions, then the XRD, then the Composition, hope
the versions match." That's the Terraform-module-copying misery we swore off.

Today we fix it. A Configuration package makes your platform a thing you
*install*, not a thing you *reassemble*.

---

## 2. The concept: a Configuration is your API, boxed and labeled

Course 9 introduced the Crossplane package model: capabilities ship as **OCI
images** (`.xpkg`). You've already installed two kinds — Providers and Functions.
A **Configuration** is the third kind, and it's the one *you* author:

| Package kind | Contains | Has a runtime pod? |
|--------------|----------|---------------------|
| Provider | MR CRDs + controller | ✅ yes |
| Function | gRPC server | ✅ yes |
| **Configuration** | **your XRDs + Compositions** | ❌ **no — pure API objects** |

A Configuration bundles two things:

1. **Your API definitions** — the XRD(s) and Composition(s) under `apis/`.
2. **A `crossplane.yaml`** metadata file declaring the package's name, the
   minimum Crossplane version, and — critically — a **`dependsOn`** list of the
   functions and providers your Compositions need.

That `dependsOn` list is the magic. When someone installs your Configuration, the
package manager reads it and **installs the dependencies automatically**. No more
"remember to apply `functions.yaml` first."

> 🧠 **A Configuration is the only package type with no runtime image.** It ships
> no controller and runs no pod. It is pure *desired API surface* — XRDs and
> Compositions — delivered as data. The package manager just installs those
> objects into the API server, the same objects you've been `kubectl apply`-ing
> by hand.

---

## 3. Walk through the real `crossplane.yaml`

Open [`../configuration/crossplane.yaml`](../configuration/crossplane.yaml):

```yaml
apiVersion: meta.pkg.crossplane.io/v1alpha1
kind: Configuration
metadata:
  name: snippystack
  annotations:
    meta.crossplane.io/maintainer: Platform Team
    meta.crossplane.io/source: github.com/example/snippystack
    meta.crossplane.io/description: |
      Self-service Snippy environments via a single platform.snippy.io/App API.
spec:
  crossplane:
    version: ">=v2.0.0"
  dependsOn:
    - function: xpkg.crossplane.io/crossplane-contrib/function-patch-and-transform
      version: ">=v0.8.0"
    - function: xpkg.crossplane.io/crossplane-contrib/function-auto-ready
      version: ">=v0.4.0"
```

Three things to notice:

- **`apiVersion: meta.pkg.crossplane.io/v1alpha1`** — this is *package metadata*,
  a different group from the `pkg.crossplane.io/v1` `Configuration` *resource*
  you'll apply to the cluster later. One describes the package; the other
  installs it. Don't confuse them.
- **`spec.crossplane.version: ">=v2.0.0"`** — your platform uses namespaced XRs
  and function pipelines, which only exist in v2. This gate makes the package
  manager refuse to install on a v1 cluster rather than fail mysteriously.
- **`spec.dependsOn`** — the two functions your Composition's pipeline references
  (`function-patch-and-transform` and `function-auto-ready`, exactly the ones in
  `manifests/course-03/functions.yaml`). The package manager will pull and
  install these for the consumer.

The actual API lives next to it in
[`../configuration/apis/`](../configuration/apis/): `xrd.yaml` (the `App`
definition, `scope: Namespaced`) and `composition.yaml` (the pipeline). These are
byte-for-byte the files you've been applying — nothing new to write.

> ⚠️ **v1 → v2:** In v1, Configurations commonly depended only on providers,
> because Compositions used native patch-and-transform. In v2, **functions are
> mandatory** — every Composition is a function pipeline — so a real-world
> Configuration almost always `dependsOn` at least one function. If you forget to
> list them, installs on a fresh cluster fail because the pipeline references a
> function that isn't there.

---

## 4. Lab: build, push, install

### 4a. Build the package

`crossplane xpkg build` bundles `crossplane.yaml` plus everything under the
package root into a single `.xpkg` OCI artifact.

```bash
cd configuration

# Build. By default it reads ./crossplane.yaml and bundles the YAML it finds
# (the apis/ directory). The result is a .xpkg file in the current directory.
crossplane xpkg build

ls *.xpkg        # e.g. snippystack-<hash>.xpkg
```

> 🧠 **The build is deterministic and offline.** Because a Configuration has no
> runtime image, building it is just packaging YAML into an OCI layer — no Docker
> daemon, no compile step. Compare this to Course 11, where a *function* package
> must embed a runtime image.

### 4b. Push it to a registry

Tag it with a registry reference and a **semantic version** — versioning is the
whole point.

```bash
crossplane xpkg push xpkg.example.com/platform/snippystack:v0.1.0
```

Use whatever registry you have (`ghcr.io/you/snippystack:v0.1.0`, a local
`localhost:5000/...`, etc.). The push is an ordinary OCI push; your platform now
lives in a registry like any container image.

### 4c. Install it on a (fresh) cluster

Simulate a brand-new cluster by removing the loose objects you applied by hand:

```bash
# Pretend this is a clean cluster: tear down the hand-applied API.
kubectl delete composition app.platform.snippy.io
kubectl delete xrd apps.platform.snippy.io
kubectl delete -f manifests/course-03/functions.yaml
```

Now install the whole platform with **one resource**. Note this is the
`pkg.crossplane.io/v1` `Configuration` (the installable kind), not the metadata
kind from §3:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: snippystack
spec:
  package: xpkg.example.com/platform/snippystack:v0.1.0
```

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: snippystack
spec:
  package: xpkg.example.com/platform/snippystack:v0.1.0
EOF
```

### 4d. Watch the package manager do your install order for you

```bash
# The Configuration becomes Installed + Healthy...
kubectl get configuration.pkg.crossplane.io

# ...which pulled in the functions from dependsOn, automatically:
kubectl get functions.pkg.crossplane.io

# ...and installed your API:
kubectl get xrd
kubectl get composition
```

You never applied the functions or the XRD. The package manager read
`dependsOn`, resolved versions, pulled the function packages, installed the XRD
and Composition, and marked everything Healthy. That's the "install order" you
used to keep in your head, now encoded in the package.

### 4e. Prove it still works

```bash
kubectl apply -f manifests/course-03/app.yaml
kubectl get app hello-snippy -n default
kubectl get deploy,svc,configmap -n default -l crossplane.io/composite=hello-snippy
```

Same `App`, same three composed resources, same running Snippy — but now served
by an installed, versioned product instead of loose files.

---

## 5. Peek under the hood: no pod, one revision

Check that your Configuration really is inert data:

```bash
kubectl -n crossplane-system get deploy        # no new deployment for snippystack
kubectl get configurationrevision
```

A Provider or Function install spins up a controller pod. Your Configuration
does **not** — there's nothing to run. Instead, exactly like Course 9 described,
installing it created a **`ConfigurationRevision`**:

```bash
kubectl get configurationrevision
# NAME                 HEALTHY   REVISION   IMAGE                                          STATE
# snippystack-abc123   True      1          xpkg.example.com/platform/snippystack:v0.1.0   Active
```

The `Configuration` is the *rolling pointer*; each resolved package digest
becomes a `ConfigurationRevision`. The Active revision *owns* the XRD and
Composition it installed (via owner references), which is why uninstalling later
cleans them up. This is the same revision machinery you traced for providers in
Course 9 — Configurations ride the identical rails.

---

## 6. Break it on purpose

### 6a. Ship v0.2.0 and watch a new revision

Bump the greeting default in `apis/xrd.yaml`, then rebuild and push a new
version:

```bash
cd configuration
crossplane xpkg build
crossplane xpkg push xpkg.example.com/platform/snippystack:v0.2.0
```

Point the installed Configuration at the new version:

```bash
kubectl patch configuration.pkg.crossplane.io snippystack --type merge \
  -p '{"spec":{"package":"xpkg.example.com/platform/snippystack:v0.2.0"}}'

kubectl get configurationrevision
# Now TWO revisions: v0.1.0 goes Inactive, v0.2.0 becomes Active.
```

Crossplane created a *second* `ConfigurationRevision`, activated it, and
deactivated the old one — a controlled, auditable upgrade. Roll back by patching
the package reference back to `v0.1.0`; the old revision reactivates. Your
platform now has release management.

### 6b. Delete the Configuration and watch the API vanish

```bash
kubectl delete configuration.pkg.crossplane.io snippystack

kubectl get xrd            # apps.platform.snippy.io is gone
kubectl get composition    # app.platform.snippy.io is gone
```

Because the Active revision *owned* the XRD and Composition, deleting the
Configuration garbage-collects them through ordinary Kubernetes owner references
— no custom cleanup logic. (The functions pulled via `dependsOn` are *not*
auto-removed; they may be shared, so Crossplane leaves them.)

> ⚠️ Deleting the Configuration removes the **API definition**, not necessarily
> the `App` instances developers created. Deleting an XRD that still has live XRs
> is blocked/dangerous — tear down the `App`s first. In production you'd gate
> this behind GitOps and the `Usage` protections from Course 13.

---

## 7. Scorecard update

| # | Course 0 pain | Status after Course 10 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ API + install both versioned in a registry + Git |
| 2 | No self-service API | ✅ the `App` API, now shippable |
| 3 | Two worlds (cluster vs cloud) | ✅ one engine (Course 2, 7) |
| 4 | No continuous reconciliation of external state | ✅ the MR loop (Course 7) |
| 5 | **Platform isn't an installable product** | ✅ **solved — one `Configuration` installs it all** |

Pain #5 is closed. Your platform is a versioned OCI artifact that installs,
upgrades, rolls back, and self-resolves its dependencies.

---

## 8. Takeaway

A Configuration turns "a folder of YAML and an install ritual" into a single
versioned product. It carries your XRDs and Compositions as pure data, declares
its function/provider dependencies in `dependsOn`, and installs with one
`Configuration` resource — spawning a `ConfigurationRevision` but *no pod*,
because there's nothing to run. You can now stand up SnippyStack on any v2
cluster in one command, upgrade it with a version bump, and roll it back by
pointing at an older tag. The platform is finally portable.

### Cleanup

```bash
# Remove any App instances, then the platform API.
kubectl delete app --all -n default
kubectl delete configuration.pkg.crossplane.io snippystack --ignore-not-found
cd configuration && rm -f *.xpkg
```

**Next:** [Course 11 — Write a Composition Function](./course-11-write-a-composition-function.md),
where you replace patch-and-transform with your *own* code — real conditionals,
real logic — closing the loop you first met as a Kopf operator in `myk8scourses`.
