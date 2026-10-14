# Course 13 — Production Hardening

> **Goal:** The capstone. You can design APIs, compose them, package them, and
> extend Crossplane with your own functions and providers. Now run the whole
> SnippyStack control plane like you *mean* it: least-privilege RBAC, pinned
> runtime pods, enforced deletion ordering, secure image pulls, observability,
> and GitOps delivery — then ship SnippyStack from its Configuration package as
> the finale.

**You need:** the cluster with Crossplane v2, `provider-kubernetes`, the
SnippyStack Configuration from Course 10, `kubectl`, and the repo's
[`../manifests/course-13/`](../manifests/course-13/) directory. Argo CD optional.

**Time:** ~75 min.

---

## 1. Recap the pain

You've relieved every pain from Course 0: a single reconciled source of truth, a
self-service `App` API, one engine for cluster and cloud, continuous
reconciliation, and an installable Configuration package. But "it works on my
cluster" is not "it's in production." Right now your provider runs as
cluster-admin, its pod has no resource limits, nothing stops a careless delete
from orphaning a live resource, and your platform is installed by hand instead of
from Git. This course closes those gaps — the unglamorous work that separates a
demo from a platform people depend on.

---

## 2. Least privilege: fire the cluster-admin binding

In Course 2 you gave `provider-kubernetes` a cluster-admin binding to get moving.
In production that's a disaster: a bug or a compromise in the provider can touch
*anything*. Scope it to exactly what SnippyStack composes.

First, recall how Crossplane does RBAC (Course 3, 6): the **RBAC manager** in
`crossplane-system` watches installed packages and maintains **aggregated
ClusterRoles**. Any ClusterRole you label with
`rbac.crossplane.io/aggregate-to-crossplane: "true"` is rolled into Crossplane's
own permissions automatically — that's the supported extension point.

Apply the least-privilege rules from
[`../manifests/course-13/rbac-least-privilege.yaml`](../manifests/course-13/rbac-least-privilege.yaml):

```bash
# Grants provider-kubernetes ONLY deployments, services, and configmaps.
kubectl apply -f manifests/course-13/rbac-least-privilege.yaml
```

```yaml
# The essence of rbac-least-privilege.yaml:
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: provider-kubernetes-snippystack
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
# Bound to the named ServiceAccount the DeploymentRuntimeConfig creates (§3).
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: provider-kubernetes-snippystack
subjects:
  - kind: ServiceAccount
    name: provider-kubernetes
    namespace: crossplane-system
roleRef:
  kind: ClusterRole
  name: provider-kubernetes-snippystack
  apiGroup: rbac.authorization.k8s.io
```

Then remove the Course 2 cluster-admin binding:

```bash
kubectl delete clusterrolebinding provider-kubernetes-admin --ignore-not-found
```

SnippyStack keeps working because the composition only ever touches Deployments,
Services, and ConfigMaps — the exact three verbs-of-objects you just granted.

> 🧠 **Least privilege is testable here.** If your provider suddenly can't manage
> a resource, the RBAC is wrong *and the composition told you which object*. The
> blast radius of the provider is now a short, reviewable list in Git.

---

## 3. DeploymentRuntimeConfig: pin the provider pod

By default a provider pod runs with no resource limits, a generated SA, and a
loose security context. **DeploymentRuntimeConfig** (the v2 replacement for the
old `ControllerConfig`) controls *how* the pod runs. Apply
[`../manifests/course-13/deploymentruntimeconfig.yaml`](../manifests/course-13/deploymentruntimeconfig.yaml):

```bash
kubectl apply -f manifests/course-13/deploymentruntimeconfig.yaml
```

It does two jobs. It defines the runtime config:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: provider-hardened
spec:
  serviceAccountTemplate:
    metadata:
      name: provider-kubernetes        # the SA your RBAC binds to (§2)
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              resources:
                requests: { cpu: 100m, memory: 128Mi }
                limits:   { cpu: "1",  memory: 512Mi }
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                runAsNonRoot: true
```

And it attaches that config to the provider via `runtimeConfigRef`:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.crossplane.io/crossplane-contrib/provider-kubernetes:v0.18.0
  runtimeConfigRef:
    name: provider-hardened
```

Note the SA name (`provider-kubernetes`) matches the one your least-privilege
binding targets — the two manifests are designed to click together. Verify the
pod restarted with limits:

```bash
kubectl -n crossplane-system get pod -l pkg.crossplane.io/provider=provider-kubernetes \
  -o jsonpath='{.items[0].spec.containers[0].resources}{"\n"}'
```

---

## 4. Usage: enforce deletion ordering

