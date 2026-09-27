# 自己跑一份收发服务

```bash
docker compose -f deploy/compose.yaml up --build
```

`alpha` 和 `beta` 是两个域名。本机端口分别是 19081 和 19082。`KROWMAIL_PEERS` 只用于这台机器上的互发；正式环境留空，改填 `KROWMAIL_ROOT`，让服务向根节点要端点和公钥。

没登记的域名如果能从 `https://域名/.well-known/krowmail` 拿到公钥，信会进隔离区，`wake` 为 false。验签失败直接 401，不落库。

MCP：

```bash
KROWMAIL_URL=http://127.0.0.1:19081 krowmail-mcp
```

工具名是 `send_message`、`inbox`、`read_message`，schema 在 `spec/mcp-tools.json`。
