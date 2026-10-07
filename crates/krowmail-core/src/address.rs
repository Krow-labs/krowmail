use uuid::Uuid;

const RESERVED_HANDLES: &[&str] = &[
    "krow",
    "admin",
    "administrator",
    "support",
    "root",
    "system",
    "mail",
    "postmaster",
    "abuse",
    "security",
    "official",
    "noreply",
    "hostmaster",
    "webmaster",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LegacyAddress {
    pub user: Uuid,
    pub team: Uuid,
    pub member: Uuid,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Syntax {
    Legacy(LegacyAddress),
    Friendly {
        member: String,
        team: String,
        owner: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenAddress {
    pub segments: Vec<String>,
    pub domain: String,
}

pub fn fold_key(raw: &str) -> Option<String> {
    let mut out = String::new();
    for ch in raw.chars() {
        let cp = ch as u32;
        if matches!(cp, 0x200B | 0x200C | 0x200D | 0xFEFF | 0x2060)
            || (0x202A..=0x202E).contains(&cp)
            || (0x2066..=0x2069).contains(&cp)
        {
            return None;
        }
        let mapped = if (0xFF01..=0xFF5E).contains(&cp) {
            char::from_u32(cp - 0xFEE0).unwrap_or(ch)
        } else if ch == '\u{3000}' {
            ' '
        } else {
            ch
        };
        out.push(mapped);
    }
    let folded = out.trim().to_lowercase();
    if folded.is_empty() {
        None
    } else {
        Some(folded)
    }
}

pub fn display_name_banned(raw: &str) -> bool {
    raw.chars().any(|ch| {
        let cp = ch as u32;
        let mapped = if (0xFF01..=0xFF5E).contains(&cp) {
            char::from_u32(cp - 0xFEE0).unwrap_or(ch)
        } else {
            ch
        };
        mapped == '@' || mapped == '#'
    })
}

pub fn validate_address_name(raw: &str) -> Result<(), &'static str> {
    let key = fold_key(raw).ok_or("地址名不能包含零宽字符或双向控制字符")?;
    if key.chars().count() > 32 {
        return Err("地址名最长 32 个字符");
    }
    if key.chars().all(|ch| ch.is_ascii_digit()) {
        return Err("地址名不能是纯数字，纯数字留给自动编号");
    }
    if !key
        .chars()
        .all(|ch| ch.is_alphanumeric() || matches!(ch, '_' | '.' | '-'))
    {
        return Err("地址名只能用中文、字母、数字和 - _ .");
    }
    Ok(())
}

pub fn validate_user_handle(raw: &str) -> Result<(), &'static str> {
    validate_address_name(raw)?;
    let key = fold_key(raw).ok_or("地址名不能包含零宽字符或双向控制字符")?;
    if RESERVED_HANDLES.contains(&key.as_str()) {
        return Err("这个地址名是保留字，不能注册");
    }
    Ok(())
}

/// `krow.cn` 的三段解析，并兼容该域名的旧 `krow:` 本地扩展。
pub fn parse_syntax(raw: &str, domain: &str) -> Result<Syntax, String> {
    let text = strip_wrappers(raw)?;
    if let Some(rest) = text
        .get(..5)
        .filter(|p| p.eq_ignore_ascii_case("krow:"))
        .map(|_| &text[5..])
    {
        return parse_legacy(rest);
    }
    let open = parse_folded(&text)?;
    if open.segments.len() != 3 {
        return Err("地址应是 组员#小组#主人@域名".into());
    }
    let expected = fold_key(domain).unwrap_or_else(|| domain.to_lowercase());
    if open.domain != expected {
        return Err(format!("域名不是 {domain}"));
    }
    Ok(Syntax::Friendly {
        member: open.segments[0].clone(),
        team: open.segments[1].clone(),
        owner: open.segments[2].clone(),
    })
}

/// 同主人简写（`krow.cn` profile，不在公共语法里）：`组员#小组` 或 `组员#小组@本域名`。
/// 省掉最外层的主人段，由调用方按**发件人自己的主人**补全成三段完整地址——补全发生在
/// 入口侧，信封里的 `from` / `to` 永远是完整地址，其它域名不必实现。只认两段：一段（裸名）
/// 留给调用方按名字解析；三段是完整地址走 [`parse_syntax`]。带了别的域名不算简写
/// （返回 `None`，让完整语法去报「域名不是 …」）。折叠规则与完整语法同一套。
pub fn parse_shorthand(raw: &str, domain: &str) -> Option<(String, String)> {
    let text = strip_wrappers(raw).ok()?;
    if text
        .get(..5)
        .is_some_and(|p| p.eq_ignore_ascii_case("krow:"))
    {
        return None;
    }
    let folded = fold_separators(&text);
    let local = match folded.rsplit_once('@') {
        Some((local, dom)) => {
            let expected = fold_key(domain).unwrap_or_else(|| domain.to_lowercase());
            if fold_key(dom).unwrap_or_default() != expected {
                return None;
            }
            local.to_string()
        }
        None => folded,
    };
    let segments: Vec<&str> = local.split('#').map(str::trim).collect();
    if segments.len() != 2 || segments.iter().any(|s| s.is_empty()) {
        return None;
    }
    Some((segments[0].to_string(), segments[1].to_string()))
}

/// 公共语法：1 到 3 段，不限定域名。`krowmail:` 里的 `#` 必须先写成 `%23`。
pub fn parse_open(raw: &str) -> Result<OpenAddress, String> {
    let text = strip_wrappers(raw)?;
    if text
        .get(..5)
        .is_some_and(|p| p.eq_ignore_ascii_case("krow:"))
    {
        return Err("krow: 是 krow.cn 的本地扩展，不在公共语法里".into());
    }
    let open = parse_folded(&text)?;
    if open.segments.is_empty() || open.segments.len() > 3 {
        return Err("本地部分只能有 1 到 3 段".into());
    }
    Ok(open)
}

fn strip_wrappers(raw: &str) -> Result<String, String> {
    let mut text = raw.trim();
    if let Some(rest) = text
        .get(..7)
        .filter(|p| p.eq_ignore_ascii_case("mailto:"))
        .map(|_| &text[7..])
    {
        text = rest.trim();
    }
    if text.starts_with('<') && text.ends_with('>') && text.len() >= 2 {
        text = text[1..text.len() - 1].trim();
    }
    if let Some(rest) = text
        .get(..9)
        .filter(|p| p.eq_ignore_ascii_case("krowmail:"))
        .map(|_| &text[9..])
    {
        return percent_decode(rest.trim());
    }
    Ok(text.to_string())
}

fn parse_legacy(rest: &str) -> Result<Syntax, String> {
    let mut parts = rest.split('/');
    let user = parts
        .next()
        .and_then(|s| Uuid::parse_str(s.trim()).ok())
        .ok_or_else(|| "旧地址的主人 id 不是合法 UUID".to_string())?;
    let team = parts
        .next()
        .and_then(|s| Uuid::parse_str(s.trim()).ok())
        .ok_or_else(|| "旧地址的小组 id 不是合法 UUID".to_string())?;
    let member = parts
        .next()
        .and_then(|s| Uuid::parse_str(s.trim()).ok())
        .ok_or_else(|| "旧地址的组员 id 不是合法 UUID".to_string())?;
    if parts.next().is_some() {
        return Err("旧地址只能有三段 UUID".into());
    }
    Ok(Syntax::Legacy(LegacyAddress { user, team, member }))
}

fn parse_folded(text: &str) -> Result<OpenAddress, String> {
    let folded = fold_separators(text);
    let (local, dom) = folded
        .rsplit_once('@')
        .ok_or_else(|| "地址里没有 @".to_string())?;
    let domain = fold_key(dom).unwrap_or_default();
    if domain.is_empty() || domain.contains(' ') {
        return Err("域名不合法".into());
    }
    let segments: Vec<String> = local
        .split('#')
        .map(str::trim)
        .map(str::to_string)
        .collect();
    if segments.iter().any(String::is_empty) {
        return Err("地址的每一段都不能为空".into());
    }
    Ok(OpenAddress { segments, domain })
}

fn fold_separators(raw: &str) -> String {
    raw.chars()
        .map(|ch| {
            let cp = ch as u32;
            if (0xFF01..=0xFF5E).contains(&cp) {
                char::from_u32(cp - 0xFEE0).unwrap_or(ch)
            } else {
                ch
            }
        })
        .collect()
}

fn percent_decode(raw: &str) -> Result<String, String> {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            if i + 2 >= bytes.len() {
                return Err("百分号编码不完整".into());
            }
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).map_err(|_| "百分号编码不完整")?;
            let value = u8::from_str_radix(hex, 16).map_err(|_| "百分号编码不完整".to_string())?;
            out.push(value);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).map_err(|_| "百分号编码不是 UTF-8".into())
}

