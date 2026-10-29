"""Composition root. Paper mode does not read API keys and does not bind a port.

Live mode fails before an exchange client is built. The monitor port stays closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

from chanedge.app.bind import feature_params, jev_params, risk_params, rule_params
from chanedge.app.pipeline import PipelineServices, run_pipeline
from chanedge.chanlun.engine import ChanEngine
from chanedge.chanlun.version import ENGINE_VERSION
from chanedge.config.hash import config_hash
from chanedge.domain.bars import Instrument
from chanedge.domain.enums import RuntimeMode
from chanedge.domain.risk import SafetyState
from chanedge.execution.paper import PaperBroker
from chanedge.features.builder import FeatureBuilder
from chanedge.features.version import FEATURE_VERSION
from chanedge.jev.compose import TypeSafeJev
from chanedge.jev.model import JevModel
from chanedge.typesafe.cache import JsonlReader, LookupCaller
from chanedge.typesafe.client import JsonlClient
from chanedge.journal.book import JournalLedger
from chanedge.marketdata.ccxt_adapter import instrument_from_market
from chanedge.marketdata.parquet_store import ParquetBarStore
from chanedge.marketdata.version import MARKETDATA_VERSION
from chanedge.risk.size import RiskManager
from chanedge.rules.gate import RuleGate

_SECRET_KEYS = ("CHANEDGE_API_KEY", "CHANEDGE_API_SECRET", "TYPESAFE_API_KEY")


def drop_secrets(logger, method_name, event_dict):
    """structlog processor. The two paper key names never reach the renderer."""
    del logger, method_name
    for key in _SECRET_KEYS:
        event_dict.pop(key, None)
    return event_dict


def configure_logging():
    structlog.configure(
        processors=[
            drop_secrets,
            structlog.processors.JSONRenderer(),
        ]
    )
    return structlog.get_logger("chanedge")


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def build_exchange():
    """Public market data only. No API key and no secret are passed in."""
    import ccxt

    return ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "swap"}})


@dataclass
class PaperApp:
    settings: object
    root: Path
    broker: PaperBroker
    ledger: JournalLedger
    store: ParquetBarStore
    exchange: object
    services: PipelineServices
    clock: object
    config_hash: str
    engine_version: str
    feature_version: str
    marketdata_version: str
    safety: SafetyState
    instruments: dict[str, Instrument]
    log: object
    pipeline: object = run_pipeline
    previous: dict = field(default_factory=dict)
    listed: object | None = None
    systemone_reader: object | None = None
    systemone_client: object | None = None


def compose(
    settings,
    *,
    root: Path,
    exchange: object,
    clock: object,
    environ=None,
    network: bool = False,
    api_key: str | None = None,
    systemone_attempts: int = 1,
) -> PaperApp:
    """Wire paper objects. environ is accepted and not read. The API key arrives as api_key."""
    del environ
    if settings.runtime.mode == "live":
        raise RuntimeError("live mode is not implemented")
    if settings.runtime.mode != "paper":
        raise RuntimeError("runtime.mode must be paper")
    _require_version_pair(settings)
    digest = config_hash(settings)
    ledger = JournalLedger(Path(root) / settings.journal.sqlite_path)
    broker = PaperBroker(
        ledger,
        initial_equity=settings.risk.initial_equity_quote,
        kill_switch=settings.safety.kill_switch,
        order_type=settings.execution.order_type,
    )
    params = jev_params(settings)
    reader = None
    client = None
    if settings.systemone.enabled:
        cache_path = Path(root) / settings.systemone.cache_path
        if network:
            client = JsonlClient(
                path=cache_path,
                model_pin=settings.systemone.model_pin,
                question_set=settings.systemone.question_set,
                timeout_seconds=settings.systemone.timeout_seconds,
                base_url=settings.systemone.base_url,
                api_key="" if api_key is None else api_key,
                attempts=systemone_attempts,
            )
            port = client
        else:
            reader = JsonlReader(cache_path, settings.systemone.model_pin)
            port = LookupCaller(
                reader,
                question_set=settings.systemone.question_set,
                model_pin=settings.systemone.model_pin,
            )
        jev = TypeSafeJev(params, port, model_pin=settings.systemone.model_pin)
        log_jev = JevModel(params.model_copy(update={"version": "weighted-v1"}))
        score_after = True
    else:
        jev = JevModel(params)
        log_jev = None
        score_after = False
    services = PipelineServices(
        engine=ChanEngine(
            config_hash=digest,
            min_bi_bars=settings.chanlun.min_bi_bars,
            segment_enabled=settings.chanlun.segment_enabled,
        ),
        features=FeatureBuilder(feature_params(settings)),
        jev=jev,
        rules=RuleGate(rule_params(settings)),
        risk=RiskManager(risk_params(settings)),
        broker=broker,
        rule_params=rule_params(settings),
        log_jev=log_jev,
        score_after_preflight=score_after,
    )
    return PaperApp(
        settings=settings,
        root=Path(root),
        broker=broker,
        ledger=ledger,
        store=ParquetBarStore(Path(root)),
        exchange=exchange,
        services=services,
        clock=clock,
        config_hash=digest,
        engine_version=ENGINE_VERSION,
        feature_version=FEATURE_VERSION,
        marketdata_version=MARKETDATA_VERSION,
        safety=SafetyState(kill_switch=settings.safety.kill_switch, mode=RuntimeMode.PAPER),
        instruments=instruments_from_exchange(exchange, settings.runtime.venue),
        log=configure_logging(),
        systemone_reader=reader,
        systemone_client=client,
    )


def _require_version_pair(settings) -> None:
    enabled = bool(settings.systemone.enabled)
    version = settings.jev.version
    if enabled and version != "typesafe-v1":
        raise RuntimeError("systemone.enabled requires jev.version typesafe-v1")
    if not enabled and version != "weighted-v1":
        raise RuntimeError("systemone.enabled false requires jev.version weighted-v1")


def instruments_from_exchange(exchange: object, venue: str) -> dict[str, Instrument]:
    load = getattr(exchange, "load_markets", None)
    if load is None:
        return {}
    markets = load()
    found: dict[str, Instrument] = {}
    for market in markets.values():
        if not isinstance(market, dict):
            continue
        try:
            instrument = instrument_from_market(market, venue=venue)
        except (TypeError, ValueError):
            continue
        found[instrument.symbol] = instrument
    return found
