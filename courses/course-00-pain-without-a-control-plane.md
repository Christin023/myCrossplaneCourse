# Course 0 — The Pain Without a Control Plane

> **Goal:** Deploy Snippy the way you did in `myk8scourses` — by hand, with raw
> Kubernetes YAML — but now across *three environments* and *for other people*.
> Deliberately hit every wall that a **control plane** (and Crossplane) was
> invented to knock down. By the end you'll have a gut-level list of problems
> that *are*, almost one-to-one, the Crossplane feature list.

**You need:** a local Kubernetes cluster (kind/minikube/k3d), `kubectl`, and the
`snippy:0.1` image loaded (see [`../snippy/README.md`](../snippy/README.md)). No
Crossplane yet.

**Time:** ~45 min.

---

## 1. Recap the pain

There is no previous Crossplane course, so here's the premise. In
`myk8scourses` you learned to run Snippy well: a Deployment, a Service, a
ConfigMap, probes, scaling. You are now good at Kubernetes.

Then your company grows. You are no longer *a* developer — you are the **platform
team**. Ten product teams want to run Snippy-like services. Each needs a dev, a
staging, and a prod environment. Your boss says: *"Let them self-serve. Don't
become a ticket queue."* That innocent sentence hides a mountain of work. Let's
climb it.

---

## 2. Deploy Snippy by hand, three times

A real environment for Snippy is at least three objects. Here's the dev one:

```bash
kubectl create namespace snippy-dev

cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata: { name: snippy-config, namespace: snippy-dev }
data: { greeting: "Snippy (dev)" }
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: snippy, namespace: snippy-dev }
spec:
  replicas: 1
  selector: { matchLabels: { app: snippy } }
  template:
    metadata: { labels: { app: snippy } }
    spec:
      containers:
        - name: snippy
          image: snippy:0.1
          ports: [{ containerPort: 8080 }]
          env:
            - name: APP_GREETING
              valueFrom: { configMapKeyRef: { name: snippy-config, key: greeting } }
---
apiVersion: v1
kind: Service
metadata: { name: snippy, namespace: snippy-dev }
spec:
  selector: { app: snippy }
  ports: [{ port: 80, targetPort: 8080 }]
EOF
```

It works. 🎉 Now do it **again** for `snippy-staging` (replicas: 2) and **again**
for `snippy-prod` (replicas: 4), each in its own namespace, each with a tweaked
greeting and replica count.

```bash
kubectl create namespace snippy-staging
kubectl create namespace snippy-prod
# ...copy the block, change namespace + replicas + greeting, apply. Twice.
```

Notice what you just did: you **copy-pasted a 30-line block three times** and
hand-edited three fields. Multiply by ten product teams. This is the job now.

---

## 3. Break it on purpose — the walls, one by one

### Wall A: "Just change the replica count in prod"

Prod needs 6 replicas now. You edit... which file? The one in your shell history?
A teammate's gist? You `kubectl edit` the live Deployment, it works, and now the
cluster disagrees with every YAML file anyone has. 

> 🧠 **Problem #1 — No single source of truth for infrastructure.** The real
> state lives in the cluster; the "intended" state is scattered across laptops.
> Drift is guaranteed.

### Wall B: "Team B wants their own Snippy — give them access"

You can hand Team B the 30-line YAML and hope they fill in the right fields. Half
of them will typo the selector, forget the ConfigMap, or point at the wrong
image. Every mistake becomes *your* support ticket.

> 🧠 **Problem #2 — No safe self-service abstraction.** Developers should ask for
> *"a Snippy environment"*, not assemble three primitives correctly every time.
> You have no way to offer a higher-level API.

### Wall C: "Also give them a database and an S3 bucket"

Real apps need cloud resources too. Now your YAML isn't enough — you reach for
the AWS Console (click-ops, no record), or a separate Terraform repo with its own
state file, its own `apply` cadence, its own drift, run from a laptop or a CI job
nobody fully trusts.