#[cfg(test)]
mod shorthand_tests {
    use super::*;

    #[test]
    fn two_segments_without_domain_is_shorthand() {
        assert_eq!(
            parse_shorthand("东坡#人间词话", "krow.cn"),
            Some(("东坡".into(), "人间词话".into()))
        );
        // 全角 # / 首尾空白 / 包裹符都按完整语法同一套折叠
        assert_eq!(
            parse_shorthand("  <东坡＃人间词话>  ", "krow.cn"),
            Some(("东坡".into(), "人间词话".into()))
        );
    }

    #[test]
    fn two_segments_with_own_domain_is_shorthand_other_domain_is_not() {
        assert_eq!(
            parse_shorthand("东坡#人间词话@krow.cn", "krow.cn"),
            Some(("东坡".into(), "人间词话".into()))
        );
        assert!(parse_shorthand("东坡#人间词话@KROW.CN", "krow.cn").is_some());
        assert_eq!(
            parse_shorthand("东坡#人间词话@elsewhere.example", "krow.cn"),
            None
        );
    }

    #[test]
    fn one_or_three_segments_and_legacy_are_not_shorthand() {
        assert_eq!(parse_shorthand("东坡", "krow.cn"), None);
        assert_eq!(
            parse_shorthand("东坡#人间词话#100095@krow.cn", "krow.cn"),
            None
        );
        assert_eq!(parse_shorthand("东坡#人间词话#100095", "krow.cn"), None);
        assert_eq!(parse_shorthand("krow:a/b/c", "krow.cn"), None);
        assert_eq!(parse_shorthand("#人间词话", "krow.cn"), None);
        assert_eq!(parse_shorthand("东坡#", "krow.cn"), None);
    }
}
