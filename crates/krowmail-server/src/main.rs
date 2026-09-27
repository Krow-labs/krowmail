use std::net::SocketAddr;

#[tokio::main]
async fn main() {
    let cfg = krowmail_server::Config::from_env().unwrap_or_else(|err| {
        eprintln!("{err}");
        std::process::exit(2);
    });
    let bind: SocketAddr = std::env::var("KROWMAIL_LISTEN")
        .unwrap_or_else(|_| "0.0.0.0:8080".into())
        .parse()
        .unwrap_or_else(|err| {
            eprintln!("KROWMAIL_LISTEN: {err}");
            std::process::exit(2);
        });
    let listener = tokio::net::TcpListener::bind(bind)
        .await
        .unwrap_or_else(|err| {
            eprintln!("bind {bind}: {err}");
            std::process::exit(2);
        });
    eprintln!(
        "krowmail-server {} listening on {}",
        cfg.domain,
        listener
            .local_addr()
            .map(|addr| addr.to_string())
            .unwrap_or_else(|_| bind.to_string())
    );
    if let Err(err) = krowmail_server::serve(cfg, listener).await {
        eprintln!("{err}");
        std::process::exit(1);
    }
}
