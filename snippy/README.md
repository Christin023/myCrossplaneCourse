# Snippy — the app the platform runs

This series reuses **Snippy**, the tiny Flask pastebin from the sibling repo
[`myk8scourses/snippy`](../../myk8scourses/snippy). SnippyStack's job is to run
Snippy for developers *on demand* — so you need the image available in your
cluster.

## Build and load the image

```bash
# build from the myk8scourses copy
docker build -t snippy:0.1 ../../myk8scourses/snippy

# load it into your local cluster
kind load docker-image snippy:0.1 --name snippy      # kind
# minikube image load snippy:0.1                     # minikube
# k3d image import snippy:0.1 -c snippy               # k3d
```

Snippy prints its `POD_NAME` and reads `APP_GREETING` from the environment —
both of which the SnippyStack `App` composition sets for you. That is how you
will *see* which composed Deployment served you, and prove that your `App`
parameters flowed all the way down to a running container.

If you did not do `myk8scourses`, any small HTTP image works — set
`spec.image` on your `App` to e.g. `nginx:1.27` and drop the `greeting` plumbing.
