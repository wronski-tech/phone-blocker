# Glossary

| Term | Meaning |
|---|---|
| **BIP** | Biuletyn Informacji Publicznej, the official public-information portal every Polish public institution must have; its register at gov.pl lists institutions with contact cards. Source `bip`. |
| **Call Directory extension** | The iOS extension (`CXCallDirectoryProvider`) through which an app gives iOS lists of numbers to block or label. It only accepts individual numbers, in ascending order. |
| **CEIDG** | Centralna Ewidencja i Informacja o Działalności Gospodarczej, the register of sole traders. Source `ceidg`. |
| **E.164** | International number format, `+48717777777`. The backend stores it without `+` as an integer, which is iOS's `CXCallDirectoryPhoneNumber`. |
| **Listing** | One number published by one organization (`listings` table), with a kind (`phone`/`fax`) and an optional department. |
| **Live Caller ID Lookup** | iOS 18 feature where the phone asks a server about an incoming number using private information retrieval, without revealing the number. Planned; would allow rules and spoofing checks on the phone. |
| **NFZ** | Narodowy Fundusz Zdrowia, the national health fund; its "Terminy leczenia" API lists contracted clinics. Source `nfz`. |
| **ntfy** | Simple push-notification service (ntfy.sh or self-hosted) used for alerts. |
| **Personal settings** | Your own always-block / never-block and label for a number; they beat everything else. |
| **Prefix rule** | Block or allow every number starting with a prefix, e.g. `+44 70`. |
| **Rejestr Aptek** | The pharmacy register run by Centrum e-Zdrowia. Source `apteki`. |
| **REGON / NIP** | Polish statistical and tax identification numbers, stored on organizations when the source provides them. |
| **RPWDL** | Rejestr Podmiotów Wykonujących Działalność Leczniczą, the register of healthcare providers. Source `rpwdl`. |
| **RSPO** | Rejestr Szkół i Placówek Oświatowych, the school register (not imported; API needs an access request). |
| **Source** | One importer module in `sources/` and the organizations it owns (`organizations.source`). |
| **`source_id`** | An organization's identity within its source (BIP card URL, RPWDL book id, pharmacy id, …). |
| **Spoofed number** | A caller ID faked by the caller. Calls from Polish ranges UKE assigned to no operator must be spoofed. |
| **Sync version** | Increasing counter stamped on a number whenever its label or block changes; the phone syncs "everything after version N". |
| **Trunk zero** | The 0 formerly dialled before Polish area codes (`071 …`); `find_numbers` strips it. |
| **UKE** | Urząd Komunikacji Elektronicznej, the telecom regulator; publishes which operator holds each number range. Source `uke`. |
| **Unassigned range** | A UKE range held as a reserve (operator id 99990 and up), so no real subscriber has those numbers. |
