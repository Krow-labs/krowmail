//! 参考收发服务。SQLite 存信，Ed25519 验签，根节点或 `/.well-known/krowmail` 取公钥。

mod http;
mod store;

use std::collections::BTreeMap;

pub use http::serve;

#[derive(Clone, Debug)]
pub struct Config {
    pub domain: String,
    pub segment_count: u8,
    pub db_path: String,
    pub public_endpoint: String,
    pub root: Option<String>,
    pub peers: BTreeMap<String, String>,
    pub trust_peers: bool,
    pub debug_wire: bool,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let domain = std::env::var("KROWMAIL_DOMAIN").map_err(|_| "缺少 KROWMAIL_DOMAIN")?;
        let segment_count = std::env::var("KROWMAIL_SEGMENT_COUNT")
            .ok()
            .and_then(|raw| raw.parse().ok())
            .unwrap_or(3);
        if !(1..=3).contains(&segment_count) {
            return Err("KROWMAIL_SEGMENT_COUNT 只能是 1 到 3".into());
        }
        Ok(Self {
            domain,
            segment_count,
            db_path: std::env::var("KROWMAIL_DB").unwrap_or_else(|_| "krowmail.sqlite".into()),
            public_endpoint: std::env::var("KROWMAIL_PUBLIC_ENDPOINT")
                .unwrap_or_else(|_| "http://127.0.0.1:8080".into()),
            root: std::env::var("KROWMAIL_ROOT")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            peers: parse_peers(&std::env::var("KROWMAIL_PEERS").unwrap_or_default()),
            trust_peers: std::env::var("KROWMAIL_TRUST_PEERS").ok().as_deref() == Some("1"),
            debug_wire: std::env::var("KROWMAIL_DEBUG_WIRE").ok().as_deref() == Some("1"),
        })
    }
}

fn parse_peers(raw: &str) -> BTreeMap<String, String> {
    raw.split(',')
        .filter_map(|item| {
            let (domain, url) = item.trim().split_once('=')?;
            let domain = domain.trim();
            let url = url.trim().trim_end_matches('/');
            if domain.is_empty() || url.is_empty() {
                None
            } else {
                Some((domain.to_string(), url.to_string()))
            }
        })
        .collect()
}
