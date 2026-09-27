use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use ed25519_dalek::{Signer, SigningKey, Verifier, VerifyingKey};
use rand::rngs::OsRng;
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignedHeaders {
    pub content_digest: String,
    pub signature_input: String,
    pub signature: String,
}

pub struct Identity {
    pub key_id: String,
    signing: SigningKey,
}

impl Identity {
    pub fn generate(domain: &str, kid: &str) -> Self {
        Self::from_seed(domain, kid, SigningKey::generate(&mut OsRng).to_bytes())
    }

    pub fn from_seed(domain: &str, kid: &str, seed: [u8; 32]) -> Self {
        Self {
            key_id: format!("{domain}/{kid}"),
            signing: SigningKey::from_bytes(&seed),
        }
    }

    pub fn to_seed(&self) -> [u8; 32] {
        self.signing.to_bytes()
    }

    pub fn public_key_b64(&self) -> String {
        STANDARD.encode(self.signing.verifying_key().to_bytes())
    }

    pub fn sign(&self, method: &str, path: &str, body: &[u8], created: i64) -> SignedHeaders {
        let digest = content_digest(body);
        let params = signature_params(created, &self.key_id);
        let base = signing_base(method, path, &digest, &params);
        let sig = self.signing.sign(base.as_bytes());
        SignedHeaders {
            content_digest: digest,
            signature_input: format!("sig1={params}"),
            signature: format!("sig1=:{}:", STANDARD.encode(sig.to_bytes())),
        }
    }
}

pub fn content_digest(body: &[u8]) -> String {
    format!("sha-256=:{}:", STANDARD.encode(Sha256::digest(body)))
}

pub fn verify(
    public_key_b64: &str,
    method: &str,
    path: &str,
    body: &[u8],
    content_digest_header: &str,
    signature_input: &str,
    signature: &str,
) -> Result<(), String> {
    let digest = content_digest(body);
    if content_digest_header.trim() != digest {
        return Err("内容摘要不一致".into());
    }
    let params = signature_input
        .trim()
        .strip_prefix("sig1=")
        .ok_or("Signature-Input 缺少 sig1")?;
    let created = param_i64(params, "created")?;
    let key_id = param_string(params, "keyid")?;
    let expected_params = signature_params(created, &key_id);
    if params != expected_params {
        return Err("签名参数与约定子集不一致".into());
    }
    let raw_sig = signature
        .trim()
        .strip_prefix("sig1=:")
        .and_then(|rest| rest.strip_suffix(':'))
        .ok_or("Signature 格式不正确")?;
    let sig_bytes = STANDARD
        .decode(raw_sig)
        .map_err(|_| "签名不是合法 base64")?;
    let sig = ed25519_dalek::Signature::from_slice(&sig_bytes).map_err(|_| "签名长度不正确")?;
    let pk_bytes = STANDARD
        .decode(public_key_b64.trim())
        .map_err(|_| "公钥不是合法 base64")?;
    let pk_array: [u8; 32] = pk_bytes
        .as_slice()
        .try_into()
        .map_err(|_| "公钥长度不正确")?;
    let pk = VerifyingKey::from_bytes(&pk_array).map_err(|_| "公钥不正确")?;
    let base = signing_base(method, path, &digest, params);
    pk.verify(base.as_bytes(), &sig)
        .map_err(|_| "验签失败".to_string())
}

fn signature_params(created: i64, key_id: &str) -> String {
    format!("(\"@method\" \"@path\" \"content-digest\");created={created};keyid=\"{key_id}\"")
}

fn signing_base(method: &str, path: &str, digest: &str, params: &str) -> String {
    format!(
        "\"@method\": {method}\n\"@path\": {path}\n\"content-digest\": {digest}\n\"@signature-params\": {params}"
    )
}

fn param_i64(params: &str, name: &str) -> Result<i64, String> {
    let key = format!("{name}=");
    let rest = params
        .split(';')
        .find_map(|part| part.strip_prefix(&key))
        .ok_or_else(|| format!("缺少 {name}"))?;
    rest.parse().map_err(|_| format!("{name} 不是整数"))
}

fn param_string(params: &str, name: &str) -> Result<String, String> {
    let key = format!("{name}=\"");
    let rest = params
        .split(';')
        .find_map(|part| part.strip_prefix(&key))
        .ok_or_else(|| format!("缺少 {name}"))?;
    rest.strip_suffix('"')
        .map(str::to_string)
        .ok_or_else(|| format!("{name} 缺少引号"))
}

#[cfg(test)]
mod tests {
    use super::{verify, Identity};

    #[test]
    fn round_trip_and_tamper() {
        let id = Identity::generate("lab.test", "k1");
        let body = br#"{"body":"hello"}"#;
        let headers = id.sign("POST", "/krowmail/v1/inbound", body, 1_700_000_000);
        assert!(verify(
            &id.public_key_b64(),
            "POST",
            "/krowmail/v1/inbound",
            body,
            &headers.content_digest,
            &headers.signature_input,
            &headers.signature,
        )
        .is_ok());
        let tampered = br#"{"body":"hello!"}"#;
        assert!(verify(
            &id.public_key_b64(),
            "POST",
            "/krowmail/v1/inbound",
            tampered,
            &headers.content_digest,
            &headers.signature_input,
            &headers.signature,
        )
        .is_err());
    }
}