Crossplane reconciles and deletes resources **in parallel** — it's eventually
consistent, with no built-in ordering. That can orphan or break things: delete
the ConfigMap while the Deployment still mounts it and Snippy loses its greeting.
A **`Usage`** resource declares "A is used by B" and a webhook **blocks deleting
A while B exists**. Apply
[`../manifests/course-13/usage.yaml`](../manifests/course-13/usage.yaml):

```bash
kubectl apply -f manifests/course-13/usage.yaml
```

```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: Usage
metadata:
  name: deployment-uses-configmap
  namespace: default
spec:
  reason: "Snippy Deployment reads APP_GREETING from the ConfigMap"
  of:
    apiVersion: v1
    kind: ConfigMap
    resourceRef:
      name: hello-snippy-config
  by:
    apiVersion: apps/v1
    kind: Deployment
    resourceRef:
      name: hello-snippy
```

Now try to delete the protected ConfigMap:

```bash
kubectl delete configmap hello-snippy-config -n default
# Error from server (admission webhook ... denied the request):
# ConfigMap is in-use by Deployment hello-snippy
```

Blocked. Delete the Deployment first (or the whole `App`) and the ConfigMap frees
up. This is how you make teardown safe in a parallel-reconcile world.

> ⚠️ The resource names in `usage.yaml` (`hello-snippy`, `hello-snippy-config`)
> match the `App` named `hello-snippy` from `manifests/course-03/app.yaml`. Apply
> that `App` first so the referenced objects exist, or the `Usage` has nothing to
> protect.

---

## 5. ImageConfig: secure the supply chain

Your packages are OCI images; in production they live in a *private* registry and
you want to verify what you pull. **`ImageConfig`** centralizes pull policy —
authentication and (with the right setup) signature verification — matched by
image prefix. Apply
[`../manifests/course-13/imageconfig.yaml`](../manifests/course-13/imageconfig.yaml):

```bash
# Create the pull secret it references, then apply the ImageConfig.
kubectl -n crossplane-system create secret docker-registry registry-credentials \
  --docker-server=registry.example.com --docker-username=USER --docker-password=PASS
kubectl apply -f manifests/course-13/imageconfig.yaml
```

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: ImageConfig
metadata:
  name: private-registry-auth
spec:
  matchImages:
    - type: Prefix
      prefix: registry.example.com/platform/
  registry:
    authentication:
      pullSecretRef:
        name: registry-credentials
```

Any package whose image starts with `registry.example.com/platform/` — your
SnippyStack Configuration and function — now pulls with those credentials, with
no per-package secrets scattered around. (ImageConfig is also where you wire
signature verification policy to reject unsigned packages.)

---

## 6. Observability: see what the control plane is doing

Three complementary views:

```bash
# 1. The composition tree for an App: XR -> composed resources, with status.
crossplane beta trace app/hello-snippy -n default

# 2. Conditions on everything — the primary signal (Synced/Ready, Course 7, 12).
kubectl get app,deploy,svc,configmap -n default
kubectl describe app hello-snippy -n default      # events + conditions

# 3. Prometheus metrics from the core and provider pods.
kubectl -n crossplane-system port-forward deploy/crossplane 8080:8080
curl -s localhost:8080/metrics | grep crossplane_ | head
```

`crossplane beta trace` is the one to reach for first — it renders the whole
SnippyStack object graph and shows *which* composed resource is unhealthy, so you
stop guessing. Conditions and events are the same debugging surface you learned
in `myk8scourses` — Crossplane adds no new mystery, just more objects to
`describe`.

> 🧠 **In Crossplane, observability is `kubectl` plus `trace`.** Because every
> piece of state is an API object with conditions and events, your existing
> Kubernetes debugging muscle memory transfers directly. The control plane
> watches itself the same way it watches everything else.

---

## 7. GitOps + HA: deliver and scale the control plane

### GitOps with Argo CD

Installing the Configuration by hand (Course 10) was fine for learning. In
production, Git is the source of truth and Argo CD syncs it — closing Pain #1 for
the *platform itself*, not just the apps. Commit a single file:

```yaml
# gitops/snippystack-configuration.yaml — the only thing Argo needs to install
# your entire platform API.
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: snippystack
spec:
  package: registry.example.com/platform/snippystack:v0.2.0
```

Point an Argo CD `Application` at the repo path holding it. Now a version bump is
a pull request: merge `v0.2.0` → Argo syncs → a new `ConfigurationRevision` rolls
out (Course 10 §6). Developers' `App` resources can live in their own Git repos,
synced the same way. The whole control plane is now reconciled from Git.

### Control-plane HA

For real uptime, run the core with replicas and leader election:

```bash
helm upgrade crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --reuse-values \
  --set replicas=3 --set leaderElection=true
