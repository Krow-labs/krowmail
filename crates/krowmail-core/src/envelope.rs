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

/// 协议位闭集（0.3.0）。与 `spec/envelope.schema.json` 里 `kind.enum` 同值、同序。
/// 缺省（线上不出现）= 普通信。不认识的收件方按普通信处理——所以它只能是可选字段。
pub const ENVELOPE_KINDS: [&str; 4] = ["ack", "close", "request", "decision"];
/// 结局闭集（0.3.0）。与 `spec/envelope.schema.json` 里 `outcome.enum` 同值、同序。
pub const ENVELOPE_OUTCOMES: [&str; 5] = ["done", "declined", "needs_info", "expired", "withdrawn"];

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
    /// 协议位（0.3.0）：`ack` / `close` / `request` / `decision`，见 [`ENVELOPE_KINDS`]。空 = 普通信。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    /// 仅 `kind=request`：请求方期望收到结局的时刻（RFC 3339）。是期望不是强制。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub due_at: Option<String>,
    /// 仅 `kind=decision`：被收尾的那封 request 信封的 id。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decision_for: Option<String>,
    /// 仅 `kind=decision`：结局，见 [`ENVELOPE_OUTCOMES`]。
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outcome: Option<String>,
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
        // 协议位（0.3.0）：闭集之外拒收；伴随字段只能跟着对应的 kind 出现，
        // 否则两端对「这是不是请求 / 结局」会有不同理解。
        let kind = self.kind.as_deref().filter(|k| !k.is_empty());
        if let Some(k) = kind {
            if !ENVELOPE_KINDS.contains(&k) {
                return Err(format!("信封 kind 只能是 {}", ENVELOPE_KINDS.join(" / ")));
            }
        }
        if self.due_at.as_deref().is_some_and(|d| !d.is_empty()) && kind != Some("request") {
            return Err("信封 due_at 只能跟着 kind=request".into());
        }
        let has_decision_for = self.decision_for.as_deref().is_some_and(|d| !d.is_empty());
        let outcome = self.outcome.as_deref().filter(|o| !o.is_empty());
        if kind == Some("decision") {
            if !has_decision_for {
                return Err(
                    "信封 kind=decision 必须带 decision_for（被收尾的 request 信封 id）".into(),
                );
            }
            match outcome {
                Some(o) if ENVELOPE_OUTCOMES.contains(&o) => {}
                Some(_) => {
                    return Err(format!(
                        "信封 outcome 只能是 {}",
                        ENVELOPE_OUTCOMES.join(" / ")
                    ))
                }
                None => return Err("信封 kind=decision 必须带 outcome".into()),
            }
        } else if has_decision_for || outcome.is_some() {
            return Err("信封 decision_for / outcome 只能跟着 kind=decision".into());
        }
        Ok(())
    }

    /// 协议位（空串视同没有）。
    pub fn kind(&self) -> Option<&str> {
        self.kind.as_deref().filter(|k| !k.is_empty())
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
            kind: None,
            due_at: None,
            decision_for: None,
            outcome: None,
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

    #[test]
    fn protocol_bits_are_optional_on_the_wire_and_validated() {
        // 普通信：四个字段都不上线。
        let wire = serde_json::to_value(base()).unwrap();
        for key in ["kind", "due_at", "decision_for", "outcome"] {
            assert!(wire.get(key).is_none(), "{key} 不该出现在普通信里");
        }
        // 老对端发来的信（没有这些字段）照常解析成普通信。
        let parsed: Envelope = serde_json::from_str(
            r#"{"id":"e","from":"a#x#1@a.test","to":"b#y#2@b.test","body":"hi","created_at":"t"}"#,
        )
        .unwrap();
        assert!(parsed.kind().is_none() && parsed.validate().is_ok());

        let mut request = base();
        request.kind = Some("request".into());
        request.due_at = Some("2026-10-09T06:00:00Z".into());
        assert!(request.validate().is_ok());
        let back: Envelope =
            serde_json::from_str(&serde_json::to_string(&request).unwrap()).unwrap();
        assert_eq!(back, request);
        assert_eq!(back.kind(), Some("request"));

        let mut decision = base();
        decision.kind = Some("decision".into());
        decision.decision_for = Some("e-request".into());
        decision.outcome = Some("declined".into());
        assert!(decision.validate().is_ok());

        let mut bad_kind = base();
        bad_kind.kind = Some("urgent".into());
        assert!(bad_kind.validate().is_err());
        let mut stray_due = base();
        stray_due.due_at = Some("2026-10-09T06:00:00Z".into());
        assert!(stray_due.validate().is_err());
        let mut ack_with_due = base();
        ack_with_due.kind = Some("ack".into());
        ack_with_due.due_at = Some("t".into());
        assert!(ack_with_due.validate().is_err());
        let mut decision_without_target = base();
        decision_without_target.kind = Some("decision".into());
        decision_without_target.outcome = Some("done".into());
        assert!(decision_without_target.validate().is_err());
        let mut decision_bad_outcome = base();
        decision_bad_outcome.kind = Some("decision".into());
        decision_bad_outcome.decision_for = Some("e".into());
        decision_bad_outcome.outcome = Some("maybe".into());
        assert!(decision_bad_outcome.validate().is_err());
        let mut stray_outcome = base();
        stray_outcome.outcome = Some("done".into());
        assert!(stray_outcome.validate().is_err());
        // 空串视同没有。
        let mut empty = base();
        empty.kind = Some(String::new());
        assert!(empty.validate().is_ok() && empty.kind().is_none());
    }
}
