FROM krow-cn-shanghai.cr.volces.com/library/rust:1.95-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY spec ./spec
RUN cargo build --release -p krowmail-server -p krowmail-mcp

FROM krow-cn-shanghai.cr.volces.com/library/debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/target/release/krowmail-server /usr/local/bin/krowmail-server
COPY --from=build /src/target/release/krowmail-mcp /usr/local/bin/krowmail-mcp
EXPOSE 8080
ENTRYPOINT ["krowmail-server"]