```

Only one replica is the active leader at a time; the others stand by for instant
failover. Combine with the resource limits from §3 so the control plane behaves
under load.

> ⚠️ **Flag HA on the critical path.** The control plane is now
> infrastructure-of-infrastructure: if it's down, drift goes uncorrected and no
> new `App` reconciles. Give it the same HA, monitoring, and backup (etcd!) you'd
> give any production API server.

---

## 8. v1 → v2 migration notes

If you're bringing an older Crossplane v1 platform forward, the headline changes
you've relied on all series:

- **Namespaced XRs.** v2 XRDs use `scope: Namespaced` (see
  `configuration/apis/xrd.yaml`), so an `App` lives in a namespace and is
  governed by ordinary Kubernetes RBAC — no cluster-scoped composite + claim
  split.
- **Claims are deprecated.** v1's Claim/XR pairing (a namespaced claim fronting a
  cluster-scoped XR) is gone in the v2 model; the namespaced XR *is* the
  developer-facing resource. Migrate by redefining XRDs as `Namespaced` and
  retiring claim types. (`manifests/course-05/legacy-claim-example.yaml` shows
  the old shape for comparison.)
- **Functions are mandatory.** Every v2 Composition is a function pipeline
  (`mode: Pipeline`). Native patch-and-transform is replaced by
  `function-patch-and-transform`. Plan the migration so your Configuration's
  `dependsOn` lists every function your pipelines call (Course 10 §3).

Migrate incrementally: stand up v2 alongside v1, move one XRD at a time, and
cut traffic over per API.

---

## 9. The finale: ship SnippyStack from Git

Put it all together. On a clean production cluster:

1. `helm install crossplane` with `--set replicas=3 --set leaderElection=true` (§7).
2. Apply the hardening manifests: `rbac-least-privilege.yaml`,
   `deploymentruntimeconfig.yaml`, `imageconfig.yaml`.
3. Let Argo CD sync `gitops/snippystack-configuration.yaml` — the package manager
   pulls the functions (`dependsOn`) and installs the XRD + Composition (Course 10).
4. Developers commit `App` resources to their namespaces; Argo syncs them;
   Crossplane composes Snippy environments, reconciled forever.
5. `Usage` guards teardown ordering; `crossplane beta trace` shows health.

That's a production control plane: least-privilege, pinned, supply-chain-secured,
observable, HA, and delivered entirely from Git.

---

## 10. Scorecard: all five pains, closed

| # | Course 0 pain | Final status |
|---|---------------|--------------|
| 1 | No single source of truth for infra | ✅ Git → Argo → etcd; everything reconciled, including the platform |
| 2 | No safe self-service abstraction | ✅ the namespaced `App` API, RBAC-scoped per namespace |
| 3 | Two worlds (cluster vs cloud) | ✅ one engine; providers reconcile both (Course 2, 12) |
| 4 | No continuous reconciliation of external state | ✅ the MR heartbeat (Course 7, 12) |
| 5 | Platform not a versioned installable product | ✅ the Configuration package, GitOps-delivered (Course 10) |

Every wall from Course 0 is down.

---

## 11. Final takeaway

You started by feeling the pain of running Snippy by hand across environments and
teams. You can now **design** a platform API (XRD), **compose** it (functions),
**package** it (Configuration), **extend** Crossplane itself (your own function
and the provider contract), and **run** it in production (least privilege,
runtime configs, usage protection, secure pulls, observability, HA, GitOps). More
than any single feature, you learned the thesis: a control plane is the reconcile
loop you already trusted from `myk8scourses`, generalized to govern everything
behind APIs you offer others. You don't just use Crossplane now — you can reason
about it, debug it, and build on it.

Go run your control plane. 🚀

### Cleanup — the whole series

```bash
# Remove platform instances and API.
kubectl delete app --all -A --ignore-not-found
kubectl delete usage --all -A --ignore-not-found
kubectl delete configuration.pkg.crossplane.io snippystack --ignore-not-found

# Remove providers, functions, runtime/image configs.
kubectl delete function.pkg.crossplane.io --all --ignore-not-found
kubectl delete provider.pkg.crossplane.io --all --ignore-not-found
kubectl delete deploymentruntimeconfig --all --ignore-not-found
kubectl delete imageconfig --all --ignore-not-found

# Uninstall Crossplane itself.
helm uninstall crossplane -n crossplane-system
kubectl delete namespace crossplane-system --ignore-not-found

# Finally, delete the local cluster.
kind delete cluster --name snippy        # or: minikube delete / k3d cluster delete snippy
```

**Where to go next:** revisit the whole map in
[`../CURRICULUM.md`](../CURRICULUM.md), or the overview and prerequisites in
[`../README.md`](../README.md). The sibling [`../../myk8scourses`](../../myk8scourses)
is where this all started — the reconcile loop that Crossplane points at the
world.
