use std::sync::{Arc, Mutex};

use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, post};
use axum::{Json, Router};
use krowmail_core::{parse_open, verify, AcceptDirectory, Directory, Envelope, Identity};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::net::TcpListener;

use crate::store::{Row, Store};
use crate::Config;

struct Inner {
    cfg: Config,
    store: Mutex<Store>,
    identity: Identity,
    client: reqwest::Client,
}

#[derive(Clone)]
struct App {
    inner: Arc<Inner>,
}

struct DomainHit {
    endpoint: String,
    public_key: String,
    key_id: String,
    registered: bool,
}

pub async fn serve(cfg: Config, listener: TcpListener) -> Result<(), String> {
    let store = Store::open(&cfg.db_path)?;
    let identity = store.identity(&cfg.domain)?;
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|err| err.to_string())?;
    let app = App {
        inner: Arc::new(Inner {
            cfg,
            store: Mutex::new(store),
            identity,
            client,
        }),
    };
    let router = Router::new()
        .route("/healthz", get(health))
        .route("/.well-known/krowmail", get(well_known))
        .route("/krowmail/v1/inbound", post(inbound))
        .route("/krowmail/v1/send", post(send_mail))
        .route("/krowmail/v1/inbox", get(inbox))
        .route("/krowmail/v1/messages/{id}", get(read_message))
        .with_state(app);
    axum::serve(listener, router)
        .await
        .map_err(|err| err.to_string())
}

async fn health() -> &'static str {
    "ok"
}

async fn well_known(State(app): State<App>) -> Json<Value> {
    Json(json!({
        "domain": app.inner.cfg.domain,
        "endpoint": app.inner.cfg.public_endpoint.trim_end_matches('/'),
        "public_key": app.inner.identity.public_key_b64(),
        "key_id": app.inner.identity.key_id,
        "segment_count": app.inner.cfg.segment_count,
    }))
}

#[derive(Deserialize)]
struct SendBody {
    from: String,
    to: String,
    body: String,
    #[serde(default)]
    subject: String,
    thread_id: Option<String>,
    in_reply_to: Option<String>,
    // 0.3.0 协议位（可选）：校验在 Envelope::validate 一处。
    kind: Option<String>,
    due_at: Option<String>,
    decision_for: Option<String>,
    outcome: Option<String>,
}

async fn send_mail(
    State(app): State<App>,
    Json(req): Json<SendBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let from = parse_open(&req.from).map_err(bad)?;
    let to = parse_open(&req.to).map_err(bad)?;
    if from.domain != app.inner.cfg.domain {
        return Err(bad("发件域名不是本机"));
    }
    let from_addr = canonical(&from.segments, &from.domain);
    let to_addr = canonical(&to.segments, &to.domain);
    directory(&app, &from.domain)?
        .resolve_local(&from.domain, &from.segments)
        .map_err(bad)?;
    let envelope = Envelope {
        id: uuid::Uuid::new_v4().to_string(),
        from: from_addr,
        to: to_addr.clone(),
        subject: req.subject,
        body: req.body,
        thread_id: req.thread_id,
        in_reply_to: req.in_reply_to,
        created_at: chrono::Utc::now().to_rfc3339(),
        attachments: Vec::new(),
        participants: Vec::new(),
        mentions: Vec::new(),
        cc: false,
        kind: req.kind,
        due_at: req.due_at,
        decision_for: req.decision_for,
        outcome: req.outcome,
    };
    envelope.validate().map_err(bad)?;
    let bytes = serde_json::to_vec(&envelope).map_err(|err| bad(err.to_string()))?;
    let mut debug = None;
    if to.domain == app.inner.cfg.domain {
        directory(&app, &to.domain)?
            .resolve_local(&to.domain, &to.segments)
            .map_err(bad)?;
        save(&app, &to_addr, &envelope, false, true)?;
    } else {
        let hit = app.lookup(&to.domain).await.map_err(bad)?;
        let created = chrono::Utc::now().timestamp();
        let signed = app
            .inner
            .identity
            .sign("POST", "/krowmail/v1/inbound", &bytes, created);
        let url = format!("{}/krowmail/v1/inbound", hit.endpoint.trim_end_matches('/'));
        let response = app
            .inner
            .client
            .post(&url)
            .header("content-type", "application/json")
            .header("content-digest", &signed.content_digest)
            .header("signature-input", &signed.signature_input)
            .header("signature", &signed.signature)
            .body(bytes.clone())
            .send()
            .await
            .map_err(|err| bad(err.to_string()))?;
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(bad(format!("对方拒收 {status} {text}")));
        }
        if app.inner.cfg.debug_wire {
            debug = Some(json!({
                "url": url,
                "body": String::from_utf8_lossy(&bytes),
                "content_digest": signed.content_digest,
                "signature_input": signed.signature_input,
                "signature": signed.signature,
            }));
        }
    }
    let mut out = json!({"id": envelope.id, "to": to_addr});
    if let Some(wire) = debug {
        out["debug_wire"] = wire;
    }
    Ok(Json(out))
}

