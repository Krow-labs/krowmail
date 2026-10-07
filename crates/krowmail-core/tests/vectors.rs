use krowmail_core::{
    decide, display_name_banned, parse_open, parse_shorthand, parse_syntax, validate_address_name,
    validate_user_handle, CrossDecision, CrossInput, MailPolicy, Syntax, ENVELOPE_KINDS,
    ENVELOPE_OUTCOMES, MAX_ENVELOPE_MENTIONS, MAX_ENVELOPE_PARTICIPANTS,
};
use serde_json::Value;

#[test]
fn address_vectors() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../spec/test-vectors/address.json"
    );
    let file: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    for case in file["cases"].as_array().unwrap() {
        let id = case["id"].as_str().unwrap();
        match case["fn"].as_str().unwrap() {
            "parse_syntax" => check_parse_syntax(id, case),
            "parse_open" => check_parse_open(id, case),
            "parse_shorthand" => check_parse_shorthand(id, case),
            "validate_address_name" => check_validate(id, case, validate_address_name),
            "validate_user_handle" => check_validate(id, case, validate_user_handle),
            "display_name_banned" => {
                let got = display_name_banned(case["input"].as_str().unwrap());
                assert_eq!(got, case["expect"].as_bool().unwrap(), "{id}");
            }
            "decide" => check_decide(id, case),
            other => panic!("{id}: unknown fn {other}"),
        }
    }
}

fn check_parse_syntax(id: &str, case: &Value) {
    let got = parse_syntax(
        case["input"].as_str().unwrap(),
        case["domain"].as_str().unwrap(),
    );
    if let Some(needle) = case.get("error_contains").and_then(Value::as_str) {
        let err = got.expect_err(id);
        assert!(err.contains(needle), "{id}: {err}");
        return;
    }
    if case.get("error").and_then(Value::as_bool) == Some(true) {
        assert!(got.is_err(), "{id}");
        return;
    }
    let expect = &case["expect"];
    match got.unwrap() {
        Syntax::Friendly {
            member,
            team,
            owner,
        } => {
            assert_eq!(expect["kind"], "friendly", "{id}");
            assert_eq!(member, expect["member"].as_str().unwrap(), "{id}");
            assert_eq!(team, expect["team"].as_str().unwrap(), "{id}");
            assert_eq!(owner, expect["owner"].as_str().unwrap(), "{id}");
        }
        Syntax::Legacy(addr) => {
            assert_eq!(expect["kind"], "legacy", "{id}");
            assert_eq!(
                addr.user.to_string(),
                expect["user"].as_str().unwrap(),
                "{id}"
            );
            assert_eq!(
                addr.team.to_string(),
                expect["team"].as_str().unwrap(),
                "{id}"
            );
            assert_eq!(
                addr.member.to_string(),
                expect["member"].as_str().unwrap(),
                "{id}"
            );
        }
    }
}

fn check_parse_shorthand(id: &str, case: &Value) {
    let got = parse_shorthand(
        case["input"].as_str().unwrap(),
        case["domain"].as_str().unwrap(),
    );
    let expect = &case["expect"];
    if expect.is_null() {
        assert_eq!(got, None, "{id}");
        return;
    }
    let (member, team) = got.unwrap_or_else(|| panic!("{id}: expected shorthand"));
    assert_eq!(member, expect["member"].as_str().unwrap(), "{id}");
    assert_eq!(team, expect["team"].as_str().unwrap(), "{id}");
}

fn check_parse_open(id: &str, case: &Value) {
    let got = parse_open(case["input"].as_str().unwrap());
    if case.get("error").and_then(Value::as_bool) == Some(true) {
        assert!(got.is_err(), "{id}");
        return;
    }
    let open = got.unwrap();
    let segments: Vec<&str> = case["expect"]["segments"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(open.segments, segments, "{id}");
    assert_eq!(
        open.domain,
        case["expect"]["domain"].as_str().unwrap(),
        "{id}"
    );
}

fn check_validate(id: &str, case: &Value, fun: fn(&str) -> Result<(), &'static str>) {
    let got = fun(case["input"].as_str().unwrap());
    if let Some(needle) = case.get("error_contains").and_then(Value::as_str) {
        let err = got.expect_err(id);
        assert!(err.contains(needle), "{id}: {err}");
        return;
    }
    if case.get("error").and_then(Value::as_bool) == Some(true) {
        assert!(got.is_err(), "{id}");
        return;
    }
    assert!(got.is_ok(), "{id}: {got:?}");
}

fn check_decide(id: &str, case: &Value) {
    let raw = &case["input"];
    let input = CrossInput {
        same_owner: raw["same_owner"].as_bool().unwrap(),
        flat_flag: raw["flat_flag"].as_bool().unwrap(),
        cross_open: raw["cross_open"].as_bool().unwrap(),
        policy: MailPolicy::parse(raw["policy"].as_str().unwrap()).unwrap(),
        known_contact: raw["known_contact"].as_bool().unwrap(),
        // 旧向量没有这个键：缺省 false，与线上「不在名单里」同义。
        allowlisted: raw
            .get("allowlisted")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        blocked: raw["blocked"].as_bool().unwrap(),
        recent_to_team: raw["recent_to_team"].as_i64().unwrap(),
        daily_pair: raw["daily_pair"].as_i64().unwrap(),
        hourly_inbox: raw["hourly_inbox"].as_i64().unwrap(),
    };
    let got = decide(&input);
    let expect = &case["expect"];
    assert_eq!(got.code(), expect["decision"].as_str().unwrap(), "{id}");
    if let CrossDecision::Allow { trust } = got {
        assert_eq!(trust, expect["trust"].as_str().unwrap(), "{id}");
    }
}

/// 信封可选卡片的上限：`spec/envelope.schema.json` 的 `maxItems` 与 core 常量必须同值，
/// 否则一边收下的信另一边会拒。
#[test]
fn envelope_schema_limits_match_core() {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../spec/envelope.schema.json"
    );
    let schema: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let props = &schema["properties"];
    assert_eq!(
        props["participants"]["maxItems"].as_u64().unwrap() as usize,
        MAX_ENVELOPE_PARTICIPANTS
    );
    assert_eq!(
        props["mentions"]["maxItems"].as_u64().unwrap() as usize,
        MAX_ENVELOPE_MENTIONS
    );
    assert_eq!(props["cc"]["type"], "boolean");
    assert_eq!(schema["additionalProperties"], false);
    // 0.3.0 协议位：闭集同值同序；kind 必须保持可选（老对端按普通信处理）。
    let enum_of = |key: &str| -> Vec<String> {
        props[key]["enum"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().to_string())
            .collect()
    };
    assert_eq!(enum_of("kind"), ENVELOPE_KINDS);
    assert_eq!(enum_of("outcome"), ENVELOPE_OUTCOMES);
    assert_eq!(props["due_at"]["type"], "string");
    assert_eq!(props["decision_for"]["type"], "string");
    let required: Vec<&str> = schema["required"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert!(!required.contains(&"kind"));
}
