# V2.6.0-rc2 update

This note records the final RC2 delta applied after the RC1 signal-core release candidate.

## RC2 changes

- Discord application commands were moved from the old `bybit_*` namespace to the dedicated `byscan_*` namespace so the V2.6 scanner can coexist with the frozen V2.5 integration without command collisions.
- Shared-bot command merge/audit logic now restores only missing `byscan_*` commands and leaves unrelated commands untouched.
- Replay validation skips markets that are no longer valid/available in the current Bybit instrument universe instead of treating those symbols as a strategy failure.
- The scanner runtime and Discord control surface report version `2.6.0-rc2`.
- The public release remains Bybit-only and keeps operational credentials, Discord IDs/tokens, bridge secrets, runtime databases and deployment-specific data outside Git history.

## Validation

RC2 is expected to pass the repository offline gate, scanner regression checks and secret scan before merge.