async fn inbound(
    State(app): State<App>,
    headers: HeaderMap,
    body: axum::body::Bytes,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let digest = header(&headers, "content-digest").map_err(unauthorized)?;
    let signature_input = header(&headers, "signature-input").map_err(unauthorized)?;
    let signature = header(&headers, "signature").map_err(unauthorized)?;
    let envelope: Envelope = serde_json::from_slice(&body).map_err(|_| bad("信封不是 JSON"))?;
    envelope.validate().map_err(bad)?;
    let from = parse_open(&envelope.from).map_err(bad)?;
    let to = parse_open(&envelope.to).map_err(bad)?;
    if to.domain != app.inner.cfg.domain {
        return Err(bad("收件域名不是本机"));
    }
    directory(&app, &to.domain)?
        .resolve_local(&to.domain, &to.segments)
        .map_err(bad)?;
    let hit = app.lookup(&from.domain).await.map_err(unauthorized)?;
    if !signature_input.contains(&format!("keyid=\"{}\"", hit.key_id)) {
        return Err(unauthorized("keyid 与域名公钥不一致"));
    }
    verify(
        &hit.public_key,
        "POST",
        "/krowmail/v1/inbound",
        &body,
        &digest,
        &signature_input,
        &signature,
    )
    .map_err(unauthorized)?;
    let quarantine = !hit.registered;
    let wake = hit.registered;
    let mailbox = canonical(&to.segments, &to.domain);
    save(&app, &mailbox, &envelope, quarantine, wake)?;
    Ok(Json(json!({
        "id": envelope.id,
        "quarantine": quarantine,
        "wake": wake,
    })))
}

#[derive(Deserialize)]
struct InboxQuery {
    mailbox: String,
    limit: Option<i64>,
}

async fn inbox(
    State(app): State<App>,
    Query(query): Query<InboxQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let mailbox = canonical_raw(&query.mailbox).map_err(bad)?;
    let limit = query.limit.unwrap_or(20).clamp(1, 100);
    let store = app.inner.store.lock().map_err(|_| bad("存储锁失败"))?;
    let rows = store.list(&mailbox, limit).map_err(bad)?;
    Ok(Json(json!(rows
        .into_iter()
        .map(row_json)
        .collect::<Vec<_>>())))
}

async fn read_message(
    State(app): State<App>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let store = app.inner.store.lock().map_err(|_| bad("存储锁失败"))?;
    let row = store
        .get(&id)
        .map_err(bad)?
        .ok_or_else(|| bad("没有这封信"))?;
    Ok(Json(row_json(row)))
}

impl App {
    async fn lookup(&self, domain: &str) -> Result<DomainHit, String> {
        if domain == self.inner.cfg.domain {
            return Ok(DomainHit {
                endpoint: self.inner.cfg.public_endpoint.clone(),
                public_key: self.inner.identity.public_key_b64(),
                key_id: self.inner.identity.key_id.clone(),
                registered: true,
            });
        }
        if let Some(base) = self.inner.cfg.peers.get(domain) {
            let card = fetch_card(&self.inner.client, base).await?;
            return Ok(DomainHit {
                endpoint: base.clone(),
                public_key: card.public_key,
                key_id: card.key_id,
                registered: self.inner.cfg.trust_peers,
            });
        }
        if let Some(root) = &self.inner.cfg.root {
            let url = format!("{}/v1/domains/{domain}", root.trim_end_matches('/'));
            let response = self
                .inner
                .client
                .get(url)
                .send()
                .await
                .map_err(|err| err.to_string())?;
            if response.status().is_success() {
                let card: Card = response.json().await.map_err(|err| err.to_string())?;
                return Ok(DomainHit {
                    endpoint: card.endpoint,
                    public_key: card.public_key,
                    key_id: card.key_id,
                    registered: card.registered.unwrap_or(true),
                });
            }
        }
        let card = fetch_card(&self.inner.client, &format!("https://{domain}")).await?;
        Ok(DomainHit {
            endpoint: card.endpoint,
            public_key: card.public_key,
            key_id: card.key_id,
            registered: false,
        })
    }
}

#[derive(Deserialize)]
struct Card {
    endpoint: String,
    public_key: String,
    key_id: String,
    #[serde(default)]
    registered: Option<bool>,
}

async fn fetch_card(client: &reqwest::Client, base: &str) -> Result<Card, String> {
    let url = format!("{}/.well-known/krowmail", base.trim_end_matches('/'));
    client
        .get(url)
        .send()
        .await
        .map_err(|err| err.to_string())?
        .json()
        .await
        .map_err(|err| err.to_string())
}

