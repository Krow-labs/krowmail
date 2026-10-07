use std::io::{BufRead, Write};

fn main() {
    let url = std::env::var("KROWMAIL_URL").unwrap_or_else(|_| "http://127.0.0.1:8080".into());
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .expect("http client");
    let tools: serde_json::Value =
        serde_json::from_str(include_str!("../../../spec/mcp-tools.json")).expect("mcp schema");
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) => line,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let req: serde_json::Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(err) => {
                reply(None, serde_json::json!({"error": err.to_string()}), true);
                continue;
            }
        };
        if req["id"].is_null() {
            continue;
        }
        let id = req.get("id").cloned();
        let method = req["method"].as_str().unwrap_or("");
        let result = match method {
            "initialize" => serde_json::json!({
                "protocolVersion": "2024-11-05",
                "capabilities": { "tools": {} },
                "serverInfo": { "name": "krowmail-mcp", "version": env!("CARGO_PKG_VERSION") }
            }),
            "tools/list" => serde_json::json!({ "tools": tools["tools"] }),
            "tools/call" => match call_tool(&client, &url, &req["params"]) {
                Ok(text) => serde_json::json!({
                    "content": [{ "type": "text", "text": text }],
                    "isError": false
                }),
                Err(err) => serde_json::json!({
                    "content": [{ "type": "text", "text": err }],
                    "isError": true
                }),
            },
            _ => {
                write_rpc(&serde_json::json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32601, "message": "method not found" }
                }));
                continue;
            }
        };
        write_rpc(&serde_json::json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": result
        }));
    }
}

fn call_tool(
    client: &reqwest::blocking::Client,
    base: &str,
    params: &serde_json::Value,
) -> Result<String, String> {
    let name = params["name"].as_str().ok_or("缺少工具名")?;
    let args = &params["arguments"];
    let response = match name {
        "send_message" => client
            .post(format!("{base}/krowmail/v1/send"))
            .json(args)
            .send()
            .map_err(|err| err.to_string())?,
        "inbox" => {
            let mailbox = args["mailbox"].as_str().ok_or("缺少 mailbox")?;
            let limit = args["limit"].as_i64().unwrap_or(20);
            client
                .get(format!("{base}/krowmail/v1/inbox"))
                .query(&[("mailbox", mailbox), ("limit", &limit.to_string())])
                .send()
                .map_err(|err| err.to_string())?
        }
        "read_message" => {
            let id = args["id"].as_str().ok_or("缺少 id")?;
            client
                .get(format!("{base}/krowmail/v1/messages/{id}"))
                .send()
                .map_err(|err| err.to_string())?
        }
        other => return Err(format!("未知工具 {other}")),
    };
    let status = response.status();
    let text = response.text().unwrap_or_default();
    if !status.is_success() {
        return Err(format!("{status} {text}"));
    }
    Ok(text)
}

fn reply(id: Option<serde_json::Value>, message: serde_json::Value, is_error: bool) {
    write_rpc(&serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "result": {
            "content": [{ "type": "text", "text": message }],
            "isError": is_error
        }
    }));
}

fn write_rpc(value: &serde_json::Value) {
    let mut out = std::io::stdout().lock();
    writeln!(out, "{value}").ok();
    out.flush().ok();
}
