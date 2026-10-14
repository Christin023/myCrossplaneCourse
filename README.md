# myCrossplanecourses — Learn Crossplane by Building One Real Platform API

A hands-on course series that teaches Crossplane **concepts, architecture,
backend mechanisms, and implementation** — not as disconnected topics, but by
building a single self-service platform API and evolving it until it becomes a
production-grade, packaged, extensible control plane.

The teaching trick (borrowed from its sibling repo
[`myk8scourses`](../myk8scourses)): every course starts by making the **previous
setup hurt**, then introduces the Crossplane feature that relieves the pain. You
learn *why* each piece exists before you learn *how* to use it.

> **New to Kubernetes?** Do [`myk8scourses`](../myk8scourses) first. Crossplane
> *is* a set of Kubernetes controllers and CRDs — this series assumes you already
> know Pods, Deployments, CRDs, controllers, and the reconcile loop. Course 1
> recaps exactly the parts we build on.

## The running case: **SnippyStack**

In `myk8scourses` you deployed **Snippy** (a tiny pastebin service) by hand —
writing a Deployment, a Service, a ConfigMap, over and over, for every
environment. That is the pain this series fixes.

Here you become the **platform team**. Instead of handing developers raw YAML,
you offer them a new, higher-level API: a single resource called **`App`**.
A developer writes six lines:

```yaml
apiVersion: platform.snippy.io/v1alpha1
kind: App
metadata:
  name: team-a-snippy
  namespace: team-a
spec:
  image: snippy:0.1
  replicas: 3
  greeting: "Hello from Team A"
```

...and Crossplane *composes* a whole running Snippy environment behind it
(a ConfigMap + a Deployment + a Service, and later real cloud resources). The
developer never sees the moving parts. You, the platform engineer, defined them
once. That is Crossplane.

| Course | SnippyStack's form | New concept it forces |
|-------:|--------------------|-----------------------|
| 0  | Hand-written YAML, repeated per env | Why a control plane at all |
| 1  | Crossplane installed | Extending the control plane |
| 2  | First Managed Resource | Providers reconcile the *outside* world |
| 3  | `App` XRD + Composition | Your own API that composes resources |
| 4  | Parameterized `App` | Patch, transform & function pipelines |
| 5  | Self-service `App` per namespace | Namespaced XRs, claims, RBAC |
| 6–9 | (same API) | Peel back the control-plane internals |
| 10–12 | `App` as a **package** + your own function/provider | Extend & implement internals |
| 13 | Hardened, GitOps-driven control plane | Production |

See [`CURRICULUM.md`](./CURRICULUM.md) for the complete outline.

## Repo layout

```
myCrossplanecourses/
├── README.md              <- you are here
├── CURRICULUM.md          <- full 14-course outline
├── snippy/                <- the app the platform runs (shared with myk8scourses)
├── courses/               <- one markdown lesson per course (00–13)
│   ├── course-00-pain-without-a-control-plane.md
│   ├── course-01-crossplane-is-a-control-plane.md
│   ├── course-02-providers-and-managed-resources.md
│   ├── course-03-your-first-composite-api.md
│   ├── course-04-compositions-functions-patch-transform.md
│   ├── course-05-claims-namespaced-xrs-and-self-service.md
│   ├── course-06-anatomy-of-a-control-plane.md
│   ├── course-07-life-of-a-managed-resource.md
│   ├── course-08-the-composition-engine.md
│   ├── course-09-packages-xpkg-and-oci.md
│   ├── course-10-build-a-configuration-package.md
│   ├── course-11-write-a-composition-function.md
│   ├── course-12-write-your-own-provider.md
│   └── course-13-production-hardening.md
├── manifests/             <- the YAML used by each course
│   ├── course-02/         <- providers, ProviderConfigs, first Managed Resources
│   ├── course-03/         <- the App XRD + Composition + functions + an App
│   ├── course-04/         <- parameterized Composition + dev/prod Apps
│   ├── course-05/         <- namespaced self-service + RBAC + legacy claim example
│   ├── course-07/         <- management policies, deletion policy, observe-only
│   └── course-13/         <- DeploymentRuntimeConfig, Usage, least-privilege RBAC
├── configuration/         <- Course 10: the SnippyStack Configuration package
│   ├── crossplane.yaml
│   └── apis/
└── functions/             <- Course 11: your own composition function (Python)
    └── snippy-app/
```

Courses 6–9 are architecture/internals deep-dives that inspect the control
plane you built rather than adding manifests.

## Prerequisites

Install these once before Course 1:

- **Docker** (or Podman) — Crossplane, providers, and functions all run as pods;
  functions also run locally via Docker for `crossplane render`.
- **A local Kubernetes cluster** — [kind](https://kind.sigs.k8s.io/)
  (recommended), [minikube](https://minikube.sigs.k8s.io/), or
  [k3d](https://k3d.io/). Crossplane itself is just a workload on this cluster.
- **kubectl** — the Kubernetes CLI.
- **Helm** — the supported way to install Crossplane.
- **The Crossplane CLI** (`crossplane`) — for `render`, `xpkg build`, and
  `beta trace`. Install:
  ```bash
  curl -sL https://raw.githubusercontent.com/crossplane/crossplane/main/install.sh | sh
  sudo mv crossplane /usr/local/bin
  ```

Quick check:

```bash
docker version
kubectl version --client
helm version
crossplane version        # client version prints even without a cluster
kind version              # or: minikube version
```

This series targets **Crossplane v2** (v2.0+). v2 made composite resources
namespaced, retired claims as a separate concept, and made composition
**functions** the one and only composition engine. Where behavior differs from
the older v1 model, the course calls it out explicitly.

## How to use this repo

Work through the courses in order. Each lesson follows the same rhythm:

1. **Recap the pain** left by the previous course.
2. **Introduce the concept** that fixes it.
3. **Do the lab** (copy-paste commands + YAML from this repo).
4. **Peek under the hood** at the mechanism that makes it work.
5. **Break it on purpose** — the step where real understanding happens.
6. **Takeaway** — the one idea to remember.

Start here → [`courses/course-00-pain-without-a-control-plane.md`](./courses/course-00-pain-without-a-control-plane.md)

## License

Content and code in this repo are provided for learning. Use freely.
