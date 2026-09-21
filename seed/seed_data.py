"""Verbatim seed schema — checklist 1.2.

This is the single source of truth for the seeded schema text. Every
requirement string below is transcribed character-for-character from the
user's original spec, with one explicit, user-confirmed transformation:
lines that were word-wrapped across multiple lines in that spec (purely
for chat-message readability) are rejoined into one continuous paragraph
per item, joining at each line break with a single space. No other
change is made — original spelling, punctuation, capitalization
inconsistencies (e.g. Item 3's "centre" vs. other items' "Centre"),
mismatched parentheses (Item 7), and inconsistent spacing around
abbreviations (e.g. "Rs.10/-" vs. "Rs. 100/-") are all preserved as-is.
PROJECT_HARNESS.md §4.1 carries a paraphrased *summary* of this schema
for human readability; this module is the real, verbatim source.

Column naming: the user's spec gives full requirement text per item but
no separate short "name" per column. This module assigns "Item {n}" for
Table 1 and "Document {n}" for Table 2 (echoing the user's own "S.No +
DOCUMENTS" framing of Table 2) as a reasonable default label — these are
freely renamable via the Config tab (checklist 1.3) and do not affect
retrieval, which runs against requirement_text + synonyms, never name.

Each entry is (column_name, requirement_text).
"""
from __future__ import annotations

TABLE_1_NAME = "Table 1"
TABLE_2_NAME = "Table 2"

TABLE_1_ITEMS: list[tuple[str, str]] = [
    ("Item 1", "Item no. as per tender"),
    ("Item 2", "Name of the items"),
    (
        "Item 3",
        "Scanned copy of Manufacturing & Market standing/experience certificate "
        "of minimum \"Three Years\" of the molecule quoted by them duly certified "
        "by centre/State Drug Controller in the Performa Section-XVII. The "
        "certificate should have been issued recently i.e. not more than one "
        "year old from the date of the opening of the tender.",
    ),
    (
        "Item 4",
        "WHO GMP/GMA Certificate — Scanned copy of valid WHO-GMP certificate/ "
        "Valid Schedule 'M' certificate issued by Centre/State Drug Controller "
        "and should not have been issued more than five years old.",
    ),
    (
        "Item 5",
        "Scanned copy of valid manufacturing license issued by Centre/State "
        "Drug Controller indicating the list of products should be submitted. "
        "Public Sector Undertakings with at least \"3-years\" market standing "
        "having manufacturing license issued by Centre/State Drug Controller.",
    ),
    (
        "Item 6",
        "Scanned copy of valid narcotic license issued by Central/State Excise "
        "Commissioner should be submitted by the bidder.",
    ),
    (
        "Item 7",
        "The manufacturing firm should enclose at least one analysis batch "
        "report per for each molecule quoted (i.e minimum of two reports of at "
        "least 2-different years of the last four financial years (2021-22, "
        "2022-23, 2023-24, 2024-25 & 2025-26).",
    ),
    (
        "Item 8",
        "If a firm is the sole manufacturer of the product, the same can be "
        "treated as a Proprietary drug, provided the firm submits a certificate "
        "to this effect from the competent authority in India.",
    ),
    (
        "Item 9",
        "In case of newly introduced drugs/molecules, the manufacturer can be "
        "eligible provided the firm submits a certificate from the DCGI, in "
        "this regard. In such cases, the firm has to submit an MMC of the "
        "molecule concerned from the date of issue of Certificate by the DCGI "
        "of the new drug to that firm. In such case MMC of 03 years is not "
        "cleared/completed, it will be relaxed accordingly. Also, in case of "
        "imported Drug/Formulations Form-45 (Permission Certificate) issued by "
        "DCGI will also be accepted.",
    ),
    (
        "Item 10",
        "Production-Capacity assessment certificate: The manufacturing firm "
        "should enclose the certificate issued by the Chartered Accountant/ "
        "concerned State Drug Controller indicating actual production detail "
        "of a particular molecule batch wise for the items quoted and at "
        "least one analysis batch report per year for any two of the last "
        "three years for each molecule quoted (i.e. minimum of two reports of "
        "at least 2-different years of the last three financial years "
        "(2021-22, 2022-23, 2023-24, 2024-25 & 2025-26)) in the enclosed "
        "Performa at Section-XIX. Separate sheets of Section-XIX should be "
        "enclosed for separate schedule.",
    ),
]

