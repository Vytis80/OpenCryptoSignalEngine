import json
import logging
import time
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger(__name__)

PROMPT_VERSION = "ai-judge-v1"


@dataclass
class AIJudgement:
    inst_id: str
    checked_at: float
    provider: str
    model: str
    status: str
    verdict: str = "NO_DATA"
    confidence: int = 0
    setup_quality: str = "C"
    risk: str = "MEDIUM"
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error: str = ""
    prompt_version: str = PROMPT_VERSION

    @property
    def ok(self) -> bool:
        return self.status == "OK" and self.verdict in {"APPROVE", "REJECT"}


class AIJudge:
    """Observational Groq/GPT-OSS signal reviewer.

    Safety invariant: this class returns analysis only. It has no exchange or
    bridge access and cannot mutate TradeAnalysis, ActiveSignal, SL, TP or size.
    """

    def __init__(self, cfg, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.session = session
        self.url = cfg.ai_judge_base_url.rstrip("/") + "/chat/completions"

    def _input(self, a, shadow=None):
        shadow_payload = None
        if shadow is not None:
            shadow_payload = {
                "status": getattr(shadow, "status", "NO_DATA"),
                "would_block": bool(getattr(shadow, "would_block", False)),
                "reasons": list(getattr(shadow, "reasons", []) or [])[:3],
            }
        return {
            "symbol": a.inst_id,
            "side": a.side,
            "scanner_status": a.status,
            "scanner_score": round(float(a.score), 2),
            "scanner_quality": a.quality,
            "entry": {
                "price": a.price,
                "low": a.entry_low,
                "high": a.entry_high,
                "sl": a.sl,
                "tp1": a.tp1,
                "tp2": a.tp2,
                "tp3": a.tp3,
                "rr_tp2": round(float(a.rr_tp2), 3),
            },
            "structure": {
                "4h_regime": getattr(a, "regime_4h", "NEUTRAL"),
                "1h_bias": a.bias_1h,
                "15m_setup": a.setup_15m,
                "5m_trigger": a.trigger_5m,
                "1m_state": getattr(a, "micro_1m", "NO 1M DATA"),
                "1m_confirmations": int(getattr(a, "micro_confirmations", 0)),
            },
            "market_context": {
                "btc": a.btc_context,
                "eth": a.eth_context,
                "relative_strength_vs_btc_pct": round(float(a.relative_strength), 4),
            },
            "execution_quality": {
                "spread_pct": round(float(a.spread_pct), 5),
                "volume_ratio_5m": round(float(a.volume_ratio_5m), 4),
                "atr_5m_pct": round(float(getattr(a, "atr_5m_pct", 0.0)), 4),
                "stop_atr": round(float(getattr(a, "stop_atr", 0.0)), 4),
                "stop_pct": round(float(getattr(a, "stop_pct", 0.0)), 4),
                "obstacle_room_r": round(float(getattr(a, "obstacle_rr", 0.0)), 4),
                "fresh": bool(a.fresh),
                "too_late": bool(a.too_late),
            },
            "historical_edge": {
                "label": getattr(a, "edge_label", "COLLECTING"),
                "sample": int(getattr(a, "edge_sample", 0)),
                "estimated_net_r": round(float(getattr(a, "edge_net_r", 0.0)), 4),
                "tp2_rate": round(float(getattr(a, "edge_tp2_rate", 0.0)), 4),
            },
            "scanner_reasons": list(a.reasons or [])[:7],
            "scanner_warnings": list(a.blocks or [])[:5],
            "anti_sl_shadow": shadow_payload,
            "audit": {
                "version": (getattr(a, "audit_evidence", {}) or {}).get("version", ""),
                "core_version": getattr(a, "core_version", "2.6"),
            },
        }

    @staticmethod
    def _schema():
        return {
            "name": "trading_signal_judgement",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "setup_quality": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "summary": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                    "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                },
                "required": ["verdict", "confidence", "setup_quality", "risk", "summary", "strengths", "risks"],
            },
        }

    async def assess(self, a, shadow=None) -> AIJudgement:
        started = time.monotonic()
        checked_at = time.time()
        base = dict(
            inst_id=a.inst_id,
            checked_at=checked_at,
            provider="groq",
            model=self.cfg.ai_judge_model,
            status="ERROR",
        )
        if not self.cfg.groq_api_key:
            return AIJudgement(**base, error="GROQ_API_KEY missing")

        system = (
            "You are AI JUDGE, a conservative second-opinion reviewer for an already-confirmed "
            "crypto perpetual trading signal. Evaluate ONLY the supplied structured evidence. "
            "Do not invent prices, news, order-flow, indicators or market data. APPROVE means the "
            "setup is internally coherent enough to allow in a hypothetical filter; REJECT means "
            "there is a material conflict or poor execution quality. Confidence is confidence in "
            "your verdict, NOT probability of profit. Historical edge marked COLLECTING or with a "
            "small sample is weak evidence and must not dominate. The existing deterministic risk "
            "engine is authoritative: never propose changing entry, SL, TP, leverage, size, or "
            "execution. Keep summary and list items concise."
        )
        payload = {
            "model": self.cfg.ai_judge_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(self._input(a, shadow), ensure_ascii=False, separators=(",", ":"))},
            ],
            "reasoning_effort": self.cfg.ai_judge_reasoning_effort if self.cfg.ai_judge_reasoning_effort in {"low", "medium", "high"} else "low",
            "reasoning_format": "hidden",
            "response_format": {"type": "json_schema", "json_schema": self._schema()},
        }
        headers = {
            "Authorization": f"Bearer {self.cfg.groq_api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=max(1.0, min(15.0, float(self.cfg.ai_judge_timeout_sec))))
        try:
            async with self.session.post(self.url, headers=headers, json=payload, timeout=timeout) as response:
                raw = await response.text()
                latency = int((time.monotonic() - started) * 1000)
                if response.status >= 300:
                    return AIJudgement(**base, latency_ms=latency, error=f"HTTP {response.status}: {raw[:240]}")
                body = json.loads(raw)
                content = body["choices"][0]["message"]["content"]
                data = json.loads(content)
                verdict = str(data.get("verdict", "")).upper()
                quality = str(data.get("setup_quality", "C")).upper()
                risk = str(data.get("risk", "MEDIUM")).upper()
                confidence = int(data.get("confidence", 0))
                if verdict not in {"APPROVE", "REJECT"}:
                    raise ValueError(f"invalid verdict {verdict!r}")
                if quality not in {"A", "B", "C", "D"}:
                    raise ValueError(f"invalid setup_quality {quality!r}")
                if risk not in {"LOW", "MEDIUM", "HIGH"}:
                    raise ValueError(f"invalid risk {risk!r}")
                return AIJudgement(
                    **{**base, "status": "OK"},
                    verdict=verdict,
                    confidence=max(0, min(100, confidence)),
                    setup_quality=quality,
                    risk=risk,
                    summary=str(data.get("summary", ""))[:700],
                    strengths=[str(x)[:220] for x in (data.get("strengths") or [])[:4]],
                    risks=[str(x)[:220] for x in (data.get("risks") or [])[:4]],
                    latency_ms=latency,
                )
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            log.warning("AI JUDGE failed %s: %s", a.inst_id, exc)
            return AIJudgement(**base, latency_ms=latency, error=str(exc)[:240])
