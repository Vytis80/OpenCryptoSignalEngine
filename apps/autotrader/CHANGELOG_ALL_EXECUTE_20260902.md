# Auto-Trader V1.5 ALL_EXECUTE patch (2026-09-02)

## Veikimas

- Priimami tik galutiniai scannerio `EXECUTE` įvykiai iš V2.5 ir V2.6.
- `SHADOW WOULD BLOCK` sprendimas išsaugomas auditui, tačiau `ALL_EXECUTE` režime nebestabdo orderio.
- Jei kaina nėra tikslioje scannerio entry zonoje, signalas išsaugomas ir automatiškai laukia iki entry zonos arba `expires_at`.
- Po restarto nebaigtas laukimas atkuriamas iš SQLite.
- Maksimalus bot-managed atvirų pozicijų skaičius nustatytas į 20.

## Nepakeistos apsaugos

- Tik Bybit Demo endpointas.
- 1% rizikos nustatymas ir esama sizing / minimum margin formulė.
- Viena pozicija tam pačiam simboliui.
- Signalų galiojimas ir entry zona.
- Balanso, margin, leverage, notional ir instrumentų patikros.
- SL/TP validacija, įrašymas ir read-back patikra.
- TP1 -> breakeven ir monotonic SL guard.
- Idempotency, fills, reconcile, recovery ir orphan pozicijų apsaugos.
- Management įvykių `signal_id` / `event_id` sutapimo patikra.

## Konfigūracija

Aktyvavimo failai yra `deployment/` aplanke. Jie prideda tik du neslaptus nustatymus:

```text
EXECUTION_MODE=ALL_EXECUTE
MAX_OPEN_POSITIONS=20
```

Esamas `.env`, `BRIDGE_SECRET`, Bybit ir Discord raktai nėra įtraukti ir neturi būti keičiami.

## Vietiniai testai

- Python compileall: OK.
- 24 unit/regression testai: OK.
- Patikrintas SHADOW manual režimo suderinamumas.
- Patikrintas SHADOW aplenkimas `ALL_EXECUTE` režime.
- Patikrintas automatinis entry laukimo įrašymas į SQLite.
- Patikrintas saugus nežinomo execution režimo atmetimas.

Tikras Bybit Demo orderis vietiniuose testuose nebuvo siunčiamas. Po įdiegimo reikia atlikti runtime health, systemd, SQLite ir natūralaus V2.5/V2.6 `EXECUTE` patikras.
