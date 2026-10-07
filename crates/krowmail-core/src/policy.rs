pub const MAX_CROSS_TEAM_SENDS: i64 = 10;
pub const CROSS_TEAM_WINDOW_MINUTES: i32 = 10;
pub const MAX_DAILY_OWNER_PAIR: i64 = 50;
pub const MAX_HOURLY_EXTERNAL: i64 = 30;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MailPolicy {
    Own,
    Contacts,
    Everyone,
    /// 白名单收信：只收通讯录里明确允许来信（allowlisted）的地址。给敏感主体留的
    /// 显式收窄档——默认通的世界里，个体仍能把门关到只剩名单。
    Allowlist,
}

impl MailPolicy {
    pub fn parse(raw: &str) -> Option<Self> {
        match raw {
            "own" => Some(Self::Own),
            "contacts" => Some(Self::Contacts),
            "everyone" => Some(Self::Everyone),
            "allowlist" => Some(Self::Allowlist),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Own => "own",
            Self::Contacts => "contacts",
            Self::Everyone => "everyone",
            Self::Allowlist => "allowlist",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CrossDecision {
    Allow { trust: &'static str },
    FlatOff,
    FlagOff,
    PolicyOwn,
    PolicyContacts,
    PolicyAllowlist,
    RateTeam,
    RateDaily,
    RateHourly,
    Blocked,
}

impl CrossDecision {
    pub fn code(self) -> &'static str {
        match self {
            Self::Allow { .. } => "allow",
            Self::FlatOff => "flat_off",
            Self::FlagOff => "flag_off",
            Self::PolicyOwn => "policy_own",
            Self::PolicyContacts => "policy_contacts",
            Self::PolicyAllowlist => "policy_allowlist",
            Self::RateTeam => "rate_team",
            Self::RateDaily => "rate_daily",
            Self::RateHourly => "rate_hourly",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Clone, Copy)]
pub struct CrossInput {
    pub same_owner: bool,
    pub flat_flag: bool,
    pub cross_open: bool,
    pub policy: MailPolicy,
    pub known_contact: bool,
    /// 发件地址在收件方通讯录里且明确允许来信（[`MailPolicy::Allowlist`] 的放行键）。
    pub allowlisted: bool,
    pub blocked: bool,
    pub recent_to_team: i64,
    pub daily_pair: i64,
    pub hourly_inbox: i64,
}

pub fn decide(input: &CrossInput) -> CrossDecision {
    if input.same_owner {
        if !input.flat_flag {
            return CrossDecision::FlatOff;
        }
    } else if !input.cross_open {
        return CrossDecision::FlagOff;
    } else if input.blocked {
        return CrossDecision::Blocked;
    } else {
        match input.policy {
            MailPolicy::Own => return CrossDecision::PolicyOwn,
            MailPolicy::Contacts if !input.known_contact => return CrossDecision::PolicyContacts,
            MailPolicy::Allowlist if !input.allowlisted => return CrossDecision::PolicyAllowlist,
            MailPolicy::Contacts | MailPolicy::Everyone | MailPolicy::Allowlist => {}
        }
        if input.daily_pair >= MAX_DAILY_OWNER_PAIR {
            return CrossDecision::RateDaily;
        }
        if input.hourly_inbox >= MAX_HOURLY_EXTERNAL {
            return CrossDecision::RateHourly;
        }
    }
    if input.recent_to_team >= MAX_CROSS_TEAM_SENDS {
        return CrossDecision::RateTeam;
    }
    CrossDecision::Allow {
        trust: if input.same_owner {
            "department"
        } else {
            "external"
        },
    }
}

pub trait Policy {
    fn decide(&self, input: &CrossInput) -> CrossDecision;
}

pub struct DefaultPolicy;

impl Policy for DefaultPolicy {
    fn decide(&self, input: &CrossInput) -> CrossDecision {
        decide(input)
    }
}
