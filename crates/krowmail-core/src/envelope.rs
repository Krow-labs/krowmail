use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attachment {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub href: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Envelope {
    pub id: String,
    pub from: String,
    pub to: String,
    #[serde(default)]
    pub subject: String,
    pub body: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thread_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub in_reply_to: Option<String>,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub attachments: Vec<Attachment>,
}

impl Envelope {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty()
            || self.from.is_empty()
            || self.to.is_empty()
            || self.created_at.is_empty()
        {
            return Err("信封缺少必填字段".into());
        }
        if !self.from.contains('@') || !self.to.contains('@') {
            return Err("信封地址缺少 @".into());
        }
        Ok(())
    }
}
