import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# =====================================================================
# 1. Custom Telemetry Span Processor for Automated Threshold Alerts
# =====================================================================

class AutomatedAlertThresholdProcessor(SpanProcessor):
    """Intercepts completed tracing spans and triggers alerts if processing runs slow."""
    def __init__(self, latency_threshold_seconds: float = 1.5):
        self.latency_threshold = latency_threshold_seconds

    def on_start(self, span, parent_context=None) -> None:
        pass # No action required when a span initiates

    def on_end(self, span: ReadableSpan) -> None:
        """Evaluates execution duration as soon as a graph node finishes processing."""
        # Calculate precise elapsed duration in seconds
        duration_ns = span.end_time - span.start_time
        duration_seconds = duration_ns / 1e9
        span_name = span.name

        # THRESHOLD CRITERIA CHECK: Flag anomalies running over our safety ceiling
        if duration_seconds > self.latency_threshold:
            print(f"\n🚨 [AUTOMATED PERFORMANCE ALERT] Component '{span_name}' exceeded latency limits!")
            print(f"   -> Measured Turnaround Duration: {duration_seconds:.4f}s (Threshold Ceiling: {self.latency_threshold}s)")
            print(f"   -> System Trace ID Context: {format(span.context.trace_id, '032x')}")

            attributes = span.attributes
            if attributes:
                print(f"   -> Associated Context Metadata: {dict(attributes)}")

            # In live production deployments, link this hook directly to an external webhook:
            # dispatch_to_pagerduty(span_name, duration_seconds, format(span.context.trace_id, '032x'))

# =====================================================================
# 2. Global OpenTelemetry Infrastructure Registration
# =====================================================================

def initialize_global_tracing_telemetry(service_name: str = "customer-support-ai-engine"):
    """Configures the Tracer Provider, binds OTLP exporters, and arms threshold alerts."""
    # Define enterprise tracking tags to cleanly sort logs inside your Jaeger UI
    #
    # NOTE: this was originally written as `resource = Resource.attributes = {...}`,
    # a chained assignment that (a) overwrote `Resource.attributes` as a class
    # attribute on the *class itself* -- a global side effect that would leak
    # into every other Resource anywhere in the process -- and (b) bound
    # `resource` to a plain dict, not an actual `Resource` instance. Passing
    # that dict as `TracerProvider(resource=...)` either raises or silently
    # produces spans with no resource attributes attached, depending on SDK
    # version. `Resource.create(...)` is the actual constructor for this.
    resource = Resource.create({
        "service.name": service_name,
        "service.environment": os.getenv("APP_ENV", "production"),
        "deployed.version": "2026.1.0"
    })

    provider = TracerProvider(resource=resource)

    # 1. Attach our custom Alerting Processor (Set to trigger alert logs if a node passes 1.5 seconds)
    alert_processor = AutomatedAlertThresholdProcessor(latency_threshold_seconds=1.5)
    provider.add_span_processor(alert_processor)

    # 2. Configure the standard OTLP Exporter pointing to the local Jaeger collector service container
    # The default open-telemetry endpoint listens on gRPC network communication port 4317
    jaeger_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    try:
        otlp_exporter = OTLPSpanExporter(endpoint=jaeger_endpoint, insecure=True)
        # BatchSpanProcessor aggregates traces asynchronously so user network traffic isn't blocked
        batch_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(batch_processor)
    except Exception as otel_err:
        print(f"⚠️ [TELEMETRY REGISTRY WARN] Failed to bind OTLP gRPC endpoint exporter: {str(otel_err)}")

    # Register provider globally so LangChain/LangGraph internals can auto-detect the tracer engine
    trace.set_tracer_provider(provider)
    print(f"🛰️ Distributed OpenTelemetry infrastructure armed for service '{service_name}'.")

# Initialize telemetry hooks automatically if imported into runtime scripts
if __name__ != "__main__":
    initialize_global_tracing_telemetry()
