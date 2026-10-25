"""OpenTelemetry tracing with GenAI semantic-convention attributes, exported to Langfuse over OTLP/HTTP."""
import base64
import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult

log = logging.getLogger("telemetry")

# FastAPI emits a span per request plus per-phase internals. The console polls read endpoints and Docker
# health-checks constantly; those GETs would bury the agent and LLM spans that matter. The route name is
# only known after routing, so requests are filtered on the method present when the span starts.
class DropNoise(Sampler):
    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None, trace_state=None) -> SamplingResult:
        if name.startswith("fastapi.") or (attributes or {}).get("http.request.method") == "GET":
            return SamplingResult(Decision.DROP)
        return SamplingResult(Decision.RECORD_AND_SAMPLE, attributes)

    def get_description(self) -> str:
        return "DropNoise"


def setup(service_name: str, langfuse_url: str, public_key: str, secret_key: str) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}), sampler=DropNoise())
    if public_key and secret_key:
        auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        exporter = OTLPSpanExporter(endpoint=f"{langfuse_url}/api/public/otel/v1/traces", headers={"Authorization": f"Basic {auth}"})
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        log.warning("Langfuse keys not set; spans are not exported")
    trace.set_tracer_provider(provider)


tracer = trace.get_tracer("custodian")
