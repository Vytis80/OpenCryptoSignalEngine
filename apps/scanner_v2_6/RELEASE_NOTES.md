# V2.6.0-rc1 release notes

## Signalų branduolys

- V2.5 funkcija palikta užšaldyta kaip palyginimo bazė; gamybinis `analyze` yra naujas v2.6 branduolys.
- Pridėtas 4H režimas ir bent 2 uždarytų 1M patvirtinimų hard gate.
- 5M trigeriai sugriežtinti: patvirtintas breakout/breakdown retestas, EMA reakcija arba liquidity sweep/reclaim.
- Pridėti neapeinami 4H/1H/15M krypties, spread, ATR diapazono, paskutinės 5M žvakės dydžio, anti-chase ir rejection vartai.
- Struktūrinis SL tikrinamas ir ATR, ir procentais. Per platus BTR tipo setupas atmetamas, o ne siunčiamas su nepraktiškais lygiais.
- Kliūtis imama iš artimiausio 15M arba 1H support/resistance; saugi erdvė turi būti bent `1.8R`.
- TP lieka tikslūs `1R/2R/3R`; EXECUTE/POTENTIAL ribos lieka `82/70`.
- `Setup Score` ir `Historical edge` atskirti. Istorinis edge skaičiuojamas pagal tą patį setupą, kryptį ir core versiją su 40/30/30 TP prielaida bei kaštais.
- Pridėtas be-lookahead Bybit 1m replay, v2.5/v2.6 A-B ataskaita ir fail-closed promotion gate.
- SHADOW nekeičia v2.6 sprendimo, Entry, SL ar TP.

## Nauja v2.6

- 42 deep-analysis slotai per ciklą, iš jų 20 skirta least-recently-scanned fair rotation.
- Coverage laikomas atliktu tik po sėkmingos pilnos analizės; klaidos automatiškai lieka greitam retry.
- ACTIVE duomenų freshness guard; stale kainos/kontekstas negali sukelti invalidation ar management sprendimo.
- Bybit WS watchdog, per-symbol freshness ir pagreitintas REST fallback.
- Bybit HTTP 403 atveju 10 min fail-fast IP cooldown; 429/5xx/webhook retry ir telemetrija.
- Vienkartiniai `DATA STALE` / `DATA RECOVERED` pranešimai.
- Post-TP struktūrinis invalidation uždaro likusios pozicijos signalo lifecycle; BTR tipo amžinas `PROTECT` nepaliekamas.
- Discord shared-bot `merge`: `bybit_*` komandos įkeliamos neliečiant `unrelated_*`.
- Kas 60 s missing-only command audit atkuria Bybit komandas po seno another integration bulk sync.
- Discord Gateway exponential backoff išlieka, bet delay ribojamas iki 60 s.
- Discord ilgi command atsakymai skaidomi į leistinus gabalus.
- Webhook alert delivery retry ir bendras failure skaitiklis.
- `/bybit_edge_stats`, cost-adjusted display-only R, išplėsti setup/shadow/health duomenys.
- Klaidingai kaip tikimybė suprantamas `Confidence` pakeistas į `Setup Score`; `Probability` nerodomas.
- Secret-safe another integration Discord nustatymų importas, preflight ir dinaminis systemd diegimas naujai VM.
- Nauja švari DB: `data/bybit_crypto_scanner_v2_6.db`.

## Release gate

- 22 offline testai.
- Python compileall.
- Shell sintaksės patikra.
- V2.6 strategy hash, užšaldyto v2.5 AST hash ir secret scan.
- Viešas Bybit live testas atliekamas pačioje naujoje VM su `preflight.py --live`.
- RC1 nepromotinamas į gamybą, kol `tools/replay_gate.py` negrąžina `PASS` su pakankama imtimi.
