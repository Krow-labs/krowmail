use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Attachment {
    pub name: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub href: Option<String>,
}

/// 在场者卡片：谁在这封信里。`role` 是 `to` 或 `cc`；提及（`mentions`）复用同一形状，
/// 但只是暴露给读信端的卡片，不投递。地址必须是完整的开放地址（带 `@域名`）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Participant {
    pub address: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub role: String,
}

/// 一封信最多抄送的人数。超级节点靠廉价广播边形成，协议上不给。
pub const MAX_CC: usize = 5;
/// 一封信最多的在场者数：主收件人 1 + 抄送 [`MAX_CC`]。与 `spec/envelope.schema.json`
/// 里 `participants.maxItems` 同值。
pub const MAX_ENVELOPE_PARTICIPANTS: usize = MAX_CC + 1;
/// 一封信最多随带的提及卡片数。与 `spec/envelope.schema.json` 里 `mentions.maxItems` 同值。
pub const MAX_ENVELOPE_MENTIONS: usize = 10;

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
    /// 在场者（主收件人 + 抄送）。空 = 单收件人，线上不出现。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub participants: Vec<Participant>,
    /// 正文里 `@地址` 抽出的卡片（只暴露，不投递）。空时线上不出现。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub mentions: Vec<Participant>,
    /// 这一份是抄送副本（收件人不是主收件人）。false 时线上不出现。
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub cc: bool,
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
        // 卡片闭集：人数与抄送上限同口径，防对端用信封当广播载体。
        if self.participants.len() > MAX_ENVELOPE_PARTICIPANTS {
            return Err(format!("信封在场者超过 {MAX_ENVELOPE_PARTICIPANTS} 人"));
        }
        if self.mentions.len() > MAX_ENVELOPE_MENTIONS {
            return Err(format!("信封提及超过 {MAX_ENVELOPE_MENTIONS} 个"));
        }
        if self
            .participants
            .iter()
            .chain(self.mentions.iter())
            .any(|p| !p.address.contains('@'))
        {
            return Err("信封卡片地址缺少 @".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn base() -> Envelope {
        Envelope {
            id: "e1".into(),
            from: "a#x#1@a.test".into(),
            to: "b#y#2@b.test".into(),
            subject: String::new(),
            body: "hi".into(),
            thread_id: None,
            in_reply_to: None,
            created_at: "2026-10-06T00:00:00Z".into(),
            attachments: Vec::new(),
            participants: Vec::new(),
            mentions: Vec::new(),
            cc: false,
        }
    }

    #[test]
    fn social_fields_are_optional_on_the_wire_and_bounded() {
        let wire = serde_json::to_value(base()).unwrap();
        assert!(wire.get("participants").is_none() && wire.get("cc").is_none());
        let parsed: Envelope = serde_json::from_str(
            r#"{"id":"e","from":"a#x#1@a.test","to":"b#y#2@b.test","body":"hi","created_at":"t"}"#,
        )
        .unwrap();
        assert!(parsed.participants.is_empty() && !parsed.cc);
        let mut too_many = base();
        too_many.participants = (0..MAX_ENVELOPE_PARTICIPANTS + 1)
            .map(|i| Participant {
                address: format!("p{i}#t#1@a.test"),
                name: String::new(),
                role: "cc".into(),
            })
            .collect();
        assert!(too_many.validate().is_err());
        let mut bad_addr = base();
        bad_addr.mentions.push(Participant {
            address: "no-at".into(),
            name: String::new(),
            role: String::new(),
        });
        assert!(bad_addr.validate().is_err());
        assert!(base().validate().is_ok());
    }

    #[test]
    fn cc_copy_round_trips_with_cards() {
        let mut copy = base();
        copy.cc = true;
        copy.participants = vec![
            Participant {
                address: "b#y#2@b.test".into(),
                name: "乙".into(),
                role: "to".into(),
            },
            Participant {
                address: "c#z#3@c.test".into(),
                name: String::new(),
                role: "cc".into(),
            },
        ];
        let wire = serde_json::to_string(&copy).unwrap();
        assert!(wire.contains("\"cc\":true") && wire.contains("\"participants\""));
        let back: Envelope = serde_json::from_str(&wire).unwrap();
        assert_eq!(back, copy);
        assert!(back.validate().is_ok());
    }
}
