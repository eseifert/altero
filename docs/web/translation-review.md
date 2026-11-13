# Translation review

The source and context review resumed on November 13, 2026. It covers the 36
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

The earlier focused pass covered 31 catalogs. The remaining 28 are being checked
against the deletion and restore workflows: nothing is moved to Trash, even though
the library normally has a Trash. The completed follow-up batches are below.

| Catalogs | Permanent deletion/replacement review |
| --- | --- |
| Breton, Catalan, Estonian, Finnish, Hungarian, Lithuanian | All three warnings reviewed; replace absent-Trash claims and protective metaphors with explicit bypass wording |
| Arabic, Hebrew, Persian, Punjabi (Shahmukhi), Urdu | All three warnings now explicitly state that nothing moves to Trash |
| Bengali, Hindi, Malayalam, Tamil | All three warnings now explicitly state that nothing moves to Trash |
| Georgian, Greek, Korean, Mongolian, Serbian | All three warnings reviewed; make the bypass explicit and retain the library owner and file scope |
| Indonesian, Khmer, Tagalog, Thai, Vietnamese | All three warnings now explicitly state that nothing moves to Trash |

3 catalogs still await this warning pass. Broader review must keep item records
distinct from account/activity records and preserve the difference between ending
sessions, closing browser tabs and deleting data.

## Validation

Run the standalone catalog check described in the
[translation guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#translating-the-interface).
Use existing behavior and browser checks for locale selection, registration,
direction and layout. Do not add tests that assert particular translated words
or duplicate each workflow for every catalog.

The translated Arabic applicant flow has been exercised on desktop and phone
Chromium with a real local SMTP sink: mailbox confirmation, pending review,
cancellation, absent account access, RTL layout and accessibility checks pass.
