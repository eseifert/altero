# Translation review

The resumed source and context review is complete as of November 13, 2026.
Its scope covers the 36
registration messages added for rc.1, outstanding permanent-deletion warnings,
and consistency of account, permission and library terminology across the 59
catalogs. Preserve each language's established form of address and regional terms.

This records the scope of contributor review, not native-speaker approval.
Catalog validation checks message structure and placeholders; it cannot certify
meaning or idiomatic wording. Native-speaker review remains welcome and necessary.

## Registration messages

The review distinguishes email confirmation, administrator approval and actual
account/library access. Generic acknowledgements and conditional recovery notices
must not promise that an account exists or that an email will always arrive.

| Catalogs | Source/context review |
| --- | --- |
| Afrikaans, Dutch, French, German | All 36 registration messages translated; existing formal/neutral address and account terms retained |
| Catalan, Galician, Italian, Portuguese (Brazil/Portugal), Spanish | All 36 registration messages translated; regional terms and established address retained |
| Danish, Finnish, Icelandic, Norwegian (Bokmål/Nynorsk), Swedish | All 36 registration messages translated; regional terms and established address retained |
| Croatian, Czech, Polish, Serbian, Slovak, Slovenian | All 36 registration messages translated; regional terms and established address retained |
| Bulgarian, Mongolian, Romanian, Russian, Turkish, Ukrainian | All 36 registration messages translated; regional terms and established address retained |
| Basque, Estonian, Greek, Hungarian, Latvian, Lithuanian | All 36 registration messages translated; regional terms and established address retained |
| Chinese (Simplified/Traditional), Japanese, Korean | All 36 registration messages translated; regional terms and established address retained |
| Arabic, Hebrew, Persian, Punjabi (Shahmukhi), Urdu | All 36 registration messages translated; regional terms and established address retained |
| Bengali, Hindi | All 36 registration messages translated; regional terms and established address retained |
| Malayalam, Tamil | All 36 registration messages translated; regional terms and established address retained |
| Indonesian, Tagalog, Vietnamese | All 36 registration messages translated; regional terms and established address retained |
| Khmer, Thai | All 36 registration messages translated; regional terms and established address retained |
| Breton, Swahili | All 36 registration messages translated; regional terms and established address retained |
| Georgian, Hausa, Yoruba | All 36 registration messages translated; regional terms and established address retained |

All 57 non-English catalogs now contain these messages. Both English variants
already contain them. Earlier German and Spanish review passes predate
this new registration copy.

## Existing wording

The earlier focused pass covered 31 catalogs. The remaining 28 were checked
against the deletion and restore workflows: nothing is moved to Trash, even though
the library normally has a Trash. The completed follow-up batches are below.

| Catalogs | Permanent deletion/replacement review |
| --- | --- |
| Breton, Catalan, Estonian, Finnish, Hungarian, Lithuanian | All three warnings reviewed; replace absent-Trash claims and protective metaphors with explicit bypass wording |
| Arabic, Hebrew, Persian, Punjabi (Shahmukhi), Urdu | All three warnings now explicitly state that nothing moves to Trash |
| Bengali, Hindi, Malayalam, Tamil | All three warnings now explicitly state that nothing moves to Trash |
| Georgian, Greek, Korean, Mongolian, Serbian | All three warnings reviewed; make the bypass explicit and retain the library owner and file scope |
| Indonesian, Khmer, Tagalog, Thai, Vietnamese | All three warnings now explicitly state that nothing moves to Trash |
| Hausa, Swahili, Yoruba | All three warnings now explicitly state that nothing moves to Trash |

The 28-catalog follow-up is complete. Together with the earlier 31-catalog pass,
the three permanent library deletion/replacement warnings have been reviewed in
all 59 catalogs. This does not imply native-speaker approval of the full catalogs.

## Consistency and context

The applicant and administrator views display the existing request’s expiry, not
a deadline for submitting a new request. The English source now says “Request
expires”; the corresponding label was checked in every catalog and ambiguous
submission-deadline wording was clarified.

The session controls and password-change notices were checked across all 59
catalogs for ending a session rather than closing a browser or deleting content.
European Portuguese now retains “else”; Korean and Swahili explicitly name the
other browsers, matching the session list and avoiding a promise to revoke other
credentials.

The item, creator, related-item, account, API-key and Trash controls were compared
across catalogs. Mongolian creation/navigation labels now use the same item noun
as the list, while activity records keep their separate noun. Tamil’s new-item
label now matches the item list and detail pane. Breton, Basque, Malayalam and
Bokmål merge notices now name the same Trash as their navigation controls, as do
Tamil, Turkish and Traditional Chinese notices.

Both Chinese variants retain their established 你 address. Later permission and
consent copy had introduced 您 in Simplified Chinese, and an editing notice did
the same in Traditional Chinese; these now match the rest of each interface.
Regional library, account and API-key terms remain distinct. The address/script
audit also checked the documented German, Dutch, Afrikaans, Spanish, Polish,
Romanian, Serbian and Turkish conventions; protocol names, placeholders and
quoted product/navigation labels are intentional exceptions.

The SSO setup notice was checked against provider writes and callback generation.
It previously described a fallback to the incoming request host that the server
no longer permits. The source and all 59 translations now require
`ALTERO_PUBLIC_URL` before setup/use and say callback addresses use that URL only.

The account-suspension and deletion descriptions, collection-removal notices,
OAuth permission ceilings and API-key persistence notices were also compared
with their English sources across all 59 catalogs. They preserve the distinction
between retaining content and deleting it, between personal and group access,
and between signing out of a browser and revoking a credential.

An inventory of values identical to English found keyboard labels, acronyms,
established loanwords and shared words such as “Version”, rather than remaining
untranslated sentences. These were reviewed as candidates and retained where
appropriate. This targeted consistency pass is not a sentence-by-sentence native
review of every message; that remains separate contributor work.

## Validation

Run the standalone catalog check described in the
[translation guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#translating-the-interface).
Use existing behavior and browser checks for locale selection, registration,
direction and layout. Do not add tests that assert particular translated words
or duplicate each workflow for every catalog.

The translated Arabic applicant flow has been exercised on desktop and phone
Chromium with a real local SMTP sink: mailbox confirmation, pending review,
cancellation, absent account access, RTL layout and accessibility checks pass.

Final checks passed with Node 24: all 59 catalogs have 824 canonical keys with
zero validation errors or warnings; all 1,458 frontend tests, TypeScript checks,
the production build and the strict documentation build pass. Desktop and phone
Chromium checks cover locale/script fallback, RTL direction fallback and account
language persistence (six cases), plus the complete registration suite (ten
cases), including SMTP refusal/recovery, approval, rejection and lost replies.
