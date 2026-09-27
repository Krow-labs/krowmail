use krowmail_core::{Envelope, Identity};
use rusqlite::{params, Connection};

pub struct Store {
    conn: Connection,
}

#[derive(Debug, Clone)]
pub struct Row {
    pub envelope: Envelope,
    pub quarantine: bool,
    pub wake: bool,
}

impl Store {
    pub fn open(path: &str) -> Result<Self, String> {
        let conn = Connection::open(path).map_err(|err| err.to_string())?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
             CREATE TABLE IF NOT EXISTS messages (
               id TEXT PRIMARY KEY,
               mailbox TEXT NOT NULL,
               envelope TEXT NOT NULL,
               quarantine INTEGER NOT NULL,
               wake INTEGER NOT NULL,
               created_at TEXT NOT NULL
             );",
        )
        .map_err(|err| err.to_string())?;
        Ok(Self { conn })
    }

    pub fn identity(&self, domain: &str) -> Result<Identity, String> {
        let existing: Option<String> = self
            .conn
            .query_row("SELECT value FROM meta WHERE key = 'seed'", [], |row| {
                row.get(0)
            })
            .ok();
        if let Some(hex_seed) = existing {
            let seed = decode_seed(&hex_seed)?;
            return Ok(Identity::from_seed(domain, "k1", seed));
        }
        let fresh = Identity::generate(domain, "k1");
        self.conn
            .execute(
                "INSERT INTO meta (key, value) VALUES ('seed', ?1)",
                params![encode_seed(&fresh.to_seed())],
            )
            .map_err(|err| err.to_string())?;
        Ok(fresh)
    }

    pub fn insert(&self, mailbox: &str, row: &Row) -> Result<(), String> {
        let envelope = serde_json::to_string(&row.envelope).map_err(|err| err.to_string())?;
        self.conn
            .execute(
                "INSERT INTO messages (id, mailbox, envelope, quarantine, wake, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    row.envelope.id,
                    mailbox,
                    envelope,
                    i64::from(row.quarantine),
                    i64::from(row.wake),
                    row.envelope.created_at,
                ],
            )
            .map_err(|err| err.to_string())?;
        Ok(())
    }

    pub fn list(&self, mailbox: &str, limit: i64) -> Result<Vec<Row>, String> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT envelope, quarantine, wake FROM messages
                 WHERE mailbox = ?1 ORDER BY created_at DESC LIMIT ?2",
            )
            .map_err(|err| err.to_string())?;
        let rows = stmt
            .query_map(params![mailbox, limit], read_row)
            .map_err(|err| err.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|err| err.to_string())
    }

    pub fn get(&self, id: &str) -> Result<Option<Row>, String> {
        let mut stmt = self
            .conn
            .prepare("SELECT envelope, quarantine, wake FROM messages WHERE id = ?1")
            .map_err(|err| err.to_string())?;
        let mut rows = stmt
            .query_map(params![id], read_row)
            .map_err(|err| err.to_string())?;
        match rows.next() {
            Some(row) => row.map(Some).map_err(|err| err.to_string()),
            None => Ok(None),
        }
    }
}

fn read_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Row> {
    let envelope: String = row.get(0)?;
    let quarantine: i64 = row.get(1)?;
    let wake: i64 = row.get(2)?;
    let envelope: Envelope = serde_json::from_str(&envelope).map_err(|err| {
        rusqlite::Error::FromSqlConversionFailure(0, rusqlite::types::Type::Text, Box::new(err))
    })?;
    Ok(Row {
        envelope,
        quarantine: quarantine != 0,
        wake: wake != 0,
    })
}

fn encode_seed(seed: &[u8; 32]) -> String {
    seed.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn decode_seed(hex_seed: &str) -> Result<[u8; 32], String> {
    if hex_seed.len() != 64 {
        return Err("种子长度不正确".into());
    }
    let mut seed = [0u8; 32];
    for (index, chunk) in hex_seed.as_bytes().chunks(2).enumerate() {
        let text = std::str::from_utf8(chunk).map_err(|_| "种子不是十六进制")?;
        seed[index] = u8::from_str_radix(text, 16).map_err(|_| "种子不是十六进制")?;
    }
    Ok(seed)
}
