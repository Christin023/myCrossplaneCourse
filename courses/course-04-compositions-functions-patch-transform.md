# Course 4 — Compositions II: Functions, Patch & Transform

> **Goal:** Turn the mostly-static `App` from Course 3 into a genuinely
> configurable platform API, and meet the engine that makes it possible: a
> Composition is a **pipeline of functions** that compute desired state from the
> XR. You'll learn the patch-and-transform toolbox, write a value back to the
> XR's `status`, and — the headline — **render the whole thing locally** with
> `crossplane render`, no cluster round-trip required.

**You need:** the cluster from Course 3 with Crossplane v2, the `App` XRD and
functions already installed, `kubectl`, the `crossplane` CLI, and **Docker**
running locally (for `crossplane render`).

**Time:** ~55 min.

---

## 1. Recap the pain

Course 3 was a triumph: you taught the control plane a brand-new noun, `App`, and
one `kubectl apply` fanned out into a ConfigMap, a Deployment, and a Service. But
look closely at what you shipped — the Composition was mostly **static**. Yes, it
copied `metadata.name` around, but the interesting knobs a developer actually
cares about (how many replicas? which image? what greeting?) were only loosely
wired, and the `App` told you nothing back — its `status` sat empty.

That's not a self-service API yet; it's a fancy template. A real platform API
takes a developer's intent (`replicas: 4`, `greeting: "Snippy (prod)"`) and
transforms it into correct resources — and reports something useful back, like
the URL where the app lives. Today you make `App` configurable, and you learn the
machinery that does the transforming.

---

## 2. The concept: a Composition is a pipeline of functions

In Course 3 you saw `mode: Pipeline` and two `functionRef` steps but didn't dwell
on them. Dwell now, because this is the center of gravity for all of Crossplane
composition.

> 🧠 **A Composition does not "contain" your resources. It describes a pipeline
> of functions, and the functions compute the resources.** Each step receives the
> observed state (the XR + anything composed so far) plus its own `input`, and
> returns **desired state**. Crossplane runs the steps in order and applies the
> accumulated result.

This is the single biggest **v1→v2 difference** you'll feel day to day:

| | Crossplane v1 (classic) | Crossplane v2 |
|---|---|---|
| Resources | Listed inline in the Composition (`spec.resources`) | Computed by **functions** in a pipeline |
| Patch & transform | Native, baked into core | A **function** (`function-patch-and-transform`) |
| Functions | Optional add-on | **Mandatory** — there is no native path |

So the familiar "patch and transform" you may have read about in old docs is
*still here* — but it now lives inside a function named, fittingly,
`function-patch-and-transform`. Our `manifests/course-03/functions.yaml` already
installed it (plus `function-auto-ready`). The Composition just calls it.

### The transform toolbox

`function-patch-and-transform` builds each composed resource from a `base`
template, then applies a list of **patches**. A patch copies a value from one
field to another and can run it through **transforms** on the way:

- **string** — reformat a value (`Format`, `TrimPrefix`, `ToUpper`, …)
- **map** — translate one value into another via a lookup table
- **math** — multiply/add (e.g. derive a memory limit from a replica count)
- **convert** — change type (string → int, int → bool, …)

And patches come in directions:

- **FromCompositeFieldPath** — XR → composed resource (the common case)
- **ToCompositeFieldPath** — composed resource → XR (write to `status`)
- **CombineToComposite / CombineFromComposite** — merge several fields into one

---

## 3. Lab: walk through the parameterized Composition

Open [`manifests/course-04/composition-parameterized.yaml`](../manifests/course-04/composition-parameterized.yaml).
It has the **same name** as the Course 3 Composition
(`app.platform.snippy.io`), so applying it *updates in place* — no delete needed.
Let's read the three interesting bits before we apply anything.

### 3a. A `string` `Format` transform names the ConfigMap

The ConfigMap shouldn't just be called `snippy-dev`; it should be
`snippy-dev-config`. A patch copies the App's name and reformats it:

```yaml
patches:
  - type: FromCompositeFieldPath
    fromFieldPath: metadata.name
    toFieldPath: metadata.name
    transforms:
      - type: string
        string:
          type: Format
          fmt: "%s-config"
  - type: FromCompositeFieldPath
    fromFieldPath: spec.greeting
    toFieldPath: data.greeting
```

