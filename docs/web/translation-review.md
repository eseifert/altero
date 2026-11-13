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

The remaining 41 non-English catalogs still need these messages. Both English
variants already contain them. Earlier German and Spanish review passes predate
this new registration copy.

## Existing wording

The last deletion-warning inventory identified 28 catalogs without the earlier
focused pass. Review must state that permanent library deletion/replacement moves
nothing to Trash, rather than claiming that the library has no Trash. Broader
review must keep item records distinct from account/activity records and preserve
the difference between ending sessions, closing browser tabs and deleting data.

## Validation

Run the standalone catalog check described in the
[translation guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#translating-the-interface).
Use existing behavior and browser checks for locale selection, registration,
direction and layout. Do not add tests that assert particular translated words
or duplicate each workflow for every catalog.
