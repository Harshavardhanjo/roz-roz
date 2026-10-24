"""Demo state from the LLD overview. TODO(Harsha): write these rows and expose POST /api/admin/reset-demo."""

HOUSEHOLD = {"name": "HSR Flat 302", "owner": "Harsha", "roommates": ["Arjun"], "weights": {"Harsha": 1, "Arjun": 1},
             "rules": {"vote_rule": "majority", "two_person_limit_paise": 100000}}

HELPERS = [
    {"name": "Lakshmi", "role": "cook", "lang": "kn", "salary_paise": 1000000, "payday_dom": 31,
     "weekly_off": [6], "paid_leaves_per_month": 2, "deduct_extra_leave": True,
     "advance_auto_limit_paise": 50000, "advance_monthly_limit_paise": 200000,
     "grocery_auto_limit_paise": 50000, "grocery_monthly_budget_paise": 600000},
    {"name": "Ramesh", "role": "driver", "lang": "hi", "salary_paise": 1800000, "payday_dom": 1,
     "weekly_off": [6], "paid_leaves_per_month": 2, "deduct_extra_leave": True,
     "advance_auto_limit_paise": 50000, "advance_monthly_limit_paise": 300000,
     "grocery_auto_limit_paise": 0, "grocery_monthly_budget_paise": 0},
]

OCTOBER_SO_FAR = {"topups_paise": {"Harsha": 800000, "Arjun": 800000}, "lakshmi_advances_paise": [50000, 50000],
                  "grocery_transfer_paise": 400000, "grocery_spent_paise": 370000,
                  "lakshmi_paid_leave_dates": ["2026-10-08", "2026-10-20"]}