`fmt: "%s-config"` takes the App's `metadata.name` and produces
`<name>-config`. The second patch drops `spec.greeting` straight into the
ConfigMap's `data.greeting`.

### 3b. Plain patches wire replicas / image / greeting onto the Deployment

The Deployment's `base` has `"placeholder"` where the real values go; patches
overwrite them from the XR spec:

```yaml
patches:
  - type: FromCompositeFieldPath
    fromFieldPath: spec.replicas
    toFieldPath: spec.replicas
  - type: FromCompositeFieldPath
    fromFieldPath: spec.image
    toFieldPath: spec.template.spec.containers[0].image
  - type: FromCompositeFieldPath
    fromFieldPath: spec.greeting
    toFieldPath: spec.template.spec.containers[0].env[0].value
```

That last one is Snippy's `APP_GREETING` env var — the same one you set by hand,
three times, back in Course 0. Now it flows from a single field.

### 3c. `CombineToComposite` writes `status.url` back to the XR

Here's the payoff that makes `App` feel like a real API — it *answers*. On the
Service, a `CombineToComposite` patch merges the Service name and namespace into
a URL and writes it to the XR's `status.url`:

```yaml
- type: CombineToComposite
  toFieldPath: status.url
  combine:
    variables:
      - fromFieldPath: metadata.name
      - fromFieldPath: metadata.namespace
    strategy: string
    string:
      fmt: "http://%s.%s.svc.cluster.local"
```

> 🧠 **This is the direction that matters for UX.** `FromCompositeFieldPath`
> flows *in* (developer intent → resources). `ToCompositeFieldPath` /
> `CombineToComposite` flow *out* (resource reality → the `status` a developer
> reads). The XRD you wrote in Course 3 already declared `status.url` in its
> schema — this is what fills it.

### 3d. Render it locally — no cluster needed

Before touching the cluster, run the whole pipeline on your laptop. This is the
feature that changes how you develop Compositions:

```bash
crossplane render \
  manifests/course-03/app.yaml \
  manifests/course-04/composition-parameterized.yaml \
  manifests/course-03/functions.yaml
```

