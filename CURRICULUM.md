# Curriculum — Crossplane by Building SnippyStack

Three tracks, 14 courses. Track A builds intuition and the "why" and gets a real
self-service API working. Track B opens the hood on architecture and backend
mechanisms. Track C has you *implement* Crossplane's extension points yourself:
a Configuration package, a composition function, and a toy provider.

Each course is a ~45–90 min session with the rhythm:
**Recap pain → New concept → Live lab → Peek under the hood → Break it on purpose → Takeaway.**

The running case is **SnippyStack**: you are a platform team turning the
hand-rolled *Snippy* app from [`myk8scourses`](../myk8scourses) into a
self-service `App` API that developers consume without touching Deployments or
Services.

> **Version note:** this series targets **Crossplane v2**. v2 made XRs
> namespaced, removed claims as a distinct type, and made composition
> **functions** mandatory (no more native patch-and-transform in core). Courses
> flag v1-vs-v2 differences where they matter.

---

## Track A — From YAML Toil to a Self-Service API (concepts + the "why")

### Course 0 — The Pain Without a Control Plane  ✅
Deploy Snippy the `myk8scourses` way across three "environments" by hand. Feel
config drift, copy-paste errors, no self-service, no single source of truth for
infrastructure, and the ticket queue between devs and ops. Those gaps *are* the
Crossplane feature list.

### Course 1 — Crossplane Is a Control Plane  ✅
Install Crossplane with Helm into a kind cluster. Discover that it adds *nothing
you can use yet* — just new CRDs and a reconcile engine. Learn the thesis:
Kubernetes is a control plane for containers; Crossplane turns it into a control
plane for **anything with an API**. **Takeaway:** Crossplane is Kubernetes'
reconcile loop pointed at the outside world.

### Course 2 — Providers & Managed Resources
Install `provider-kubernetes` and `provider-nop`. Configure a `ProviderConfig`.
Create your first **Managed Resource (MR)** — a provider's CRD that maps 1:1 to
an external object — and watch a controller make the outside world match it.
Meet the `crossplane.io/external-name` annotation and connection secrets.
**Takeaway:** a provider is a controller whose "cluster" is some external API.

### Course 3 — Your First Composite API (XRD + Composition)
Teach the control plane a new noun: `App`. Define a **CompositeResourceDefinition
(XRD)** for `platform.snippy.io/App`, and a **Composition** (Pipeline mode) that
fans one `App` out into a ConfigMap + Deployment + Service for Snippy. Create an
`App`; watch a whole environment appear. **Takeaway:** an XRD is your API's
schema; a Composition is its implementation.

### Course 4 — Compositions II: Functions, Patch & Transform
Make the `App` configurable. Use `function-patch-and-transform` to wire
`spec.replicas`, `spec.image`, and `spec.greeting` into the composed resources,
with transforms and defaults. Add `function-auto-ready`. Render locally with
`crossplane render` — no cluster round-trip. **Takeaway:** a Composition is a
**pipeline of functions** that compute desired state from the XR.

### Course 5 — Claims, Namespaced XRs & Self-Service
Give developers safe self-service. In **v2**, XRs are namespaced: a dev creates
an `App` in their own namespace and RBAC confines them there. See how **v1**
solved this with claims (XRC) and why v2 dropped them. Add a developer Role.
**Takeaway:** the platform team owns the Composition; developers own only the
small, namespaced API surface you exposed.

---

## Track B — Architecture & Backend Mechanisms (the "how it actually works")

### Course 6 — Anatomy of a Control Plane
Tour every pod and object: the Crossplane core (composition + package
controllers), the **RBAC manager**, provider pods, function pods, and the CRDs
each installs. Everything is an API object; every component is a client of the
API server — exactly like core Kubernetes. **Takeaway:** Crossplane is "more
Kubernetes," not a sidecar system.

### Course 7 — The Life of a Managed Resource
Trace one MR end-to-end through the provider's reconcile loop:
`Observe → Create/Update/Delete`, the `ExternalClient` interface, the
`external-name` annotation as the bridge to external identity, connection
details → Secrets, readiness, `managementPolicies`, and `deletionPolicy`.
Orphan an external resource on purpose. **Takeaway:** every provider implements
the same four-verb contract against its API.

### Course 8 — The Composition Engine
Trace one `App` end-to-end: the XR reconciler observes the XR and composed
resources, builds a `RunFunctionRequest`, calls each function over **gRPC**, and
each returns **desired state** that accumulates down the pipeline before
server-side apply. Meet composition revisions and `crossplane beta trace`.
**Takeaway:** functions are pure(ish) functions of (observed, desired, input) →
desired; the engine owns all I/O.

### Course 9 — Packages: xpkg, OCI & the Package Manager
Providers, functions, and configurations are all **OCI images** (`.xpkg`). Learn
how the package manager unpacks them, creates `*Revision` objects, resolves
dependencies, and reconciles provider/function **pods** into existence. Inspect
a package's layers. **Takeaway:** installing Crossplane extensions is just
pulling and reconciling OCI images into controllers.

---

## Track C — Implementation (build the extension points yourself)

### Course 10 — Build a Configuration Package
Package the SnippyStack `App` XRD + Composition into a **Configuration** OCI
image with `crossplane.yaml` dependencies on the functions. Build it with
`crossplane xpkg build`, push it, and install it with a single `Configuration`
resource on a fresh cluster. **Takeaway:** your platform API becomes a versioned,
installable artifact — infrastructure as a product.

### Course 11 — Write a Composition Function
Replace patch-and-transform with **your own function**. Start with inline
`function-python`, then scaffold a real function package (`main.py`, Dockerfile,
`crossplane.yaml`) that reads the `App` spec and emits the composed resources in
code. Test it with `crossplane render`. **Takeaway:** a function is just a gRPC
server that transforms desired state — you can put real logic in your platform.

### Course 12 — Write Your Own Provider
Demystify providers. Study the `ExternalClient` `Observe/Create/Update/Delete`
contract from Course 7, then implement a minimal managed resource + controller
(using `crossplane-runtime` concepts, illustrated against a toy external API).
See how `provider-nop` and `provider-kubernetes` are the same shape.
**Takeaway:** a provider is the reconcile loop you already understand, wrapped
around someone else's API.

### Course 13 — Production Hardening (capstone)
Least-privilege RBAC (the RBAC manager + aggregated ClusterRoles),
`DeploymentRuntimeConfig` for provider pods, `Usage` for deletion ordering,
`ImageConfig` for registry auth and signature verification, observability,
GitOps with Argo CD, control-plane HA, and v1→v2 migration. Deploy SnippyStack
from the Configuration package via GitOps. **Takeaway:** you can design, run,
extend, and reason about a production control plane.

---

## Progress

All 14 courses (0–13) are written, with runnable manifests, a Configuration
package, and a composition function.

- [x] Course 0 — The Pain Without a Control Plane
- [x] Course 1 — Crossplane Is a Control Plane
- [x] Course 2 — Providers & Managed Resources
- [x] Course 3 — Your First Composite API (XRD + Composition)
- [x] Course 4 — Compositions II: Functions, Patch & Transform
- [x] Course 5 — Claims, Namespaced XRs & Self-Service
- [x] Course 6 — Anatomy of a Control Plane
- [x] Course 7 — The Life of a Managed Resource
- [x] Course 8 — The Composition Engine
- [x] Course 9 — Packages: xpkg, OCI & the Package Manager
- [x] Course 10 — Build a Configuration Package
- [x] Course 11 — Write a Composition Function
- [x] Course 12 — Write Your Own Provider
- [x] Course 13 — Production Hardening
