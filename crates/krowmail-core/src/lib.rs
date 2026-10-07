//! 地址、信封、来信策略和域名签名。不含数据库。

mod address;
mod envelope;
mod policy;
mod sign;
mod traits;

pub use address::{
    display_name_banned, fold_key, parse_open, parse_shorthand, parse_syntax,
    validate_address_name, validate_user_handle, LegacyAddress, OpenAddress, Syntax,
};
pub use envelope::{
    Attachment, Envelope, Participant, ENVELOPE_KINDS, ENVELOPE_OUTCOMES, MAX_CC,
    MAX_ENVELOPE_MENTIONS, MAX_ENVELOPE_PARTICIPANTS,
};
pub use policy::{
    decide, CrossDecision, CrossInput, DefaultPolicy, MailPolicy, Policy,
    CROSS_TEAM_WINDOW_MINUTES, MAX_CROSS_TEAM_SENDS, MAX_DAILY_OWNER_PAIR, MAX_HOURLY_EXTERNAL,
};
pub use sign::{content_digest, verify, Identity, SignedHeaders};
pub use traits::{
    AcceptDirectory, DeliveryHook, Directory, DomainRecord, InMemoryStore, MailStore, MailboxRef,
    RootResolver, StoredLetter,
};
