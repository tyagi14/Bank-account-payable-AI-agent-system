"""Extraction agent: (sandboxed OCR) -> guardrail on the untrusted content -> typed field extraction."""
import httpx

from app import config, governance, llm, pii
from app.agents.common import RAW_IMAGES, RAW_TEXT, RunState, check, emit, finish, invoice, store
from app.prompts import PROMPTS
from app.schemas import GuardrailVerdict, InvoiceFields

AGENT = "extraction"
SANDBOX_TOOL = {"type": "Tool", "id": "sandbox-ocr"}


async def _sandbox_ocr(image: bytes) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(f"{config.SANDBOX_RUNNER_URL}/ocr", content=image, headers={"Content-Type": "application/octet-stream"})
    resp.raise_for_status()
    return resp.json()


async def extraction_node(state: RunState) -> dict:
    thread_id = state["thread_id"]
    await governance.heartbeat(thread_id, AGENT)
    await store().update(thread_id, "working", "extracting")
    if not await check(state, AGENT, "ExtractInvoice", invoice(state)):
        return await finish(state, AGENT, "rejected", "blocked_policy", "extraction not authorized")

    image = RAW_IMAGES.pop(thread_id, None)
    if image is not None:
        if not await check(state, AGENT, "RunSandboxOCR", SANDBOX_TOOL):
            return await finish(state, AGENT, "rejected", "blocked_policy", "sandboxed OCR not authorized")
        ocr = await _sandbox_ocr(image)
        await emit(state, AGENT, "sandbox", {k: ocr[k] for k in ("container", "ocr_ms", "total_ms", "landlock")})
        text = ocr["text"]
    else:
        text = RAW_TEXT.pop(thread_id, None)
    if not text or not text.strip():
        return await finish(state, AGENT, "failed", "failed", "no document text (raw content is not kept across restarts)")

    await governance.heartbeat(thread_id, AGENT)
    verdict, usage = await llm.structured(base_url=config.LITELLM_URL, key=config.LITELLM_KEYS[AGENT], agent=AGENT, route="custodian-guardrail",
                                          response_model=GuardrailVerdict, system=PROMPTS["guardrail"]["text"], user=text)
    evidence, _ = pii.redact(verdict.evidence)
    await emit(state, AGENT, "guardrail", {"violation": verdict.violation, "categories": verdict.categories, "evidence": evidence, "llm": usage})
    if verdict.violation:
        await governance.audit("guardrail_block", AGENT, {"categories": verdict.categories, "evidence": evidence}, thread_id)
        return await finish(state, AGENT, "rejected", "blocked_guardrail", f"guardrail: {', '.join(verdict.categories)}")

    await governance.heartbeat(thread_id, AGENT)
    fields, usage = await llm.structured(base_url=config.LITELLM_URL, key=config.LITELLM_KEYS[AGENT], agent=AGENT, route="custodian-routine",
                                         response_model=InvoiceFields, system=PROMPTS["extraction"]["text"], user=text)
    redacted, entity_types = pii.redact(text)
    record = {"fields": fields.model_dump(), "prompt": PROMPTS["extraction"]["source"], "pii_entity_types": entity_types,
              "ocr_text_redacted": redacted, "llm": usage}
    await governance.audit("extraction", AGENT, record, thread_id)
    await emit(state, AGENT, "extracted", record)
    await store().update(thread_id, "working", "extracted", {"vendor": fields.vendor_name, "total": fields.total_amount})
    return {"fields": fields.model_dump(), "stage": "extracted"}
