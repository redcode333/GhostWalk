# HydraDB graph-node for GhostWalk, built from a checkout of hydra-db/hydradb (the build context). Release mode, slim runtime.
#   docker build -f docker/hydradb.Dockerfile -t ghostwalk-hydradb ../hydradb
# CI (.github/workflows/hydradb-image.yml) builds it and pushes ghcr.io/redcode333/ghostwalk-hydradb:<sha> and :latest.
FROM ubuntu:24.04 AS builder
ARG RUST_TOOLCHAIN=stable
ENV DEBIAN_FRONTEND=noninteractive CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup PATH=/usr/local/cargo/bin:${PATH}
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates clang cmake curl git libclang-dev libcypher-parser-dev libffi-dev libgraphblas-dev pkg-config && \
    rm -rf /var/lib/apt/lists/* && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain "${RUST_TOOLCHAIN}"
WORKDIR /workspace
# LAGraph has no Ubuntu package: build it statically against the system GraphBLAS (prefix /usr/local), as HydraDB's own Dockerfile does.
COPY scripts/install_lagraph.sh /tmp/install_lagraph.sh
RUN bash /tmp/install_lagraph.sh /usr/local
ENV LIBRARY_PATH=/usr/local/lib LAGRAPH_LIB_DIR=/usr/local/lib
COPY . .
# --ignore-rust-version: the workspace pins an MSRV newer than some stable toolchains; the code builds with stable regardless.
RUN cargo build --release --ignore-rust-version \
      --features server-runtime,experimental-cypher-engine,datafusion-cypher-engine \
      --bin graph-node && \
    strip --strip-debug target/release/graph-node

FROM ubuntu:24.04 AS runtime
ARG GIT_SHA=""
LABEL org.opencontainers.image.revision="${GIT_SHA}" org.opencontainers.image.source="https://github.com/redcode333/GhostWalk"
ENV DEBIAN_FRONTEND=noninteractive RUST_LOG=info
# libgraphblas / libcypher-parser shared objects (LAGraph is linked statically into graph-node)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libcypher-parser-dev libgraphblas-dev && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 graph && useradd --uid 10001 --gid graph --no-create-home --shell /usr/sbin/nologin graph && \
    mkdir -p /var/cache/slatedb /tmp/graph /data/store /data/cache && chown -R graph:graph /var/cache/slatedb /tmp/graph /data
COPY --from=builder /workspace/target/release/graph-node /usr/local/bin/graph-node
USER 10001:10001
EXPOSE 7687 8443 9090
ENTRYPOINT ["/usr/local/bin/graph-node"]
