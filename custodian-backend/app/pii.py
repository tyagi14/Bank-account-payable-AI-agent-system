"""Presidio redaction for anything persisted durably (audit log, run events). Best-effort: a failing
scan never blocks a pipeline step, but the entity types it found are always logged."""
import logging

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

log = logging.getLogger("pii")

ENTITIES = ["CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER", "EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "US_SSN", "IP_ADDRESS", "URL"]
_nlp = NlpEngineProvider(nlp_configuration={"nlp_engine_name": "spacy", "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]}).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp, supported_languages=["en"])
_anonymizer = AnonymizerEngine()


def redact(text: str | None) -> tuple[str | None, list[str]]:
    if not text:
        return text, []
    try:
        findings = _analyzer.analyze(text=text, language="en", entities=ENTITIES)
        found = sorted({f.entity_type for f in findings})
        if found:
            log.info("redacted PII entity types: %s", found)
        return _anonymizer.anonymize(text=text, analyzer_results=findings).text, found
    except Exception:
        log.exception("PII redaction failed; storing a placeholder instead of the raw text")
        return "<redaction-failed>", ["REDACTION_ERROR"]