> 🧠 **Problem #3 — Two worlds.** In-cluster things (Deployments) reconcile
> continuously; cloud things (databases, buckets) are provisioned once by a
> *different* tool and then drift silently. There is no single engine keeping
> *everything* at desired state.

### Wall D: "Someone changed the prod bucket by hand"

With Terraform, a manual change in the console sits there until the next `apply`
— minutes or days later, if ever. Nothing is *continuously* enforcing your
intent. The console has no idea Terraform exists.

> 🧠 **Problem #4 — No continuous reconciliation for external resources.**
> `terraform apply` is a pulse, not a heartbeat. Kubernetes gives Deployments a
> heartbeat; your cloud resources don't have one.

### Wall E: "Ship the platform itself to another cluster"

A new region needs the whole setup: the Snippy template, the database module,
the bucket module, the glue. You copy repos, rewrite variables, and pray.

> 🧠 **Problem #5 — Your platform isn't a versioned, installable product.** It's
> a pile of YAML and Terraform you reassemble by hand per cluster.

---

## 4. Peek under the hood: what a "control plane" actually is

Every problem above is a variation of the same need:

> *"Keep reality continuously matching a declared desired state — for in-cluster
> AND out-of-cluster resources — behind an API I can offer to others, without me
> babysitting it."*

Kubernetes already solved this for **containers**. You declare a Deployment, and
a **reconciliation loop** (observe → diff → act, forever — the heartbeat from
`myk8scourses` Course 2) keeps three Pods alive across reboots and failures.

A **control plane** is that same idea, generalized:

- It stores **desired state** as API objects (in etcd, via the Kubernetes API).
- **Controllers** continuously reconcile the real world toward that state.
- The API is **extensible**: you can teach it new nouns (CRDs) and new behaviors
  (controllers) — which in `myk8scourses` Course 11–12 you did by hand with a
  CRD and a Kopf operator.

**Crossplane** is a packaged, powerful version of exactly that extension:
- It lets controllers (**providers**) reconcile *external* APIs — AWS, GCP, a
  database, even another Kubernetes cluster — the same way Deployments reconcile
  Pods. (Problem #3, #4)
- It lets you define your *own* higher-level APIs (**Composite Resources**) that
  bundle many resources behind one friendly type — "give me a Snippy
  environment." (Problem #2)
- Those APIs live in Git and in etcd as the single source of truth, reconciled
  forever. (Problem #1)
- And you can **package** the whole platform as a versioned OCI artifact and
  install it anywhere. (Problem #5)

Crossplane didn't invent reconciliation or these problems. It packaged the
solution into the control plane you already know — Kubernetes — so one engine
governs everything.

---

## 5. The scorecard (your pain → the rest of the series)

| # | Pain you just felt | Fixed in |
|---|--------------------|----------|
| 1 | No single source of truth for infra | Course 1–3 (everything is a reconciled API object) |
| 2 | No safe self-service abstraction | Course 3–5 (XRDs, Compositions, namespaced XRs) |
| 3 | Two worlds (cluster vs cloud) | Course 2 (providers + managed resources) |
| 4 | No continuous reconciliation of external state | Course 7 (the MR reconcile loop) |
| 5 | Platform isn't an installable product | Course 10 (Configuration packages) |

---

## 6. Takeaway

You don't need Crossplane because it's trendy. You need *something* that
continuously reconciles desired vs actual state for **everything** — in-cluster
and external — behind an API you can safely hand to other teams. You already met
that something's heart in `myk8scourses`: the reconcile loop. Crossplane points
that loop at the whole world. Keep this pain list in mind — each course crosses
one item off, and you'll know exactly *why* the feature exists.

**Next:** [Course 1 — Crossplane Is a Control Plane](./course-01-crossplane-is-a-control-plane.md),
where you install Crossplane and discover it adds a reconcile engine — and
nothing you can use *yet*.
