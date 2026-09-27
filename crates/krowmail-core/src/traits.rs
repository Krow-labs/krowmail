use crate::envelope::Envelope;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MailboxRef {
    pub address: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredLetter {
    pub envelope: Envelope,
    pub quarantine: bool,
    pub wake: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DomainRecord {
    pub domain: String,
    pub endpoint: String,
    pub public_key: String,
    pub key_id: String,
    pub segment_count: u8,
    pub reputation: i32,
    pub registered: bool,
}

pub trait Directory {
    fn resolve_local(&self, domain: &str, segments: &[String]) -> Result<MailboxRef, String>;
}

pub trait MailStore {
    fn put(&mut self, letter: &StoredLetter) -> Result<(), String>;
    fn list(&self, mailbox: &str, limit: usize) -> Result<Vec<StoredLetter>, String>;
    fn get(&self, id: &str) -> Result<Option<StoredLetter>, String>;
}

pub trait DeliveryHook {
    fn on_deliver(&mut self, letter: &StoredLetter);
}

pub trait RootResolver {
    fn lookup(&self, domain: &str) -> Result<Option<DomainRecord>, String>;
}

pub struct AcceptDirectory {
    pub segment_count: u8,
}

impl Directory for AcceptDirectory {
    fn resolve_local(&self, domain: &str, segments: &[String]) -> Result<MailboxRef, String> {
        if segments.len() != usize::from(self.segment_count) {
            return Err(format!("本域名登记为 {} 段", self.segment_count));
        }
        Ok(MailboxRef {
            address: format!("{}@{domain}", segments.join("#")),
        })
    }
}

#[derive(Default)]
pub struct InMemoryStore {
    letters: Vec<StoredLetter>,
}

impl MailStore for InMemoryStore {
    fn put(&mut self, letter: &StoredLetter) -> Result<(), String> {
        if self
            .letters
            .iter()
            .any(|row| row.envelope.id == letter.envelope.id)
        {
            return Err("信件 id 已存在".into());
        }
        self.letters.push(letter.clone());
        Ok(())
    }

    fn list(&self, mailbox: &str, limit: usize) -> Result<Vec<StoredLetter>, String> {
        let rows: Vec<_> = self
            .letters
            .iter()
            .rev()
            .filter(|row| row.envelope.to == mailbox)
            .take(limit)
            .cloned()
            .collect();
        Ok(rows)
    }

    fn get(&self, id: &str) -> Result<Option<StoredLetter>, String> {
        Ok(self
            .letters
            .iter()
            .find(|row| row.envelope.id == id)
            .cloned())
    }
}