The three arguments are, in order: the **XR** (a developer's `App`), the
**Composition**, and the **Functions** to run. Crossplane pulls each function's
OCI image, starts it **locally via Docker**, feeds it the XR, and prints the
composed resources it *would* create — plus the XR with its computed `status`.

> 🧠 **`crossplane render` runs the exact same functions the cluster runs, but
> entirely offline.** No API server, no etcd, no apply. It's the unit-test loop
> for platform engineering: edit a patch, re-render, read the output, repeat —
> in seconds. (Docker is required because functions are container images.)

In the output you'll see a `ConfigMap` named `hello-snippy-config`, a
`Deployment` with `replicas: 2` and `image: snippy:0.1`, a `Service`, and the
`App` carrying `status.url: http://hello-snippy.default.svc.cluster.local`.

### 3e. Apply to the cluster and prove it with two environments

Now make it real. Update the Composition (same name = update), then apply two
very different Apps from **one** API:

```bash
kubectl apply -f manifests/course-04/composition-parameterized.yaml
kubectl apply -f manifests/course-04/apps-dev-prod.yaml
```

[`apps-dev-prod.yaml`](../manifests/course-04/apps-dev-prod.yaml) defines
`snippy-dev` (`replicas: 1`) and `snippy-prod` (`replicas: 4`) — the exact
copy-paste chore from Course 0, now a few fields each.

```bash
kubectl get app
kubectl get app snippy-prod -o jsonpath='{.status.url}'; echo
kubectl get deploy snippy-prod -o jsonpath='{.spec.replicas}'; echo
```

`status.url` is populated for each App, and `snippy-prod` runs **4** replicas
while `snippy-dev` runs 1 — from the same Composition, the same XRD, zero
copy-paste.

---

## 4. Peek under the hood: desired state accumulates

Picture the pipeline as a conveyor belt carrying a **desired-state document**:

```
XR (App) ──▶ [function-patch-and-transform] ──▶ [function-auto-ready] ──▶ apply
             adds ConfigMap, Deployment,          marks the XR Ready when
             Service + status.url                 those resources are Ready
```

Each function receives everything the previous step produced and **adds to or
refines** it. Nothing is thrown away between steps — desired state *accumulates*
down the pipeline, and only the final accumulated result is applied (via
server-side apply). You'll trace this request/response in gory, gRPC detail in
Course 8.

Two rules worth tattooing on your brain:

> ⚠️ **Functions cannot mutate the XR's `spec`.** They can only produce composed
> resources and write the XR's `status`. The spec is the developer's intent and
> is sacred; a function that tried to "fix" `spec.replicas` would be fighting the
> user. That's why `status.url` is legal but rewriting `spec` is not.

> 🧠 **`function-auto-ready` is why you didn't wire readiness by hand.** It
> inspects the composed resources and flips the XR to `Ready: True` once they're
> all Ready. In classic v1 you'd configure readiness checks manually; here it's
> just another function in the pipeline.

And remember the toolbox is larger than what this Composition uses: **map**
(e.g. translate a friendly `size: large` into `replicas: 5`), **math** (derive
one number from another), and **convert** (fix types) are all available, as are
**patch policies** that control what happens when a source field is missing
(`fromFieldPath` policy `Optional` vs `Required`).

---

## 5. Break it on purpose

### Watch it converge after a hand-edit

The whole point of a control plane is that it *keeps* reality matching intent.
Poke the Deployment indirectly through its App and watch the loop react:

```bash
kubectl patch app snippy-dev --type merge -p '{"spec":{"replicas":5}}'
kubectl get deploy snippy-dev -w   # Ctrl-C once it reads 5
```

You changed the *App* (the source of truth), the composition engine recomputed
desired state, and the Deployment converged to 5. No `kubectl edit` on the
Deployment, no drift — the same reconcile heartbeat you met in `myk8scourses`
Course 2, now driving a resource you *composed*.

### Introduce a typo and let `render` catch it

Copy the Composition and break one `toFieldPath` on purpose — point it at a field
that doesn't exist on a Deployment:

```bash
cp manifests/course-04/composition-parameterized.yaml /tmp/broken.yaml
# edit /tmp/broken.yaml: change
#   toFieldPath: spec.replicas
# to
#   toFieldPath: spec.replicASS   # typo
crossplane render \
  manifests/course-03/app.yaml \
  /tmp/broken.yaml \
  manifests/course-03/functions.yaml
```

`render` surfaces the problem **locally, in seconds**, instead of after an apply
and a confused `kubectl describe`. This is the development loop you want: break
things on your laptop, not in the cluster.

---

## 6. Scorecard update

With a configurable, self-describing `App`, developers can now ask for an
environment by changing a handful of fields — the self-service abstraction from
Pain #2 is real.

| # | Course 0 pain | Status after Course 4 |
|---|---------------|------------------------|
| 1 | No single source of truth | ✅ the `App` object is the source; drift reconciles away |
| 2 | No self-service abstraction | ✅ **solved** — one configurable `App` API, no copy-paste |
| 3 | Two worlds (cluster vs cloud) | ⏭️ providers compose external resources the same way (Course 7) |
| 4 | No continuous reconciliation of external state | ⏭️ Course 7 |
| 5 | Platform not installable | ⏭️ Course 10 (Configuration packages) |

---

## 7. Takeaway

A Composition isn't a template — it's a **pipeline of functions** that compute
desired state from the XR. `function-patch-and-transform` gives you a toolbox
(string/map/math/convert transforms, in/out patch directions) to turn a
developer's small intent into correct resources, and `CombineToComposite` lets
your API *answer back* through `status`. Best of all, `crossplane render` runs
that exact pipeline on your laptop so you develop Compositions in seconds, not
apply-and-pray cycles. In **v2** this pipeline is the only path — functions are
mandatory — and that uniformity is what makes the rest of the series click.

### Cleanup

```bash
kubectl delete -f manifests/course-04/apps-dev-prod.yaml
rm -f /tmp/broken.yaml
# Leave the XRD, Composition and functions installed — Course 5 builds on them.
```

**Next:** [Course 5 — Claims, Namespaced XRs & Self-Service](./course-05-claims-namespaced-xrs-and-self-service.md),
where you hand this API to a real developer — safely confined to their own
namespace with ordinary Kubernetes RBAC.