fn directory(app: &App, domain: &str) -> Result<AcceptDirectory, (StatusCode, Json<Value>)> {
    if domain != app.inner.cfg.domain {
        return Ok(AcceptDirectory { segment_count: 3 });
    }
    Ok(AcceptDirectory {
        segment_count: app.inner.cfg.segment_count,
    })
}

fn save(
    app: &App,
    mailbox: &str,
    envelope: &Envelope,
    quarantine: bool,
    wake: bool,
) -> Result<(), (StatusCode, Json<Value>)> {
    let store = app.inner.store.lock().map_err(|_| bad("存储锁失败"))?;
    store
        .insert(
            mailbox,
            &Row {
                envelope: envelope.clone(),
                quarantine,
                wake,
            },
        )
        .map_err(bad)
}

fn row_json(row: Row) -> Value {
    json!({
        "id": row.envelope.id,
        "from": row.envelope.from,
        "to": row.envelope.to,
        "subject": row.envelope.subject,
        "body": row.envelope.body,
        "created_at": row.envelope.created_at,
        "quarantine": row.quarantine,
        "wake": row.wake,
    })
}

fn canonical(segments: &[String], domain: &str) -> String {
    format!("{}@{domain}", segments.join("#"))
}

fn canonical_raw(raw: &str) -> Result<String, String> {
    let open = parse_open(raw)?;
    Ok(canonical(&open.segments, &open.domain))
}

fn header(headers: &HeaderMap, name: &str) -> Result<String, String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
        .ok_or_else(|| format!("缺少 {name}"))
}

fn bad(message: impl Into<String>) -> (StatusCode, Json<Value>) {
    (
        StatusCode::BAD_REQUEST,
        Json(json!({"error": message.into()})),
    )
}

fn unauthorized(message: impl Into<String>) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNAUTHORIZED,
        Json(json!({"error": message.into()})),
    )
}

#[cfg(test)]
mod tests {
    use super::serve;
    use crate::Config;
    use std::collections::BTreeMap;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn two_domains_sign_and_reject_tamper() {
        let a_db = tempfile::NamedTempFile::new().unwrap();
        let b_db = tempfile::NamedTempFile::new().unwrap();
        let listener_a = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listener_b = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port_a = listener_a.local_addr().unwrap().port();
        let port_b = listener_b.local_addr().unwrap().port();
        let url_a = format!("http://127.0.0.1:{port_a}");
        let url_b = format!("http://127.0.0.1:{port_b}");
        let mut peers_a = BTreeMap::new();
        peers_a.insert("beta.test".into(), url_b.clone());
        let mut peers_b = BTreeMap::new();
        peers_b.insert("alpha.test".into(), url_a.clone());
        let cfg = |domain: &str, db: &std::path::Path, endpoint: String, peers| Config {
            domain: domain.into(),
            segment_count: 1,
            db_path: db.to_string_lossy().into(),
            public_endpoint: endpoint,
            root: None,
            peers,
            trust_peers: true,
            debug_wire: true,
        };
        tokio::spawn(serve(
            cfg("alpha.test", a_db.path(), url_a.clone(), peers_a),
            listener_a,
        ));
        tokio::spawn(serve(
            cfg("beta.test", b_db.path(), url_b.clone(), peers_b),
            listener_b,
        ));
        let client = reqwest::Client::new();
        wait_ready(&client, &url_a).await;
        wait_ready(&client, &url_b).await;
        let sent = client
            .post(format!("{url_a}/krowmail/v1/send"))
            .json(&serde_json::json!({
                "from": "ann@alpha.test",
                "to": "bob@beta.test",
                "body": "hello"
            }))
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap()
            .json::<serde_json::Value>()
            .await
            .unwrap();
        let inbox = client
            .get(format!("{url_b}/krowmail/v1/inbox"))
            .query(&[("mailbox", "bob@beta.test")])
            .send()
            .await
            .unwrap()
            .json::<serde_json::Value>()
            .await
            .unwrap();
        assert_eq!(inbox[0]["body"], "hello");
        assert_eq!(inbox[0]["wake"], true);
        let wire = &sent["debug_wire"];
        let tampered = wire["body"]
            .as_str()
            .unwrap()
            .replace("hello", "hellp")
            .into_bytes();
        let rejected = client
            .post(format!("{url_b}/krowmail/v1/inbound"))
            .header("content-type", "application/json")
            .header("content-digest", wire["content_digest"].as_str().unwrap())
            .header("signature-input", wire["signature_input"].as_str().unwrap())
            .header("signature", wire["signature"].as_str().unwrap())
            .body(tampered)
            .send()
            .await
            .unwrap();
        assert_eq!(rejected.status(), reqwest::StatusCode::UNAUTHORIZED);
    }

    async fn wait_ready(client: &reqwest::Client, base: &str) {
        for _ in 0..50 {
            if client
                .get(format!("{base}/healthz"))
                .send()
                .await
                .ok()
                .is_some_and(|response| response.status().is_success())
            {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
        panic!("server {base} did not start");
    }
}
