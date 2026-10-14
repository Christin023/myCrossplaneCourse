"""Entry point: start the gRPC server for the SnippyStack composition function.

The crossplane-function SDK's CLI helper wires up TLS, logging, and the gRPC
server. In production Crossplane runs this in a pod and talks to it over mTLS.
For local development pass --insecure so `crossplane render` can reach it.
"""

from crossplane.function import runtime

from function import FunctionRunner


def main():
    runtime.serve(
        FunctionRunner(),
        # These flags are parsed by the SDK's runtime helper.
    )


if __name__ == "__main__":
    main()