TABLE_2_ITEMS: list[tuple[str, str]] = [
    ("Document 1", "Scanned copy of \"Tender Acceptance Form\""),
    ("Document 2", "Checklist and list of item quoted"),
    (
        "Document 3",
        "Section VIII Clause 11: The manufacturing firm quoting for the items "
        "mentioned below have to submit the documents of annual turnover of the "
        "company audited by a Chartered Accountant of the pharmaceutical "
        "products during any three consecutive financial years (2020-21, "
        "2021-22, 2022-23, 2023-24, 2024-25 & 2025-26): I) Narcotic drugs, "
        "Enemas should have minimum annual turnover of Rs. 1.5 Crores. "
        "Niche products/Patented Products/MSE have minimum annual turnover of "
        "Rs. 1.5 Crores. II) Cream/Ointment, lotion, eye/ear drops, mouth "
        "wash/Gargles, Contrast media, I.V fluids (large volume parentrals) "
        "should have a minimum annual turnover of Rs. 30.00 Crores. III) "
        "Tablets, Capsules, Injections should have a minimum annual turnover "
        "of at least Rs. 150.00. 25% or more of the annual turnover shall be "
        "from the trading of the drugs in open market and it should be "
        "exclusive from supply to Government Departments and 3rd Party Sale. "
        "A certificate from the Chartered Accountant with reference to sale in "
        "the open market/sale to the Government Departments and 3rd Party Sale "
        "should be submitted.",
    ),
    (
        "Document 4",
        "Section VIII Clause 10: Copy of GST Registration Certificate to be "
        "furnished. Firm shall furnish a certificate on their letter head "
        "stating that up to date returns have been filed and there are no dues "
        "with the concerned department. Firm will also submit scanned copies "
        "of last 01 (one) year's returns submitted to the concerned department.",
    ),
    (
        "Document 5",
        "Section VIII Clause 18: Scanned copy of Information as per the format "
        "enclosed (Section-XVII) should be submitted with the tender.",
    ),
    (
        "Document 6",
        "Section VIII Clause 13: Scanned copy of Non-conviction certificate "
        "issued by the Centre/State Drug Controller to the effect that the "
        "manufacturer has not been convicted under the Drugs and Cosmetics "
        "Act, 1940 and rules thereunder during the last three years in respect "
        "of any of the drugs for which prices have been quoted by the firm. In "
        "case the DCGI does not mention the name of the molecules in their "
        "certificates, a relevant undertaking will be provided with list of "
        "drug/molecules along with non-conviction certificate, by the vendor "
        "in addition to the above mentioned certificate. Non-Conviction "
        "Certificate must have been issued by the Drug Controller of the "
        "concerned State within preceding one year from the date of the "
        "publication of the tender.",
    ),
    (
        "Document 7",
        "Manufacturing firm should upload the scanned copy of performance "
        "certificate of 02 years for supply of drugs/medicines/iv fluids "
        "within last 05 financial years i.e. 2020-21, 2021-22, 2022-23, "
        "2023-24, 2024-25 and 2025-26 from any Govt. Hospital/PSUs./reputed "
        "hospital/Institutions/International buyer on the purchaser letter "
        "head where the bidder is supplying these items in reference to this "
        "tender. The performance certificate submitted should be issued within "
        "preceding one year from the date of the publication of the tender.",
    ),
    (
        "Document 8",
        "Section VIII Clause 16: Certificate on self attested non-judicial "
        "stamp paper of Rs.10/- stating that there is no vigilance/CBI case "
        "pending against the firm/supplier and the firm has not been "
        "blacklisted/debarred on the date of submission of the bid by any "
        "Central Govt./State Govt. department/hospital/PSUs etc. Bidder should "
        "also provide information regarding blacklisting/debarring of the firm "
        "in last three years (2023-24, 2024-25 and 2025-26) by any Government "
        "or Private organization/Hospital.",
    ),
    (
        "Document 9",
        "Section VIII Clause 17: The firms should give an undertaking to the "
        "effect that they will be legally bound to supply the medicines/drugs, "
        "for which they have quoted the rates in the tender during the "
        "validity of the contract. In case they fail to execute any "
        "supply-order placed to them within 45 days from the date of placement "
        "of purchase order, they will be liable for action against them as per "
        "tender terms.",
    ),
    (
        "Document 10",
        "Scanned copy of Documents confirming to Sole Proprietorship/ "
        "Partnership/Private Limited Firm in the country of origin as the "
        "case may be to be uploaded.",
    ),
    (
        "Document 11",
        "Section VIII Clause 15: The contractor should also give a guarantee "
        "as follows, in case of biological and other products having a "
        "particular life-period, to provide safe-guard against loss on "
        "account of deterioration within their stated period of potency.",
    ),
    (
        "Document 12",
        "Section VIII Clause 19: Section-XVI A) Notarized undertaking on an "
        "affidavit of Rs. 100/-, The Drugs and Cosmetics Rules, 1945, supply "
        "drugs of standard quality. B) Affidavit of Rs. 100/- 5-point "
        "declaration.",
    ),
    ("Document 13", "OEM Authorization."),
]

# (table_name, items) — order matters; this is the order tables are created in.
SEED_SCHEMA: list[tuple[str, list[tuple[str, str]]]] = [
    (TABLE_1_NAME, TABLE_1_ITEMS),
    (TABLE_2_NAME, TABLE_2_ITEMS),
]
