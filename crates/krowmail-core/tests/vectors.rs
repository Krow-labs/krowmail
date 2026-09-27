use krowmail_core::{
    decide, display_name_banned, parse_open, parse_syntax, validate_address_name,
    validate_user_handle, CrossDecision, CrossInput, MailPolicy, Syntax,
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
