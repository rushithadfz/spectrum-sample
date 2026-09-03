"""
Populate the portal with a full demo catalog: one agent, 12 offers,
9 incentive programs, 11 products with grouped specs, sales and content.

    python manage.py seed_demo            # create/update, keep existing rows
    python manage.py seed_demo --reset    # wipe portal tables first
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from portal.models import (
    AgentProfile,
    RoleType,
    Team,
    Badge,
    Announcement,
    Category,
    Cutoff,
    Dispute,
    Highlight,
    Incentive,
    MtdCategory,
    Notification,
    Offer,
    Period,
    PerformanceSnapshot,
    Persona,
    PointsRule,
    Product,
    ProductLink,
    Quest,
    Quota,
    Resource,
    Sale,
    SavedPlan,
    Budget,
    Channel,
    IncentivePlan,
    MarketTrend,
    PayoutException,
    Scorecard,
    Spec,
    SpecGroup,
    Status,
    SupportContact,
    Tier,
    TrendPoint,
)

D = Decimal

AGENT_PASSWORD = "demo12345"   # unused by the role picker; kept for /admin/

# --------------------------------------------------------------------------
# The org: 2 managers over 4 team leads over 16 field agents.
# Personas are generated from this, so everyone is selectable at sign-in.
# --------------------------------------------------------------------------
TEAMS = [
    ("DFW Inbound Queue 4", "Southwest Region", "gchen"),
    ("DFW Inbound Queue 7", "Southwest Region", "gchen"),
    ("NYC Inbound Queue 2", "Northeast Region", "sreed"),
    ("NYC Retail Queue 5",  "Northeast Region", "sreed"),
]

# username, first, last, id, role, team index, attainment, accent
PEOPLE = [
    # --- managers ---
    ("gchen",     "Grace",   "Chen",     "MG-10032", "manager", None, 0,   "violet"),
    ("sreed",     "Samuel",  "Reed",     "MG-10047", "manager", None, 0,   "violet"),
    # --- team leads ---
    ("jmitchell", "Jordan",  "Mitchell", "TL-20114", "lead",    0,    0,   "teal"),
    ("hpark",     "Hannah",  "Park",     "TL-20115", "lead",    1,    0,   "teal"),
    ("praman",    "Priya",   "Raman",    "TL-20131", "lead",    2,    0,   "teal"),
    ("ofletcher", "Owen",    "Fletcher", "TL-20132", "lead",    3,    0,   "teal"),
    # --- team 1 ---
    ("jliu",      "Jenny",   "Liu",      "AG-40921", "agent",   0,    103, "blue"),
    ("knguyen",   "Kevin",   "Nguyen",   "AG-40922", "agent",   0,    118, "blue"),
    ("ecarter",   "Emily",   "Carter",   "AG-40923", "agent",   0,    91,  "blue"),
    ("wzhang",    "Wei",     "Zhang",    "AG-40924", "agent",   0,    76,  "blue"),
    ("tbrooks",   "Tyler",   "Brooks",   "AG-40925", "agent",   0,    64,  "blue"),
    # --- team 2 ---
    ("atanaka",   "Aiko",    "Tanaka",   "AG-40931", "agent",   1,    127, "blue"),
    ("mbennett",  "Marcus",  "Bennett",  "AG-40932", "agent",   1,    88,  "blue"),
    ("asharma",   "Ananya",  "Sharma",   "AG-40933", "agent",   1,    72,  "blue"),
    ("dkim",      "Daniel",  "Kim",      "AG-40934", "agent",   1,    58,  "blue"),
    # --- team 3 ---
    ("rmorgan",   "Rachel",  "Morgan",   "AG-40941", "agent",   2,    112, "blue"),
    ("hsato",     "Haruto",  "Sato",     "AG-40942", "agent",   2,    97,  "blue"),
    ("jcole",     "Jasmine", "Cole",     "AG-40943", "agent",   2,    83,  "blue"),
    ("vmehta",    "Vikram",  "Mehta",    "AG-40944", "agent",   2,    69,  "blue"),
    # --- team 4 ---
    ("clarson",   "Chloe",   "Larson",   "AG-40951", "agent",   3,    134, "blue"),
    ("jtan",      "Jayden",  "Tan",      "AG-40952", "agent",   3,    95,  "blue"),
    ("nrivera",   "Nathan",  "Rivera",   "AG-40953", "agent",   3,    78,  "blue"),
    ("mchoi",     "Mina",    "Choi",     "AG-40954", "agent",   3,    61,  "blue"),
]

# Recorded per person rather than derived from a first name, which would
# misgender real people. Demo data, set deliberately.
PRESENTS_AS = {
    "jliu": "woman", "knguyen": "man", "ecarter": "woman", "wzhang": "man",
    "tbrooks": "man", "jmitchell": "man", "hpark": "woman", "praman": "woman",
    "ofletcher": "man", "gchen": "woman", "sreed": "man",
}

AGENT_USERNAME = "jliu"          # the persona the demo opens on

ROLE_BLURB = {
    "agent":   "Your scorecard, incentives, earnings calculator and disputes",
    "lead":    "Your squad roster, attainment against quota and their open disputes",
    "manager": "Every team you own, rollups, leaderboard and payout oversight",
}

ROLE_LABEL = {
    "agent":   "Residential Inbound Agent",
    "lead":    "Team Lead - Residential Inbound",
    "manager": "Regional Manager",
}
ROLE_ENUM = {
    "agent":   RoleType.AGENT,
    "lead":    RoleType.LEAD,
    "manager": RoleType.MANAGER,
}


# --------------------------------------------------------------------------
# Catalog data
# --------------------------------------------------------------------------
PRODUCTS = [
    {
        "slug": "internet-advantage-500", "name": "Internet Advantage 500 Mbps",
        "sku": "INT-ADV-500", "category": Category.INTERNET, "icon": "\U0001F310",
        "price_note": "$49.99/mo promo, $69.99 standard",
        "description": "Mid-tier residential broadband over hybrid fiber-coax. The default recommendation for households of 1-4.",
        "highlights": [("Download", "500 Mbps"), ("Upload", "20 Mbps"), ("Data cap", "None")],
        "links": [
            ("Public product page", "https://www.spectrum.com/internet", "\U0001F517"),
            ("Agent sales sheet (PDF)", "#", "\U0001F4C4"),
            ("Coverage / serviceability check", "#", "\U0001F4CD"),
            ("Objection handling script", "#", "\U0001F5E3"),
        ],
        "specs": [
            ("Performance", [
                ("Download speed", "Up to 500 Mbps (wired)"),
                ("Upload speed", "Up to 20 Mbps"),
                ("Typical latency", "15-25 ms"),
                ("Data allowance", "Unlimited - no cap, no throttling"),
                ("Concurrent devices", "Recommended up to 12 active devices"),
            ]),
            ("Network", [
                ("Technology", "DOCSIS 3.1 hybrid fiber-coax"),
                ("IP addressing", "Dynamic IPv4 + IPv6 dual stack"),
                ("Static IP", "Not available on residential tiers"),
                ("Service availability", "All serviceable residential addresses"),
            ]),
            ("Equipment", [
                ("Modem", "Included at no charge"),
                ("Router", "Advanced WiFi add-on, $7/mo"),
                ("Install options", "Self-install kit (free) or professional install ($59.99)"),
                ("Compatible customer modems", "DOCSIS 3.1 approved list"),
            ]),
            ("Contract & billing", [
                ("Term", "No contract"),
                ("Promo length", "12 months"),
                ("Early termination fee", "None"),
                ("Auto-pay discount", "$5/mo with paperless billing"),
            ]),
        ],
    },
    {
        "slug": "internet-ultra-1-gig", "name": "Internet Ultra 1 Gig",
        "sku": "INT-ULT-1000", "category": Category.INTERNET, "icon": "⚡",
        "price_note": "$79.99/mo promo, $109.99 standard",
        "description": "Gigabit residential tier. Sell into homes with 4+ people, 4K streaming, gaming, or a work-from-home setup.",
        "highlights": [("Download", "1 Gbps"), ("Upload", "35 Mbps"), ("Router", "Included")],
        "links": [
            ("Public product page", "https://www.spectrum.com/internet/gig", "\U0001F517"),
            ("Gig speed test tool", "#", "\U0001F4CA"),
            ("Agent sales sheet (PDF)", "#", "\U0001F4C4"),
            ("Upgrade path calculator", "#", "\U0001F9EE"),
        ],
        "specs": [
            ("Performance", [
                ("Download speed", "Up to 1 Gbps (940 Mbps typical wired)"),
                ("Upload speed", "Up to 35 Mbps"),
                ("Typical latency", "10-20 ms"),
                ("Data allowance", "Unlimited"),
                ("Concurrent devices", "25+ active devices"),
            ]),
            ("Network", [
                ("Technology", "DOCSIS 3.1 with mid-split upstream"),
                ("IP addressing", "Dynamic IPv4 + IPv6 dual stack"),
                ("Wired requirement", "Cat 6 or better and a 1 Gbps NIC to reach full speed"),
                ("WiFi ceiling", "Approx. 700-900 Mbps on WiFi 6/7 near the router"),
            ]),
            ("Equipment", [
                ("Modem", "DOCSIS 3.1 gateway included"),
                ("Router", "WiFi 7 router included at no extra charge"),
                ("Mesh extender", "One free extender on request"),
                ("Install", "Free professional installation"),
            ]),
            ("Contract & billing", [
                ("Term", "No contract"),
                ("Promo length", "12 months"),
                ("Early termination fee", "None"),
                ("Upgrade credit", "Prorated from prior tier"),
            ]),
        ],
    },
    {
        "slug": "internet-assist", "name": "Internet Assist",
        "sku": "INT-AST-050", "category": Category.INTERNET, "icon": "\U0001F91D",
        "price_note": "$24.99/mo",
        "description": "Subsidized broadband for qualifying low-income households. Eligibility must be verified before submission.",
        "highlights": [("Download", "50 Mbps"), ("Upload", "5 Mbps"), ("Contract", "None")],
        "links": [
            ("Eligibility program details", "#", "\U0001F517"),
            ("Verification checklist (PDF)", "#", "✅"),
            ("Enrollment form", "#", "\U0001F4DD"),
        ],
        "specs": [
            ("Performance", [
                ("Download speed", "Up to 50 Mbps"),
                ("Upload speed", "Up to 5 Mbps"),
                ("Data allowance", "Unlimited"),
            ]),
            ("Eligibility", [
                ("Qualifying programs", "NSLP, Community Eligibility Provision, SSI (age 65+)"),
                ("Verification", "Proof of participation required at order entry"),
                ("Household limit", "One subscription per household"),
                ("Existing balance", "Account must have no outstanding balance"),
            ]),
            ("Equipment", [
                ("Modem", "Included, no monthly fee"),
                ("In-home WiFi", "$5/mo add-on"),
                ("Install", "Self-install kit only"),
            ]),
        ],
    },
    {
        "slug": "mobile-unlimited", "name": "Mobile Unlimited",
        "sku": "MOB-UNL-01", "category": Category.MOBILE, "icon": "\U0001F4F1",
        "price_note": "$29.99/line promo, $45.00 standard",
        "description": "Unlimited talk, text and data on a nationwide 5G network. Requires an active internet account.",
        "highlights": [("Data", "Unlimited"), ("Network", "5G nationwide"), ("Max lines", "5 per account")],
        "links": [
            ("Public mobile page", "https://www.spectrum.com/mobile", "\U0001F517"),
            ("Device compatibility checker", "#", "\U0001F50D"),
            ("Port-in / switch guide (PDF)", "#", "\U0001F504"),
            ("Coverage map", "#", "\U0001F5FA"),
        ],
        "specs": [
            ("Plan", [
                ("Data", "Unlimited, reduced speeds after 30 GB per line per cycle"),
                ("Talk & text", "Unlimited nationwide"),
                ("Mobile hotspot", "5 GB at full speed, then 600 Kbps"),
                ("Video streaming", "Up to 480p standard, HD add-on available"),
                ("International", "Talk/text to Mexico and Canada included"),
            ]),
            ("Network", [
                ("Technology", "5G / 4G LTE nationwide"),
                ("SIM type", "Physical SIM and eSIM supported"),
                ("WiFi calling", "Supported on compatible devices"),
                ("VoLTE", "Required - device must be VoLTE capable"),
            ]),
            ("Requirements", [
                ("Internet service", "Active internet account required at the address"),
                ("Auto-pay", "Required for promo pricing"),
                ("Line limit", "Up to 5 lines per account"),
                ("Device", "Bring your own or finance a new device over 24 months"),
            ]),
        ],
    },
    {
        "slug": "mobile-by-the-gig", "name": "Mobile By the Gig",
        "sku": "MOB-GIG-01", "category": Category.MOBILE, "icon": "\U0001F4CA",
        "price_note": "$14.00 per GB shared",
        "description": "Pay-per-gigabyte mobile plan with shared data. The fallback pitch when a customer refuses unlimited.",
        "highlights": [("Billing", "Per GB shared"), ("Talk & text", "Unlimited"), ("Max lines", "5 per account")],
        "links": [
            ("Plan comparison tool", "#", "⚖"),
            ("Data usage calculator", "#", "\U0001F9EE"),
            ("Agent sales sheet (PDF)", "#", "\U0001F4C4"),
        ],
        "specs": [
            ("Plan", [
                ("Data", "Charged at $14 per GB, shared across all lines"),
                ("Talk & text", "Unlimited nationwide"),
                ("Plan switching", "Switch between By the Gig and Unlimited any time"),
                ("Overage", "No overage - additional GB billed at the same rate"),
            ]),
            ("Network", [
                ("Technology", "5G / 4G LTE nationwide"),
                ("SIM type", "Physical SIM and eSIM"),
                ("WiFi calling", "Supported"),
            ]),
            ("Requirements", [
                ("Internet service", "Active internet account required"),
                ("Auto-pay", "Required"),
                ("Line limit", "Up to 5 lines per account"),
            ]),
        ],
    },
    {
        "slug": "tv-select", "name": "TV Select",
        "sku": "TV-SEL-125", "category": Category.TV, "icon": "\U0001F4FA",
        "price_note": "$59.99/mo promo",
        "description": "The core video package - 125+ channels with a streaming box and three included premium apps.",
        "highlights": [("Channels", "125+"), ("Included apps", "Disney+, Max, Paramount+"), ("First box", "Free")],
        "links": [
            ("Channel lineup by ZIP", "https://www.spectrum.com/cable-tv", "\U0001F517"),
            ("Channel lineup card (PDF)", "#", "\U0001F4C4"),
            ("Premium add-on pricing", "#", "\U0001F4B2"),
            ("Sports package matrix", "#", "\U0001F3C8"),
        ],
        "specs": [
            ("Content", [
                ("Channel count", "125+ (varies by market)"),
                ("Local channels", "Included"),
                ("Included streaming apps", "Disney+ (Basic), Max (Basic), Paramount+ Essential"),
                ("On demand", "30,000+ titles included"),
                ("Premium add-ons", "HBO, SHOWTIME, STARZ, EPIX - $10-$15/mo each"),
            ]),
            ("Technical", [
                ("Max resolution", "4K UHD on supported channels"),
                ("DVR", "Cloud DVR add-on, 50 or 100 hours"),
                ("Simultaneous streams", "Up to 3 in-home streams per account"),
                ("Out-of-home viewing", "Supported via the TV app"),
            ]),
            ("Equipment", [
                ("Streaming box", "First box included, $7.99/mo per extra box"),
                ("Bring your own", "Roku, Fire TV, Apple TV and Samsung supported via app"),
                ("Install", "Free professional install with a bundle"),
            ]),
            ("Billing", [
                ("Broadcast TV surcharge", "Applies, not included in promo rate"),
                ("Promo length", "12 months"),
                ("Term", "No contract"),
            ]),
        ],
    },
    {
        "slug": "stream-select", "name": "Stream Select (streaming-only TV)",
        "sku": "TV-STR-065", "category": Category.TV, "icon": "\U0001F3AC",
        "price_note": "$39.99/mo",
        "description": "App-only live TV for cord-cutters. No equipment, no truck roll, activates instantly.",
        "highlights": [("Channels", "65+ live"), ("Equipment", "None"), ("Install", "Instant")],
        "links": [
            ("Streaming channel lineup", "#", "\U0001F517"),
            ("Supported devices list", "#", "\U0001F4F1"),
            ("Cord-cutter pitch script", "#", "\U0001F5E3"),
        ],
        "specs": [
            ("Content", [
                ("Channel count", "65+ live channels"),
                ("Local channels", "Included where available"),
                ("On demand", "Included with most networks"),
                ("Premium add-ons", "Available in-app"),
            ]),
            ("Technical", [
                ("Max resolution", "1080p"),
                ("Simultaneous streams", "2 concurrent streams"),
                ("Cloud DVR", "50 hours included"),
                ("Minimum bandwidth", "25 Mbps recommended per HD stream"),
            ]),
            ("Requirements", [
                ("Supported devices", "Roku, Fire TV, Apple TV, iOS, Android, web"),
                ("Internet service", "Active internet account required"),
                ("Equipment", "None - no set-top box issued"),
            ]),
        ],
    },
    {
        "slug": "home-phone-unlimited", "name": "Home Phone Unlimited",
        "sku": "VOI-UNL-01", "category": Category.VOICE, "icon": "☎",
        "price_note": "$24.99/mo, $19.99 in a bundle",
        "description": "Digital home phone with unlimited nationwide calling. Strongest with 55+ and multi-generational households.",
        "highlights": [("Calling", "Unlimited US/CA/MX"), ("Features", "28 included"), ("Number", "Port-in supported")],
        "links": [
            ("Calling feature list (PDF)", "#", "\U0001F4C4"),
            ("International rate table", "#", "\U0001F30E"),
            ("Number port-in form", "#", "\U0001F4DD"),
        ],
        "specs": [
            ("Calling", [
                ("Nationwide calling", "Unlimited to US, Canada, Mexico and Puerto Rico"),
                ("International", "Per-minute rates, add-on packages available"),
                ("Included features", "28 features incl. caller ID, call waiting, voicemail, blocking"),
                ("Number portability", "Existing number can be ported in"),
            ]),
            ("Technical", [
                ("Technology", "Digital voice over the broadband connection"),
                ("Backup", "Battery backup unit available, 8 hours standby"),
                ("E911", "Supported - service address must be registered"),
                ("Handsets", "Customer provides standard corded/cordless handset"),
            ]),
            ("Billing", [
                ("Standalone price", "$24.99/mo"),
                ("Bundle price", "$19.99/mo with internet"),
                ("Term", "No contract"),
            ]),
        ],
    },
    {
        "slug": "business-internet-600", "name": "Business Internet 600 Mbps",
        "sku": "BIZ-INT-600", "category": Category.BUSINESS, "icon": "\U0001F3E2",
        "price_note": "$64.99/mo for 24 months",
        "description": "SMB broadband with business-grade support and an optional static IP block. 24-month term.",
        "highlights": [("Download", "600 Mbps"), ("Upload", "35 Mbps"), ("Support", "24/7 business line")],
        "links": [
            ("Business product page", "https://www.spectrum.com/business", "\U0001F517"),
            ("SMB proposal template", "#", "\U0001F4C4"),
            ("Static IP order form", "#", "\U0001F4DD"),
            ("SLA summary", "#", "\U0001F4CB"),
        ],
        "specs": [
            ("Performance", [
                ("Download speed", "Up to 600 Mbps"),
                ("Upload speed", "Up to 35 Mbps"),
                ("Data allowance", "Unlimited"),
                ("Availability target", "99.9% network availability"),
            ]),
            ("Network", [
                ("Static IP", "1, 5 or 13 usable IPs - $14.99 to $39.99/mo"),
                ("IPv6", "Supported"),
                ("Business WiFi", "Managed WiFi add-on with guest network"),
                ("Domain & email", "3 email boxes and a domain included"),
            ]),
            ("Support & terms", [
                ("Support", "24/7 dedicated US-based business support"),
                ("Term", "24-month agreement required"),
                ("Early termination fee", "Remaining months x 35% of monthly rate"),
                ("Install", "Professional install included"),
            ]),
        ],
    },
    {
        "slug": "advanced-wifi-7-router", "name": "Advanced WiFi 7 Router",
        "sku": "HW-RTR-WE7", "category": Category.EQUIPMENT, "icon": "\U0001F4E1",
        "price_note": "$7.00/mo lease",
        "description": "The leased router behind the Advanced WiFi add-on. Know these specs - customers ask about coverage constantly.",
        "highlights": [("Standard", "WiFi 7 (802.11be)"), ("Coverage", "Up to 3,000 sq ft"), ("Bands", "Tri-band")],
        "links": [
            ("Equipment spec sheet (PDF)", "#", "\U0001F4C4"),
            ("Coverage sizing guide", "#", "\U0001F4D0"),
            ("Mesh extender ordering", "#", "\U0001F4E6"),
            ("Equipment return policy", "#", "↩"),
        ],
        "specs": [
            ("Wireless", [
                ("WiFi standard", "WiFi 7 (802.11be), backward compatible to 802.11a/b/g/n/ac/ax"),
                ("Bands", "Tri-band - 2.4 GHz, 5 GHz, 6 GHz"),
                ("Max theoretical throughput", "5.8 Gbps aggregate"),
                ("Channel width", "Up to 320 MHz on 6 GHz"),
                ("MIMO", "4x4 MU-MIMO with beamforming"),
                ("Coverage", "Up to 3,000 sq ft; add a mesh extender beyond that"),
            ]),
            ("Ports & hardware", [
                ("WAN port", "1 x 2.5 Gbps Ethernet"),
                ("LAN ports", "4 x 1 Gbps Ethernet"),
                ("USB", "1 x USB 3.0"),
                ("Dimensions", "9.1 x 4.3 x 4.3 in"),
                ("Power", "12V DC, 30W max"),
            ]),
            ("Software", [
                ("Security suite", "Included - threat blocking and device quarantine"),
                ("Parental controls", "Per-device profiles, schedules and content filters"),
                ("Management", "Via the My Account mobile app"),
                ("Firmware", "Automatic over-the-air updates"),
                ("Guest network", "Supported, separate SSID and password"),
            ]),
            ("Terms", [
                ("Lease", "$7.00/mo, included free on 1 Gig plans"),
                ("Return", "Must be returned within 30 days of cancellation"),
                ("Unreturned equipment fee", "$180.00"),
            ]),
        ],
    },
    {
        "slug": "streaming-tv-box", "name": "Streaming TV Box",
        "sku": "HW-STB-XM1", "category": Category.EQUIPMENT, "icon": "\U0001F5A5",
        "price_note": "First box free, $7.99/mo per extra box",
        "description": "The set-top streaming box shipped with TV Select. First box is free on every bundle.",
        "highlights": [("Video", "4K HDR"), ("Audio", "Dolby Atmos"), ("Remote", "Voice remote")],
        "links": [
            ("Box spec sheet (PDF)", "#", "\U0001F4C4"),
            ("Setup walkthrough", "#", "\U0001F3AC"),
            ("Supported app list", "#", "\U0001F4F2"),
        ],
        "specs": [
            ("Video & audio", [
                ("Max resolution", "4K UHD at 60 fps"),
                ("HDR", "HDR10, HLG and Dolby Vision"),
                ("Audio", "Dolby Atmos and Dolby Digital Plus passthrough"),
                ("Output", "HDMI 2.1"),
            ]),
            ("Hardware", [
                ("Processor", "Quad-core ARM Cortex-A55"),
                ("Memory", "2 GB RAM / 8 GB storage"),
                ("Networking", "WiFi 6 dual-band + 10/100 Ethernet"),
                ("Remote", "Bluetooth voice remote with TV power and volume control"),
                ("Dimensions", "4.5 x 4.5 x 1.0 in"),
            ]),
            ("Software", [
                ("Live TV", "Integrated live guide with the TV Select lineup"),
                ("Apps", "Netflix, Disney+, Max, Prime Video, YouTube, Paramount+ and more"),
                ("Voice search", "Search across live TV and apps"),
                ("Profiles", "Not supported - single household profile"),
            ]),
            ("Terms", [
                ("First box", "Included free with TV Select"),
                ("Additional boxes", "$7.99/mo each, max 5 per account"),
                ("Unreturned equipment fee", "$120.00"),
            ]),
        ],
    },
]


OFFERS = [
    {
        "code": "OF-1001", "slug": "internet-advantage-500-mbps", "name": "Internet Advantage 500 Mbps",
        "category": Category.INTERNET, "status": Status.ACTIVE, "badges": "Best seller",
        "blurb": "Entry speed tier for households of 1-4 with promo pricing locked for 12 months.",
        "price": D("49.99"), "price_period": "/mo for 12 mos", "was_price": D("69.99"),
        "points": "500 Mbps download / 20 Mbps upload\nNo data caps, no contracts\nFree self-install kit\nWiFi equipment $10/mo add-on",
        "commission": D("65"), "spiff": D("25"), "spiff_note": "Weekend Blitz SPIFF - ends Aug 31",
        "eligibility": "New residential customers only. No service at address in prior 30 days.",
        "terms": "Promo rate for 12 months, then standard rate applies. Taxes and fees extra. Install fee waived on self-install.",
        "valid_from": date(2026, 8, 1), "valid_to": date(2026, 9, 30),
        "products": ["internet-advantage-500", "advanced-wifi-7-router"],
    },
    {
        "code": "OF-1002", "slug": "internet-ultra-1-gig-offer", "name": "Internet Ultra 1 Gig",
        "category": Category.INTERNET, "status": Status.ACTIVE, "badges": "High payout",
        "blurb": "Gigabit tier for heavy streaming and work-from-home households.",
        "price": D("79.99"), "price_period": "/mo for 12 mos", "was_price": D("109.99"),
        "points": "1 Gbps download / 35 Mbps upload\nAdvanced WiFi router included\nFree professional installation\nUnlimited data",
        "commission": D("110"), "spiff": D("40"), "spiff_note": "Gig Push - stacks with bundle SPIFF",
        "eligibility": "New and existing customers upgrading from 500 Mbps or lower.",
        "terms": "Promo rate for 12 months. Speeds based on wired connection. Actual speeds may vary.",
        "valid_from": date(2026, 7, 15), "valid_to": date(2026, 9, 30),
        "products": ["internet-ultra-1-gig", "advanced-wifi-7-router"],
    },
    {
        "code": "OF-1003", "slug": "mobile-unlimited-2-lines", "name": "Mobile Unlimited - 2 Lines",
        "category": Category.MOBILE, "status": Status.ACTIVE, "badges": "Bundle boost",
        "blurb": "Two unlimited mobile lines at a promo rate when attached to an active internet account.",
        "price": D("29.99"), "price_period": "/line/mo", "was_price": D("45.00"),
        "points": "Unlimited talk, text and data\n5G nationwide access included\nRequires active internet service\nFree line activation this month",
        "commission": D("45"), "spiff": D("30"), "spiff_note": "Per line - $30 x 2 lines = $60",
        "eligibility": "Requires an active internet account in good standing at the same address.",
        "terms": "Auto-pay required. Speeds may be reduced after 30 GB of usage per line per cycle.",
        "valid_from": date(2026, 8, 1), "valid_to": date(2026, 10, 31),
        "products": ["mobile-unlimited"],
    },
    {
        "code": "OF-1004", "slug": "mobile-by-the-gig-offer", "name": "Mobile By the Gig",
        "category": Category.MOBILE, "status": Status.ACTIVE, "badges": "",
        "blurb": "Low-usage mobile plan - a strong add-on for light users who reject unlimited.",
        "price": D("14.00"), "price_period": "/GB shared", "was_price": None,
        "points": "Shared data across all lines\nUnlimited talk and text\nSwitch between plans anytime\nRequires active internet service",
        "commission": D("25"), "spiff": D("10"), "spiff_note": "Attach SPIFF when sold same-day with internet",
        "eligibility": "Requires an active internet account. Max 5 lines per account.",
        "terms": "Charged per GB of shared data. Auto-pay required.",
        "valid_from": date(2026, 1, 1), "valid_to": date(2026, 12, 31),
        "products": ["mobile-by-the-gig"],
    },
    {
        "code": "OF-1005", "slug": "tv-select-internet-bundle", "name": "TV Select + Internet Bundle",
        "category": Category.BUNDLE, "status": Status.ACTIVE, "badges": "Top payout, Best seller",
        "blurb": "The flagship double-play. Highest total payout of any residential offer this month.",
        "price": D("109.98"), "price_period": "/mo for 12 mos", "was_price": D("154.98"),
        "points": "500 Mbps internet + 125+ TV channels\nStreaming box included, first box free\nFree professional installation\nDisney+, Max and Paramount+ included",
        "commission": D("140"), "spiff": D("75"), "spiff_note": "Double-Play Bonus - highest SPIFF this cycle",
        "eligibility": "New residential customers. Credit check required for equipment.",
        "terms": "Promo pricing for 12 months. Broadcast TV surcharge applies and is not included in promo rate.",
        "valid_from": date(2026, 8, 1), "valid_to": date(2026, 9, 15),
        "products": ["internet-advantage-500", "tv-select", "streaming-tv-box"],
    },
    {
        "code": "OF-1006", "slug": "triple-play", "name": "Triple Play - Internet, TV & Voice",
        "category": Category.BUNDLE, "status": Status.ACTIVE, "badges": "High payout",
        "blurb": "Full-stack household bundle. Best fit for 55+ and multi-generational homes.",
        "price": D("139.97"), "price_period": "/mo for 12 mos", "was_price": D("199.97"),
        "points": "500 Mbps internet\n125+ channels with streaming box\nUnlimited nationwide home phone\nFree installation on all three services",
        "commission": D("175"), "spiff": D("60"), "spiff_note": "Triple Play Bonus",
        "eligibility": "New residential customers at serviceable addresses.",
        "terms": "Promo pricing for 12 months. Taxes, fees and surcharges extra.",
        "valid_from": date(2026, 8, 1), "valid_to": date(2026, 9, 30),
        "products": ["internet-advantage-500", "tv-select", "home-phone-unlimited"],
    },
    {
        "code": "OF-1007", "slug": "business-internet-600-offer", "name": "Business Internet 600 Mbps",
        "category": Category.BUSINESS, "status": Status.ACTIVE, "badges": "SMB",
        "blurb": "Small-business tier with a static IP option and a 24/7 business support line.",
        "price": D("64.99"), "price_period": "/mo for 24 mos", "was_price": None,
        "points": "600 Mbps download / 35 Mbps upload\nStatic IP available as add-on\n24/7 dedicated business support\nFree modem, no data caps",
        "commission": D("150"), "spiff": D("50"), "spiff_note": "SMB Growth SPIFF - Q3 only",
        "eligibility": "Businesses with a valid tax ID. 2-year term agreement required.",
        "terms": "24-month term agreement. Early termination fee applies.",
        "valid_from": date(2026, 7, 1), "valid_to": date(2026, 9, 30),
        "products": ["business-internet-600"],
    },
    {
        "code": "OF-1008", "slug": "internet-assist-offer", "name": "Internet Assist (Low-Income)",
        "category": Category.INTERNET, "status": Status.ACTIVE, "badges": "Qualified program",
        "blurb": "Subsidized 50 Mbps tier for qualifying households. Counts toward unit quota.",
        "price": D("24.99"), "price_period": "/mo", "was_price": None,
        "points": "50 Mbps download / 5 Mbps upload\nNo contract, no modem fee\nIn-home WiFi $5/mo add-on\nCounts as one internet unit",
        "commission": D("30"), "spiff": D("0"), "spiff_note": "",
        "eligibility": "Household must qualify via NSLP, SSI (65+) or Community Eligibility Provision.",
        "terms": "Eligibility must be verified before order submission. Program subject to change.",
        "valid_from": date(2026, 1, 1), "valid_to": date(2026, 12, 31),
        "products": ["internet-assist"],
    },
    {
        "code": "OF-1009", "slug": "mobile-line-switch-credit", "name": "Mobile Line Switch Credit",
        "category": Category.MOBILE, "status": Status.ENDING, "badges": "Ends soon",
        "blurb": "Up to $500 in switch credits per line to cover a competitor early-termination fee.",
        "price": D("0"), "price_period": "credit offer", "was_price": None,
        "points": "Up to $500 per line, max 2 lines\nApplied as bill credit over 12 months\nRequires competitor final bill upload\nStacks with Mobile Unlimited promo",
        "commission": D("20"), "spiff": D("35"), "spiff_note": "Switcher SPIFF - final week",
        "eligibility": "Port-in from a competing carrier within 30 days of activation.",
        "terms": "Customer must remain active for 12 months. Credits forfeited on cancellation.",
        "valid_from": date(2026, 6, 1), "valid_to": date(2026, 8, 31),
        "products": ["mobile-unlimited"],
    },
    {
        "code": "OF-1010", "slug": "stream-select-offer", "name": "Streaming-Only TV (Stream Select)",
        "category": Category.TV, "status": Status.ACTIVE, "badges": "",
        "blurb": "App-based TV package for cord-cutters. No box, no install truck roll.",
        "price": D("39.99"), "price_period": "/mo", "was_price": None,
        "points": "65+ live channels in-app\nWorks on Roku, Fire TV and mobile\nNo equipment or install fee\nRequires internet service",
        "commission": D("45"), "spiff": D("15"), "spiff_note": "Cord-cutter attach SPIFF",
        "eligibility": "Requires an active internet account at the service address.",
        "terms": "Channel lineup varies by market. Streaming quality depends on connection speed.",
        "valid_from": date(2026, 5, 1), "valid_to": date(2026, 12, 31),
        "products": ["stream-select"],
    },
    {
        "code": "OF-1011", "slug": "advanced-wifi-add-on", "name": "Advanced WiFi Add-On",
        "category": Category.ADDON, "status": Status.ACTIVE, "badges": "Easy attach",
        "blurb": "Whole-home WiFi with security and parental controls. The easiest attach on any install.",
        "price": D("7.00"), "price_period": "/mo", "was_price": None,
        "points": "WiFi 7 router with band steering\nSecurity suite and parental controls\nFree mesh extender on 1 Gig plans\nAttaches to any internet order",
        "commission": D("15"), "spiff": D("10"), "spiff_note": "Attach rate bonus at 60%+ attach",
        "eligibility": "Any active internet account.",
        "terms": "Equipment must be returned on cancellation or unreturned equipment fee applies.",
        "valid_from": date(2026, 1, 1), "valid_to": date(2026, 12, 31),
        "products": ["advanced-wifi-7-router"],
    },
    {
        "code": "OF-1012", "slug": "home-phone-unlimited-offer", "name": "Home Phone Unlimited",
        "category": Category.VOICE, "status": Status.EXPIRED, "badges": "",
        "blurb": "Standalone unlimited home phone. Replaced by the Triple Play bundle rate.",
        "price": D("24.99"), "price_period": "/mo", "was_price": None,
        "points": "Unlimited nationwide calling\n28 calling features included\nKeep your existing number\nNo contract",
        "commission": D("20"), "spiff": D("0"), "spiff_note": "",
        "eligibility": "Closed to new orders as of Aug 1, 2026.",
        "terms": "Offer retired. Existing customers keep current rate.",
        "valid_from": date(2026, 1, 1), "valid_to": date(2026, 7, 31),
        "products": ["home-phone-unlimited"],
    },
]


INCENTIVES = [
    ("IN-2001", "Double-Play Bonus", Incentive.Kind.SPIFF, Status.ACTIVE, "$75 per bundle sale",
     "Aug 1 - Sep 15, 2026",
     "Paid on every internet + TV bundle installed and active for 30 days.",
     14, 20, "bundles", D("1050"), D("1500"), ["OF-1005"]),
    ("IN-2002", "Gig Push", Incentive.Kind.SPIFF, Status.ACTIVE, "$40 per 1 Gig install",
     "Jul 15 - Sep 30, 2026",
     "Extra payout on every 1 Gig activation, including upgrades from lower tiers.",
     9, 15, "installs", D("360"), D("600"), ["OF-1002"]),
    ("IN-2003", "Mobile Attach Accelerator", Incentive.Kind.TIERED, Status.ACTIVE,
     "$30/line, +$250 at 50 lines", "Aug 1 - Oct 31, 2026",
     "Per-line SPIFF on mobile lines attached to an internet sale, plus a lump bonus at 50 lines.",
     41, 50, "lines", D("1230"), D("1750"), ["OF-1003", "OF-1004"]),
    ("IN-2004", "Weekend Blitz", Incentive.Kind.SPIFF, Status.ENDING, "$25 per 500 Mbps sale",
     "Aug 22 - Aug 31, 2026",
     "Short-window SPIFF on the 500 Mbps tier. Sales must be submitted before Aug 31, 11:59 PM CT.",
     11, 20, "sales", D("275"), D("500"), ["OF-1001"]),
    ("IN-2005", "SMB Growth SPIFF", Incentive.Kind.SPIFF, Status.ACTIVE, "$50 per business account",
     "Q3 2026",
     "Paid on new small-business internet accounts with a signed 24-month term.",
     7, 10, "accounts", D("350"), D("500"), ["OF-1007"]),
    ("IN-2006", "Quota Multiplier", Incentive.Kind.MULTIPLIER, Status.ACTIVE,
     "1.15x on all commission above 100% quota", "Monthly, ongoing",
     "Once monthly unit quota is hit, every additional sale pays 15% above base commission.",
     148, 160, "units", D("0"), D("960"), []),
    ("IN-2007", "Switcher SPIFF", Incentive.Kind.SPIFF, Status.ENDING, "$35 per ported line",
     "Jun 1 - Aug 31, 2026",
     "Paid on mobile lines ported in from a competing carrier. Final week of the program.",
     8, 12, "ports", D("280"), D("420"), ["OF-1009"]),
    ("IN-2008", "Q3 President's Club", Incentive.Kind.RECOGNITION, Status.ACTIVE,
     "Trip + $2,000 bonus", "Jul 1 - Sep 30, 2026",
     "Top 10 agents by net units across the quarter qualify. Currently ranked 4 of 62.",
     412, 480, "net units", D("0"), D("2000"), []),
    ("IN-2009", "Clean Install Bonus", Incentive.Kind.QUALITY, Status.AT_RISK,
     "$300 flat if chargebacks stay under 2%", "Monthly",
     "Paid when 30-day chargebacks stay below 2% of installs. Currently at 1.4% - 2 chargebacks logged.",
     0, 1, "month clean", D("0"), D("300"), []),
]


SALES = [
    (date(2026, 8, 27), "ORD-884210", "M. Alvarez", "OF-1005", 1, D("140"), D("75"), "Pending install"),
    (date(2026, 8, 27), "ORD-884198", "J. Nguyen", "OF-1002", 1, D("110"), D("40"), "Installed"),
    (date(2026, 8, 26), "ORD-884102", "K. Boateng", "OF-1003", 2, D("90"), D("60"), "Active"),
    (date(2026, 8, 26), "ORD-884077", "R. Patel", "OF-1001", 1, D("65"), D("25"), "Installed"),
    (date(2026, 8, 25), "ORD-883940", "Northside Dental", "OF-1007", 1, D("150"), D("50"), "Scheduled"),
    (date(2026, 8, 25), "ORD-883911", "D. Okoro", "OF-1006", 3, D("175"), D("60"), "Installed"),
    (date(2026, 8, 24), "ORD-883806", "L. Fitzgerald", "OF-1010", 1, D("45"), D("15"), "Active"),
    (date(2026, 8, 23), "ORD-883744", "S. Haddad", "OF-1001", 1, D("65"), D("25"), "Chargeback"),
    (date(2026, 8, 23), "ORD-883702", "T. Ramirez", "OF-1011", 1, D("15"), D("10"), "Active"),
    (date(2026, 8, 22), "ORD-883655", "B. Whitmore", "OF-1004", 1, D("25"), D("10"), "Active"),
]


RESOURCES = [
    ("\U0001F4CD", "Serviceability lookup", "Address check"),
    ("\U0001F4DD", "Order entry system", "Submit a sale"),
    ("\U0001F4C5", "Install scheduling", "Truck roll calendar"),
    ("\U0001F4B0", "Commission statements", "Last 24 months"),
    ("\U0001F4DA", "Product knowledge base", "All lines of business"),
    ("\U0001F3AF", "Compliance & scripting", "Required disclosures"),
    ("\U0001F5FA", "Coverage maps", "Internet + mobile"),
    ("\U0001F6E0", "Escalation desk", "Open a ticket"),
]

ANNOUNCEMENTS = [
    (date(2026, 8, 27), "Urgent", "red",
     "Weekend Blitz SPIFF closes Aug 31 at 11:59 PM CT. Orders entered after the cutoff pay base commission only."),
    (date(2026, 8, 25), "Pricing", "amber",
     "Triple Play promo rate drops to $134.97 effective Sep 1. Quote the current rate only through Aug 31."),
    (date(2026, 8, 21), "Product", "",
     "WiFi 7 router now ships as the default gateway on all 1 Gig installs. Update your pitch - no separate add-on charge."),
    (date(2026, 8, 18), "Compliance", "",
     "New disclosure language required on all mobile port-in sales. Script updated in the compliance library."),
]

CONTACTS = [
    ("Agent help desk", "1-800-555-0142"),
    ("Order escalations", "1-800-555-0177"),
    ("Commission disputes", "payouts@example.com"),
    ("Compliance questions", "compliance@example.com"),
]

CUTOFFS = [
    ("Same-day order entry", "9:00 PM CT"),
    ("SPIFF submission", "Last day of window, 11:59 PM CT"),
    ("Install scheduling", "6:00 PM CT for next day"),
    ("Statement close", "Last calendar day"),
]

QUOTAS = [
    ("Internet", 62, 60, "installs"),
    ("Mobile lines", 41, 55, "lines"),
    ("TV / Video", 26, 25, "installs"),
    ("Voice", 12, 12, "lines"),
    ("Advanced WiFi attach", 38, 45, "attaches"),
]



# ==========================================================================
# Incentive-portal data (mirrors the reference POC)
# ==========================================================================
PERIODS = [
    ("August 2026", date(2026, 8, 1), True),
    ("July 2026", date(2026, 7, 1), False),
    ("June 2026", date(2026, 6, 1), False),
    ("May 2026", date(2026, 5, 1), False),
    ("April 2026", date(2026, 4, 1), False),
    ("March 2026", date(2026, 3, 1), False),
]

# threshold, payout, and the plan's own label for the step to this tier
TIERS = [
    ("Contender",    60, D("350"),  "Next 180"),
    ("Contributor", 105, D("750"),  "Next 125"),
    ("Achiever",    150, D("1000"), "Next 70"),
    ("Star",        476, D("1250"), "Top 33"),
]

POINTS_RULES = [
    ("Gig Internet PSU", "GIG", 8),
    ("Internet PSU", "INT PSU", 3),
    ("Video PSU", "VID PSU", 4),
]

MTD = [
    ("GIG", 5, 40, D("2.0"), D("3.8"), True),
    ("INT PSU", 12, 36, D("1.9"), D("3.4"), False),
    ("VID PSU", 6, 24, D("1.7"), D("3.1"), False),
]

BADGES = [
    ("Ignition", "\U0001F680", "First sale of the period", True, False),
    ("First Accelerator", "\u26A1", "Hit an accelerator threshold", True, False),
    ("Rising Star", "\U0001F31F", "Climbed 10 rank positions", True, False),
    ("Hat Trick", "\U0001F3A9", "Three sales in one day", True, False),
    ("Star Tier", "\u2B50", "Reached the Star tier", False, True),
    ("Champion", "\U0001F3C6", "Finished top 10 in the market", False, True),
    ("10-Day Streak", "\U0001F525", "Ten consecutive selling days", True, False),
    ("Goal Getter", "\U0001F3AF", "Hit your monthly target", False, False),
    ("Target Crusher", "\U0001F4A5", "Exceeded target by 25%", False, False),
    ("Beast Mode", "\U0001F981", "Top performer two months running", False, False),
    ("Cap Hit", "\U0001F4B0", "Reached the payout cap", False, False),
]

TREND = [("Jan", D("3120")), ("Feb", D("2890")), ("Mar", D("4010")),
         ("Apr", D("3450")), ("May", D("3980")), ("Jun", D("4245"))]

# name, short_code, blurb, progress, goal, unit, points, dollars, rate, rate_label,
# days_left, points_based, bucket, status
PROGRAMS = [
    ("2 Gig Break the Bank", "Inc 01",
     "Sell one 2 Gig Internet unit and earn $10. No cap - every unit counts!",
     6, 50, "units", 10, D("60"), D("10"), "$10/unit", 5, False, "active", Status.ACTIVE),
    ("5G Home Gateway", "Inc 10",
     "Sell 5G Home Internet gateways in eligible coverage areas.",
     1, 5, "gateways", 700, D("0"), D("0"), "700 pts", 19, True, "active", Status.ACTIVE),
    ("Points Incentive", "Inc 00",
     "Earn points across all incentives to climb the leaderboard.",
     120, 605, "pts", 120, D("0"), D("0"), "points", 26, True, "active", Status.ACTIVE),
    ("Mobile Line Blitz", "Inc 22",
     "Attach a mobile line to any new internet order. Double points for the first week.",
     0, 25, "lines", 40, D("0"), D("0"), "40 pts/line", 24, True, "launched", Status.ACTIVE),
    ("May Mobile Sprint", "Inc M5 01",
     "Mobile line sprint that ran through May.",
     350, 350, "pts", 350, D("0"), D("0"), "350 pts", 0, True, "previous", Status.EXPIRED),
]

# subject, category, priority, status, day-of-month
DISPUTES = [
    ("Commission is missing on order 884210", "Commission Error", "High", "Awaiting lead", 26),
    ("Accelerator bonus not included in August payout",
     "Bonus / SPIF Not Applied", "Medium", "In Review", 24),
    ("Bundle commission rate applied incorrectly", "Commission Error", "High", "Awaiting lead", 22),
    ("Clawback applied after customer reconnected", "Clawback Dispute", "Low", "Rejected", 21),
    ("2 Gig SPIFF missing for three installs", "Bonus / SPIF Not Applied", "High", "Awaiting lead", 19),
    ("Mobile line credited to the wrong agent", "Commission Error", "Medium", "In Review", 18),
    ("Payout short by $140 against statement", "Missing Payout", "High", "Awaiting lead", 17),
    ("Chargeback on a customer still active", "Clawback Dispute", "Medium", "In Review", 15),
    ("Attach bonus not paid on WiFi add-on", "Bonus / SPIF Not Applied", "Low", "Resolved", 14),
    ("Gig install paid at standard rate", "Commission Error", "Medium", "Resolved", 12),
    ("Weekend Blitz SPIFF missing entirely", "Bonus / SPIF Not Applied", "High", "In Review", 11),
    ("Two payouts missing from the August run", "Missing Payout", "High", "Awaiting lead", 9),
    ("Clawback for a cancelled order I never sold", "Clawback Dispute", "Medium", "Awaiting lead", 7),
    ("Retail bundle rate lower than plan", "Commission Error", "Low", "Rejected", 5),
]

QUESTS = [
    ("Quote three bundles", "Pitch the double-play on three calls today", "📦", 30, 2, 3),
    ("Attach Advanced WiFi", "Add WiFi to any internet order", "📡", 20, 1, 2),
    ("Log a 2 Gig sale", "One 2 Gig unit closes the daily streak", "⚡", 50, 1, 1),
    ("Clear a dispute", "Resolve or escalate one open ticket", "📋", 15, 0, 1),
]

# region -> product, category, units, change %, attach %
TRENDS = {
    "Southwest Region": [
        ("Internet Ultra 1 Gig",   Category.INTERNET, 412, D("18.4"), D("62.0")),
        ("Mobile Unlimited",       Category.MOBILE,   386, D("24.1"), D("38.5")),
        ("2 Gig Internet",         Category.INTERNET, 244, D("31.7"), D("29.0")),
        ("TV Select",              Category.TV,       198, D("-6.2"), D("71.0")),
        ("5G Home Gateway",        Category.INTERNET, 156, D("42.3"), D("21.5")),
        ("Advanced WiFi",          Category.ADDON,    141, D("9.8"),  D("46.0")),
        ("Home Phone Unlimited",   Category.VOICE,     64, D("-14.5"), D("83.0")),
    ],
    "Northeast Region": [
        ("Mobile Unlimited",       Category.MOBILE,   441, D("27.6"), D("35.0")),
        ("Internet Ultra 1 Gig",   Category.INTERNET, 358, D("11.2"), D("58.0")),
        ("Stream Select",          Category.TV,       262, D("35.9"), D("24.0")),
        ("2 Gig Internet",         Category.INTERNET, 187, D("16.8"), D("33.0")),
        ("Advanced WiFi",          Category.ADDON,    173, D("6.4"),  D("51.0")),
        ("TV Select",              Category.TV,       129, D("-9.7"), D("68.0")),
        ("Business Internet 600",  Category.BUSINESS,  88, D("21.5"), D("44.0")),
    ],
}

# region -> channel, icon, agents, spend, attainment %, avg payout, change %
CHANNELS = {
    "Southwest Region": [
        ("Retail Stores",     "🏪", 4980, D("1820000"), 71, D("2040"), D("4.2")),
        ("Inbound Call Centre", "📞", 3920, D("856000"),  63, D("1015"), D("-1.8")),
        ("Outbound Telesales", "📢", 2480, D("628000"),  66, D("1006"), D("2.1")),
        ("Door-to-Door",      "🚪", 1980, D("528000"),  74, D("1980"), D("6.8")),
        ("Indirect / Dealer", "🤝", 3210, D("386000"),  51, D("742"),  D("0.3")),
    ],
    "Northeast Region": [
        ("Retail Stores",     "🏪", 3640, D("1310000"), 68, D("1890"), D("2.9")),
        ("Inbound Call Centre", "📞", 2870, D("712000"),  70, D("1120"), D("5.4")),
        ("Outbound Telesales", "📢", 1930, D("441000"),  59, D("948"),  D("-3.1")),
        ("Indirect / Dealer", "🤝", 2450, D("298000"),  55, D("806"),  D("1.2")),
    ],
}

NOTIFICATIONS = [
    ("Exception Flagged", "Agent John Kim has an anomaly of $3,200 in Retail channel.", "2m ago", "red"),
    ("Plan Submitted", "Q1 Retail Incentive Plan submitted for approval.", "18m ago", ""),
    ("Plan Approved", "National Sales Accelerator plan approved by VP Operations.", "1h ago", "green"),
    ("Attainment Milestone", "Sofia Delgado hit 125% attainment - top performer this month.", "2h ago", "green"),
    ("Exception Flagged", "Duplicate payout detected for Agent #4821 - $1,450 held for review.", "3h ago", "red"),
    ("Month-End Close Done", "February 2026 payroll calculations completed successfully.", "5h ago", "green"),
    ("Plan Submitted", "Digital Growth Bonus Plan submitted by Analyst Sarah Chen.", "8h ago", ""),
    ("Quota Update", "Q1 2026 quotas updated for 42 agents across 3 regions.", "1d ago", ""),
    ("Plan Activated", "Enterprise Retention Bonus plan is now live for March 2026.", "1d ago", "green"),
    ("Approval Overdue", "SMB Channel Incentive plan has been pending approval for 3 days.", "2d ago", "amber"),
]

class Command(BaseCommand):
    help = "Seed the portal with demo agents, offers, incentives and products."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete existing portal rows before seeding.",
        )

    def _say(self, msg, style=None):
        """Respect --verbosity 0 so the test suite stays quiet."""
        if self.verbosity:
            self.stdout.write(style(msg) if style else msg)

    @transaction.atomic
    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        if options["reset"]:
            self._say("Clearing existing portal data...")
            for model in (Persona, SavedPlan, Dispute, Notification, Scorecard,
                          MtdCategory, TrendPoint, Badge, PointsRule, Tier, Period, Quest,
                          Scorecard,
                          Sale, Incentive, Offer, Spec, SpecGroup, Highlight,
                          IncentivePlan, MarketTrend, Channel, Budget,
                          PayoutException, Team,
                          ProductLink, Product, Quota, PerformanceSnapshot, AgentProfile,
                          Announcement, Resource, SupportContact, Cutoff):
                model.objects.all().delete()

        agent = self._seed_agent()
        self._seed_org(agent)
        self._seed_personas(agent)
        self._seed_incentive_portal(agent)
        products = self._seed_products()
        offers = self._seed_offers(products)
        self._seed_sales(agent, offers)
        self._seed_content()

        self._say(self.style.SUCCESS(f"\nSeeded {Product.objects.count()} products, "
            f"{Offer.objects.count()} offers, "
            f"{Incentive.objects.count()} incentives, "
            f"{Spec.objects.count()} spec rows."
        ))
        self._say(self.style.SUCCESS("Sign in at /login/ - pick any of the three roles (no password)"
        ))

    # ----------------------------------------------------------------
    def _seed_agent(self):
        # A profile from an earlier seed may still hold this agent_id under a
        # different user (the demo persona changed). Clear it before claiming it.
        AgentProfile.objects.filter(agent_id="AG-40921").exclude(
            user__username=AGENT_USERNAME
        ).delete()
        # Demo identities from earlier seeds, replaced by the current one.
        User.objects.filter(
            username__in=["rchandaluri", "mrodriguez"]
        ).exclude(username=AGENT_USERNAME).delete()

        user, created = User.objects.get_or_create(
            username=AGENT_USERNAME,
            defaults={
                "first_name": "Jenny",
                "last_name": "Liu",
                "email": "jenny.liu@example.com",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(AGENT_PASSWORD)
            user.save()
            self._say(f"Created user {AGENT_USERNAME}")

        agent, _ = AgentProfile.objects.update_or_create(
            user=user,
            defaults={
                "agent_id": "AG-40921",
                "role": "Residential Inbound Agent",
                "channel": "Inbound Sales - Residential",
                "market": "Dallas / Fort Worth - TX",

                "manager": "A. Whitfield",
                "tier": "Gold",
                "agent_since": "March 2023",
                "department": "Residential Inbound",
                "supervisor": "J. Smith",
                "manager": "S. Chen",
                "points_balance": 8200,
                "xp": 5820,          # level 12, 320 XP into the level
                "streak_days": 14,
                "last_seen": date(2026, 8, 27),
            },
        )

        agent.quotas.all().delete()
        for i, (lob, sold, target, unit) in enumerate(QUOTAS):
            Quota.objects.create(agent=agent, lob=lob, sold=sold, target=target, unit=unit, order=i)

        PerformanceSnapshot.objects.update_or_create(
            agent=agent, period="August 2026",
            defaults={
                "days_left": 3, "units_sold": 148, "unit_target": 160,
                "gross_commission": D("6420.00"), "spiff_earned": D("1875.00"),
                "pending_payout": D("2140.00"), "next_payout_date": "Sep 15, 2026",
                "last_month_commission": D("5780.00"), "close_rate": D("31.4"),
                "chargebacks": 2, "chargeback_amount": D("-180.00"),
                "rank": 4, "rank_of": 62, "ytd_earned": D("48930.00"),
                "is_current": True,
                "calls_handled": 471, "calls_converted": 148,
                "avg_handle_time": "8:42", "attach_rate": D("61.5"),
                "queue_position": 3,
            },
        )
        return agent

    # ----------------------------------------------------------------
    def _seed_org(self, agent):
        """
        Build the whole hierarchy and give every person their own data, so
        switching persona at sign-in shows genuinely different numbers.
        """
        # Tiers first: every scorecard below resolves its current tier against
        # this table, so it has to exist before the agents are written.
        self._seed_tiers()

        profiles = {}
        teams = []

        # -- people first; teams reference them --
        for username, first, last, agent_id, role, team_ix, attainment, accent in PEOPLE:
            if username == AGENT_USERNAME:
                user = agent.user
                profile = agent
            else:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={"first_name": first, "last_name": last,
                              "email": f"{first.lower()}.{last.lower()}@example.com"},
                )
                if created:
                    user.set_password(AGENT_PASSWORD)
                    user.save()
                profile, _ = AgentProfile.objects.get_or_create(
                    user=user, defaults={"agent_id": agent_id}
                )
            profile.agent_id = agent_id
            profile.role = ROLE_LABEL[role]
            profile.role_type = ROLE_ENUM[role]
            profile.channel = "Inbound Sales - Residential"
            profile.department = "Residential Inbound"
            profile.tier = "Gold"
            profile.agent_since = "2024"
            profile.points_balance = 900 + attainment * 42
            profile.xp = 300 + attainment * 48
            profile.streak_days = max(1, attainment // 12)
            profile.save()
            profiles[username] = profile

        # -- teams --
        for i, (name, region, manager_username) in enumerate(TEAMS):
            team, _ = Team.objects.update_or_create(
                name=name,
                defaults={"region": region, "order": i,
                          "manager": profiles[manager_username]},
            )
            teams.append(team)

        # -- wire people to teams --
        lead_for = {}
        for username, first, last, agent_id, role, team_ix, attainment, accent in PEOPLE:
            profile = profiles[username]
            if team_ix is None:
                profile.market = ("Dallas / Fort Worth - TX" if username == "gchen"
                                  else "New York - NY")
                profile.save(update_fields=["market"])
                continue
            team = teams[team_ix]
            profile.team = team
            profile.market = team.region
            if role == "lead":
                team.lead = profile
                team.save(update_fields=["lead"])
                lead_for[team_ix] = profile
            profile.save(update_fields=["team", "market"])

        # -- per-person detail --
        for username, first, last, agent_id, role, team_ix, attainment, accent in PEOPLE:
            profile = profiles[username]
            team = teams[team_ix] if team_ix is not None else None
            profile.supervisor = lead_for[team_ix].full_name if team_ix in lead_for else ""
            profile.manager = (team.manager.full_name if team and team.manager else "")
            profile.save(update_fields=["supervisor", "manager"])

            if role != "agent":
                continue

            self._seed_agent_detail(profile, attainment)

        self._say(
            f"Seeded {Team.objects.count()} teams, "
            f"{AgentProfile.objects.filter(role_type=RoleType.AGENT).count()} field agents, "
            f"{AgentProfile.objects.filter(role_type=RoleType.LEAD).count()} leads, "
            f"{AgentProfile.objects.filter(role_type=RoleType.MANAGER).count()} managers"
        )
        return profiles

    # ----------------------------------------------------------------
    def _seed_tiers(self):
        for i, (name, threshold, payout, label) in enumerate(TIERS):
            Tier.objects.update_or_create(
                name=name,
                defaults={"threshold_points": threshold, "payout": payout,
                          "next_label": label, "order": i},
            )

    # ----------------------------------------------------------------
    def _seed_agent_detail(self, profile, attainment):
        """Quota, scorecard, trend, MTD split, badges and quests for one agent."""
        points = attainment + 51
        rank = max(1, 150 - attainment)

        profile.quotas.all().delete()
        Quota.objects.create(agent=profile, lob="Total units",
                             sold=attainment, target=100, unit="units", order=0)

        PerformanceSnapshot.objects.update_or_create(
            agent=profile, period="August 2026",
            defaults={
                "days_left": 3, "units_sold": attainment, "unit_target": 100,
                "gross_commission": D(attainment * 45),
                "spiff_earned": D(attainment * 14),
                "pending_payout": D(attainment * 18),
                "next_payout_date": "Sep 15, 2026",
                "last_month_commission": D(attainment * 42),
                "chargebacks": 0 if attainment > 90 else 1,
                "rank": rank, "rank_of": 150,
                "ytd_earned": D(attainment * 380),
                "is_current": True,
                "calls_handled": attainment * 4,
                "calls_converted": attainment,
                "avg_handle_time": "8:42",
                "attach_rate": D("61.5"),
                "queue_position": max(1, rank // 20),
            },
        )

        Scorecard.objects.update_or_create(
            agent=profile,
            defaults={
                "psid": f"EMP-{70000 + profile.pk}", "job_code": "AE-INB",
                "location": profile.market or "Southwest Region",
                "incentive_id": "RIBSR2606ACQ",
                "rank": rank, "previous_rank": rank + (7 if attainment > 90 else -4),
                "rank_of": 150, "total_points": points,
                "current_tier": Tier.objects.filter(
                    threshold_points__lte=points).order_by("-threshold_points").first(),
                "potential_payout": D(300 + attainment * 2),
                "eligibility": "Eligible",
                "point_streak": max(1, attainment // 18), "period_days": 31,
                "days_remaining": 25,
                "report_date": date(2026, 7, 3),
                "finalization_date": date(2026, 7, 10),
                "pay_date": date(2026, 7, 20),
            },
        )

        profile.trend.all().delete()
        for i, (month, factor) in enumerate(
            [("Jan", 0.74), ("Feb", 0.69), ("Mar", 0.95),
             ("Apr", 0.82), ("May", 0.94), ("Jun", 1.0)]
        ):
            TrendPoint.objects.create(agent=profile, month=month,
                                      amount=D(round(attainment * 41 * factor)), order=i)

        profile.mtd.all().delete()
        for i, (label, vol_f, pts_f, pct, star, focus) in enumerate([
            ("GIG", 0.05, 0.39, D("2.0"), D("3.8"), True),
            ("INT PSU", 0.12, 0.35, D("1.9"), D("3.4"), False),
            ("VID PSU", 0.06, 0.23, D("1.7"), D("3.1"), False),
        ]):
            MtdCategory.objects.create(
                agent=profile, label=label,
                volume=max(1, int(attainment * vol_f)),
                points=max(1, int(points * pts_f)),
                pct_of_points=pct, star_pct=star, is_focus=focus, order=i,
            )

        # Higher attainment unlocks more badges.
        unlocked = min(len(BADGES), max(2, attainment // 13))
        profile.badges.all().delete()
        for i, (name, icon, desc, _earned, milestone) in enumerate(BADGES):
            Badge.objects.create(
                agent=profile, name=name, icon=icon, description=desc,
                is_earned=i < unlocked, is_milestone=milestone, order=i,
            )

        profile.quests.all().delete()
        for i, (name, desc, icon, xp, progress, goal) in enumerate(QUESTS):
            # Stronger performers are further through the day's quests.
            done = progress + (1 if attainment > 100 and progress < goal else 0)
            Quest.objects.create(
                agent=profile, name=name, description=desc, icon=icon,
                xp=xp, progress=min(goal, done), goal=goal, order=i,
            )

    # ----------------------------------------------------------------
    def _seed_personas(self, agent):
        """Everyone in the org is selectable at sign-in, grouped by role."""
        Persona.objects.all().delete()
        for i, (username, first, last, agent_id, role, team_ix, attainment, accent) in enumerate(PEOPLE):
            profile = AgentProfile.objects.filter(user__username=username).first()
            if profile is None:
                continue
            if role == "agent":
                title = f"Field Agent - {profile.team.name if profile.team else 'Unassigned'}"
            elif role == "lead":
                title = f"Team Lead - {profile.team.name if profile.team else 'Unassigned'}"
            else:
                title = f"Manager - {profile.market}"

            Persona.objects.create(
                slug=username, name=profile.full_name, title=title,
                blurb=ROLE_BLURB[role], accent=accent, role_type=ROLE_ENUM[role],
                is_available=True, user=profile.user, order=i,
            )
        self._say(f"Seeded {Persona.objects.count()} sign-in personas")

    # ----------------------------------------------------------------
    def _seed_incentive_portal(self, agent):
        """Periods, tiers, points structure, badges, programs, disputes."""
        for i, (label, starts, current) in enumerate(PERIODS):
            Period.objects.update_or_create(
                label=label,
                defaults={"starts_on": starts, "is_current": current, "order": i},
            )

        self._seed_tiers()
        tiers = {t.name: t for t in Tier.objects.all()}

        for i, (label, short, points) in enumerate(POINTS_RULES):
            PointsRule.objects.update_or_create(
                label=label,
                defaults={"short_label": short, "points": points, "order": i},
            )

        agent.trend.all().delete()
        for i, (month, amount) in enumerate(TREND):
            TrendPoint.objects.create(agent=agent, month=month, amount=amount, order=i)

        Scorecard.objects.update_or_create(
            agent=agent,
            defaults={
                "psid": "EMP-78432", "job_code": "AE-INB",
                "location": "Southwest Region", "incentive_id": "RIBSR2606ACQ",
                "rank": 40, "previous_rank": 47, "rank_of": 150, "total_points": 154,
                "current_tier": tiers["Achiever"], "potential_payout": D("500"),
                "eligibility": "Eligible",
                "point_streak": 5, "period_days": 31, "days_remaining": 25,
                "report_date": date(2026, 7, 3),
                "finalization_date": date(2026, 7, 10),
                "pay_date": date(2026, 7, 20),
            },
        )

        # Replace the old commission/SPIFF programs with the POC ones.
        SavedPlan.objects.all().delete()
        Incentive.objects.all().delete()
        for i, row in enumerate(PROGRAMS):
            (name, code, blurb, progress, goal, unit, points, dollars,
             rate, rate_label, days_left, points_based, bucket, status) = row
            Incentive.objects.create(
                code=f"IN-{3000 + i}", short_code=code, name=name,
                kind=Incentive.Kind.SPIFF, status=status,
                payout=rate_label, period="August 2026", description=blurb,
                progress=progress, goal=goal, unit=unit,
                earned=dollars, potential=dollars if dollars else D("0"),
                points_earned=points, rate_per_unit=rate, unit_rate_label=rate_label,
                days_left=days_left, is_points_based=points_based, bucket=bucket,
                order=i,
            )

        Dispute.objects.all().delete()
        roster = list(AgentProfile.objects.filter(role_type=RoleType.AGENT))
        for i, (subject, category, priority, status, day) in enumerate(DISPUTES):
            Dispute.objects.create(
                agent=roster[i % len(roster)] if roster else agent,
                ticket_no=f"TKT-{i + 1:05d}",
                subject=subject, category=category, priority=priority,
                status=status, raised_on=date(2026, 8, day),
            )

        MarketTrend.objects.all().delete()
        for region, rows in TRENDS.items():
            for i, (product, category, units, change, attach) in enumerate(rows):
                MarketTrend.objects.create(
                    region=region, product=product, category=category,
                    units=units, change_pct=change, attach_rate=attach,
                    period="August 2026", order=i,
                )

        # A couple of plans already in flight, so the queue is not empty.
        IncentivePlan.objects.all().delete()
        leads = {t.name: t.lead for t in Team.objects.select_related("lead")}
        for team_name, name, product, category, amount, target, status, note in [
            ("DFW Inbound Queue 4", "5G Gateway Push - September", "5G Home Gateway",
             Category.INTERNET, D("15"), 120, IncentivePlan.State.SUBMITTED, ""),
            ("DFW Inbound Queue 7", "Mobile Attach Sprint", "Mobile Unlimited",
             Category.MOBILE, D("12"), 200, IncentivePlan.State.SUBMITTED, ""),
            ("NYC Inbound Queue 2", "Stream Select Launch Bonus", "Stream Select",
             Category.TV, D("10"), 150, IncentivePlan.State.APPROVED,
             "Good read on the trend - approved."),
            ("DFW Inbound Queue 4", "Home Phone Revival", "Home Phone Unlimited",
             Category.VOICE, D("25"), 80, IncentivePlan.State.REJECTED,
             "Declining category. Put the budget behind 2 Gig instead."),
        ]:
            team = Team.objects.filter(name=team_name).first()
            if not team or not team.lead:
                continue
            IncentivePlan.objects.create(
                name=name, team=team, product=product, category=category,
                reward_type=IncentivePlan.Reward.CASH, reward_amount=amount,
                target_units=target, runs_from=date(2026, 9, 1),
                runs_to=date(2026, 9, 30), status=status,
                created_by=team.lead,
                decided_by=team.manager if status in (
                    IncentivePlan.State.APPROVED, IncentivePlan.State.REJECTED) else None,
                decision_note=note,
                rationale=f"{product} is moving in {team.region}; a per-unit "
                          f"incentive should lift attach on the back of it.",
            )

        Channel.objects.all().delete()
        for region, rows in CHANNELS.items():
            for i, (name, icon, agents, spend, att, avg, change) in enumerate(rows):
                Channel.objects.create(
                    region=region, name=name, icon=icon, agents=agents,
                    spend=spend, attainment=att, avg_payout=avg,
                    change_pct=change, order=i,
                )

        Budget.objects.all().delete()
        for region, amount in [("Southwest Region", D("250000")),
                               ("Northeast Region", D("210000")),
                               ("Dallas / Fort Worth - TX", D("250000")),
                               ("New York - NY", D("210000"))]:
            Budget.objects.update_or_create(
                region=region, period="August 2026", defaults={"amount": amount})

        # Exceptions are derived from the roster, not invented: the flags
        # describe conditions you can verify on the agents' own pages.
        PayoutException.objects.all().delete()
        roster = list(AgentProfile.objects.filter(role_type=RoleType.AGENT))
        payouts = []
        for a in roster:
            snap = a.snapshots.filter(is_current=True).first()
            if snap:
                payouts.append((a, snap))
        if payouts:
            avg = sum(s.pending_payout for _, s in payouts) / len(payouts)
            for a, snap in payouts:
                if snap.pending_payout > avg * D("1.35"):
                    PayoutException.objects.create(
                        agent=a, kind=PayoutException.Kind.HIGH_PAYOUT,
                        amount=snap.pending_payout,
                        detail=(f"Pending payout is {round(snap.pending_payout / avg, 1)}x the "
                                f"regional average of ${avg:,.0f} - confirm before disbursement."),
                        flagged_on=date(2026, 8, 27),
                    )
                elif a.attainment < 62:
                    PayoutException.objects.create(
                        agent=a, kind=PayoutException.Kind.LOW_VOLUME,
                        amount=snap.pending_payout,
                        detail=(f"{snap.units_sold} units against a {snap.unit_target} target "
                                f"({a.attainment}%) - well below channel norm."),
                        flagged_on=date(2026, 8, 25),
                    )
        self._say(f"Seeded {Channel.objects.count()} channels, "
                  f"{PayoutException.objects.count()} exceptions, "
                  f"{Budget.objects.count()} budgets")

        self._say(f"Seeded {MarketTrend.objects.count()} trend rows, "
                  f"{IncentivePlan.objects.count()} incentive plans")

        Notification.objects.all().delete()
        for i, (kind, text, ago, tone) in enumerate(NOTIFICATIONS):
            Notification.objects.create(kind=kind, text=text, ago=ago, tone=tone, order=i)

        self._say(
            f"Seeded {Incentive.objects.count()} programs, {Badge.objects.count()} badges, "
            f"{Tier.objects.count()} tiers, {Dispute.objects.count()} disputes, "
            f"{Quest.objects.count()} quests"
        )

    # ----------------------------------------------------------------
    def _seed_products(self):
        by_slug = {}
        for i, data in enumerate(PRODUCTS):
            product, _ = Product.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"], "sku": data["sku"],
                    "category": data["category"], "icon": data["icon"],
                    "description": data["description"],
                    "price_note": data["price_note"], "order": i,
                },
            )
            product.highlights.all().delete()
            product.links.all().delete()
            product.spec_groups.all().delete()

            for j, (label, value) in enumerate(data["highlights"]):
                Highlight.objects.create(product=product, label=label, value=value, order=j)

            for j, (label, url, icon) in enumerate(data["links"]):
                ProductLink.objects.create(product=product, label=label, url=url, icon=icon, order=j)

            for j, (group_name, rows) in enumerate(data["specs"]):
                group = SpecGroup.objects.create(product=product, name=group_name, order=j)
                for k, (label, value) in enumerate(rows):
                    Spec.objects.create(group=group, label=label, value=value, order=k)

            by_slug[data["slug"]] = product

        self._say(f"Seeded {len(by_slug)} products")
        return by_slug

    # ----------------------------------------------------------------
    def _seed_offers(self, products):
        by_code = {}
        for i, data in enumerate(OFFERS):
            product_slugs = data.pop("products")
            offer, _ = Offer.objects.update_or_create(
                code=data["code"], defaults={**data, "order": i},
            )
            offer.products.set([products[s] for s in product_slugs])
            by_code[data["code"]] = offer
            data["products"] = product_slugs  # restore so re-runs work

        self._say(f"Seeded {len(by_code)} offers")
        return by_code

    # ----------------------------------------------------------------
    def _seed_incentives(self, offers):
        for i, row in enumerate(INCENTIVES):
            (code, name, kind, status, payout, period, desc,
             progress, goal, unit, earned, potential, offer_codes) = row
            incentive, _ = Incentive.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "kind": kind, "status": status, "payout": payout,
                    "period": period, "description": desc, "progress": progress,
                    "goal": goal, "unit": unit, "earned": earned,
                    "potential": potential, "order": i,
                },
            )
            incentive.offers.set([offers[c] for c in offer_codes])
        self._say(f"Seeded {len(INCENTIVES)} incentive programs")

    # ----------------------------------------------------------------
    def _seed_sales(self, agent, offers):
        for sold_on, order_no, customer, offer_code, units, base, spiff, status in SALES:
            Sale.objects.update_or_create(
                order_no=order_no,
                defaults={
                    "agent": agent, "sold_on": sold_on, "customer": customer,
                    "offer": offers[offer_code], "units": units,
                    "base": base, "spiff": spiff, "status": status,
                },
            )
        self._say(f"Seeded {len(SALES)} sales")

    # ----------------------------------------------------------------
    def _seed_content(self):
        for i, (icon, label, meta) in enumerate(RESOURCES):
            Resource.objects.update_or_create(
                label=label, defaults={"icon": icon, "meta": meta, "url": "#", "order": i}
            )
        for posted_on, tag, tone, text in ANNOUNCEMENTS:
            Announcement.objects.update_or_create(
                posted_on=posted_on, tag=tag, defaults={"tone": tone, "text": text}
            )
        for i, (label, value) in enumerate(CONTACTS):
            SupportContact.objects.update_or_create(label=label, defaults={"value": value, "order": i})
        for i, (label, value) in enumerate(CUTOFFS):
            Cutoff.objects.update_or_create(label=label, defaults={"value": value, "order": i})
        self._say("Seeded resources, announcements, contacts and cutoffs")
