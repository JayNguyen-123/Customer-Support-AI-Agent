import os
import time
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, TypedDict, Annotated, Sequence, Literal, Any
from pydantic import BaseModel, Field

# FastAPI infrastructure
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response

# LangGraph & LangChain primitives
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
# NOTE: the original import here was `from langgraph_checkpoint_sqlite import
# SqliteSaver` -- a top-level module name that doesn't match how LangGraph's
# checkpoint backends are actually packaged (compare tests/test_agent.py's
# own `from langgraph.checkpoint.memory import MemorySaver`, which uses the
# real `langgraph.checkpoint.<backend>` namespace). It was also the *sync*
# saver; this app invokes the graph exclusively through async methods
# (`.ainvoke`, `.astream_events`, `.aupdate_state` -- see the WebSocket and
# takeover routes below), so it needs the async-native checkpointer.
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import ToolNode

# Security & Relational DB Persistence
import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from database_persistence import get_db, UserModel

# Observability, Metrics & Tracing
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Gauge, Histogram
from opentelemetry import trace

# Registers the OTLP/Jaeger exporter, the custom latency-alert span processor,
# and the global TracerProvider (see telemetry.py). Without this import,
# `trace.get_tracer(...)` below falls back to OpenTelemetry's default no-op
# provider: every `tracer.start_as_current_span(...)` call in this file would
# still "work" (no errors) but silently produce no spans, no Jaeger export,
# and no latency alerts -- the entire tracing stack described in the README
# would be running dark.
import telemetry


# =====================================================================
# Telemetry, Metrics & Cryptography Config
# =====================================================================
# Prometheus Gauges and Histograms for real-time monitoring.
# ACTIVE_WS_SESSIONS tracks current WebSocket connections.
# GRAPH_LATENCY measures the performance of LangGraph turns.
# RATE_LIMIT_DROPS counts requests blocked by rate limiting.
ACTIVE_WS_SESSIONS = Gauge("support_agent_active_websockets", "Active WebSocket lines.")
GRAPH_LATENCY = Histogram("support_agent_graph_latency_seconds", "Graph latency.", buckets=(0.5, 1.0, 2.0, 5.0, 10.0))
RATE_LIMIT_DROPS = Counter("support_agent_rate_limit_drops_total", "Blocked requests.")

# JWT secret key for token signing, retrieved from environment variables for security.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "SUPER_SECRET_PRODUCTION_SIGNING_PASSPHRASE_HEX_101")
ALGORITHM = "HS256" # Cryptographic algorithm for JWTs.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto") # Context for password hashing.
security_jwt_guard = HTTPBearer() # FastAPI dependency for extracting JWTs from headers.
tracer = trace.get_tracer("langgraph.production.orchestrator") # OpenTelemetry tracer for distributed tracing.

# =====================================================================
# Token Bucket Rate-Limiter Engine
# =====================================================================
class TokenBucketLimiter:
    """Implements a token bucket algorithm to rate-limit incoming requests."""
    def __init__(self, capacity: int = 5, fill_rate_per_sec: float = 0.5, stale_after_sec: float = 3600):
        self.capacity = capacity  # Maximum tokens the bucket can hold.
        self.fill_rate = fill_rate_per_sec  # Rate at which tokens are added per second.
        self.buckets: Dict[str, Dict[str, float]] = {} # Stores bucket state per client IP.
        # A bucket that's had time to refill all the way back to capacity has
        # nothing left to track -- it behaves identically to a brand-new one.
        # Without this, `buckets` grows by one entry per distinct client IP
        # ever seen, for the lifetime of the process, and never shrinks: a
        # slow, unbounded memory leak under any real amount of traffic.
        self.stale_after_sec = stale_after_sec
        self._last_swept = time.time()

    def _sweep_stale_buckets_locked(self, current_time: float) -> None:
        # Cheap, opportunistic sweep -- runs at most once a minute, off the
        # request path's hot loop, no extra thread/timer needed.
        if current_time - self._last_swept < 60:
            return
        self._last_swept = current_time
        stale_ips = [
            ip for ip, bucket in self.buckets.items()
            if current_time - bucket["last_update"] > self.stale_after_sec
        ]
        for ip in stale_ips:
            del self.buckets[ip]

    def is_allowed(self, client_ip: str) -> bool:
        """Checks if a request from a given IP is allowed based on the token bucket.
        If allowed, a token is consumed. Returns True if allowed, False otherwise."""
        current_time = time.time()
        self._sweep_stale_buckets_locked(current_time)

        # Initialize bucket for new client IPs.
        if client_ip not in self.buckets:
            self.buckets[client_ip] = {"tokens": float(self.capacity), "last_update": current_time}
            return True

        bucket = self.buckets[client_ip]
        # Add tokens based on time elapsed since last update.
        bucket["tokens"] = min(float(self.capacity), bucket["tokens"] + ((current_time - bucket["last_update"]) * self.fill_rate))
        bucket["last_update"] = current_time

        # If tokens are available, consume one and allow the request.
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        # Otherwise, block the request.
        return False

# NOTE: this dict lives in a single process's memory, so running multiple
# Uvicorn/Gunicorn workers (or replicas) gives each one its own independent
# rate-limit budget per client IP rather than a shared one -- fine for a
# single-worker deployment, but worth knowing before scaling out. A shared
# store (e.g. Redis) is the fix if/when that matters.
rate_limiter = TokenBucketLimiter(capacity=3, fill_rate_per_sec=0.2) # Instantiate the rate limiter.

# =====================================================================
# WebSocket Connection Lane Registry
# =====================================================================
class ConnectionManager:
    """Manages active WebSocket connections to broadcast messages to clients."""
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {} # Maps thread IDs to active WebSocket objects.

    async def connect_user(self, thread_id: str, websocket: WebSocket):
        """Accepts a WebSocket connection and registers it for a given thread_id."""
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        ACTIVE_WS_SESSIONS.inc() # Increment active sessions metric.

    def disconnect_user(self, thread_id: str):
        """Removes a disconnected WebSocket from the active connections."""
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
            ACTIVE_WS_SESSIONS.dec() # Decrement active sessions metric.

    async def push_message_to_user(self, thread_id: str, payload: dict) -> bool:
        """Sends a JSON message to a specific user's WebSocket connection."""
        if thread_id in self.active_connections:
            await self.active_connections[thread_id].send_json(payload)
            return True
        return False

manager = ConnectionManager() # Instantiate the connection manager.

# =====================================================================
# Core Shared Graph State & Tool Mapping
# =====================================================================
class SupportSystemState(TypedDict):
    """Represents the shared state of the LangGraph workflow."""
    messages: Annotated[Sequence[BaseMessage], add_messages] # List of chat messages.
    active_agent: str # Currently active agent (e.g., 'order_agent', 'troubleshooting_agent').
    order_id: str # Extracted order ID.
    device_model: str # Extracted device model.
    action_requires_approval: bool # Flag for actions needing human approval.
    approval_granted: bool # Flag indicating if approval was granted.
    validation_passed: bool # Flag indicating RAG validation status.
    validation_feedback: str # Feedback from RAG validation.
    revision_count: int # Count of agent revisions due to RAG feedback.

@tool
def lookup_order_tracking(order_id: str) -> str:
    """Retrieve live shipping tracking and delivery details for an order ID."""
    # Placeholder for actual order tracking logic.
    return f"Order {order_id} has left the facility and will arrive on Friday."

@tool
def initiate_refund_pipeline(order_id: str) -> str:
    """Trigger financial refund sequence. High impact operation."""
    # Placeholder for actual refund initiation logic.
    return f"SUCCESS: Refund transaction executed for Order {order_id}."

order_tools = [lookup_order_tracking, initiate_refund_pipeline]
order_tool_node = ToolNode(order_tools) # LangGraph node for executing order-related tools.

class RouterSchema(BaseModel):
    """Schema for the supervisor agent's routing decision."""
    next_agent: Literal["order_agent", "troubleshooting_agent", "respond_to_user"]
    extracted_order_id: str = ""
    extracted_device: str = ""

class ValidationSchema(BaseModel):
    """Schema for the RAG validator's output."""
    is_compliant: bool # Whether the agent's answer complies with SOPs.
    feedback: str # Feedback if non-compliant.

# =====================================================================
# Graph Agent Nodes Setup
# =====================================================================
async def supervisor_router_node(state: SupportSystemState):
    """Routes the conversation to the appropriate agent or to respond directly to the user."""
    with tracer.start_as_current_span("node.supervisor_router"):
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0) # LLM for routing decisions.
        # Use structured output to get a clean routing decision.
        # NOTE: this must be `.ainvoke()`, not `.invoke()` -- the graph runs
        # under `astream_events`/`ainvoke` (see the WebSocket handler below),
        # and a blocking sync call here would stall the whole event loop for
        # every connected client during each LLM round trip. It also matches
        # what tests/test_agent.py actually mocks (`ChatOpenAI.ainvoke`); the
        # original sync `.invoke()` call meant those mocks never engaged and
        # the "mocked" tests would have hit the real OpenAI API.
        decision = await model.with_structured_output(RouterSchema).ainvoke(state["messages"])
        updates = {"active_agent": decision.next_agent}
        if decision.extracted_order_id: updates["order_id"] = decision.extracted_order_id
        if decision.extracted_device: updates["device_model"] = decision.extracted_device
        return updates

async def order_management_agent(state: SupportSystemState):
    """Handles order-related queries, including potential refund requests which require approval."""
    with tracer.start_as_current_span("node.order_management"):
        order_id = state.get("order_id", "UNKNOWN")
        messages = state["messages"]
        last_message = messages[-1] if messages else None

        # Only treat this as a *fresh* refund request if the customer just
        # said so -- not if the last entry is a ToolMessage (e.g. the
        # refund tool's own "Refund transaction executed" success message,
        # which also contains the word "refund" and would otherwise
        # re-trigger the freeze *after* the refund already went through) or
        # an admin's injected AIMessage during a takeover.
        is_fresh_user_request = isinstance(last_message, HumanMessage)
        refund_requested = is_fresh_user_request and "refund" in str(last_message.content).lower()

        # If a refund is requested and not yet approved, flag for human intervention.
        if refund_requested and not state.get("approval_granted", False):
            return {
                "action_requires_approval": True,
                "messages": [AIMessage(content=f"Refund request caught for order {order_id}. Freezing thread for supervisor sign-off.")]
            }

        # Bind order tools to the LLM and generate a response.
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools(order_tools)
        prompt = f"You are the Order Specialist. Active Order ID context: {order_id}."
        response = await model.ainvoke([HumanMessage(content=prompt)] + list(messages))
        return {
            "messages": [response],
            "action_requires_approval": False,
            # Consume the one-time approval grant here. Without this, a single
            # admin sign-off (via /api/v1/support/takeover) stayed True in the
            # persisted checkpoint for the rest of the thread's lifetime,
            # silently letting the agent auto-approve every *future* refund
            # request on this thread with no further human review.
            "approval_granted": False,
        }

async def troubleshooting_agent(state: SupportSystemState):
    """Assists with technical troubleshooting based on device model and previous feedback."""
    with tracer.start_as_current_span("node.troubleshooting_agent"):
        device = state.get("device_model", "Standard Product")
        feedback = state.get("validation_feedback", "")
        base_prompt = f"You are the Technical Support Expert diagnosing a {device}."
        # Incorporate validation feedback for self-correction.
        if feedback:
            base_prompt += f"\n\n⚠️ REVISION CRITERIA: Fix your answer based on this SOP rule: '{feedback}'"
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
        response = await model.ainvoke([SystemMessage(content=base_prompt)] + list(state["messages"]))
        return {"messages": [response]}

async def live_rag_validation_node(state: SupportSystemState):
    """Validates agent responses against a knowledge base using RAG (Retrieval Augmented Generation)."""
    with tracer.start_as_current_span("node.rag_validation") as span:
        device = state.get("device_model", "Unknown")
        agent_answer = state["messages"][-1].content

        # Retrieve relevant documents from the Chroma vector store.
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        vector_store = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
        # Only match chunks that haven't passed their TTL. ingest.py writes an
        # `expires_at` epoch timestamp onto every chunk specifically so stale
        # manuals get excluded here -- but the original query never actually
        # applied a metadata filter, so expired documents (and the README's
        # advertised "Logical Eviction Handling") had no effect at retrieval
        # time. Chroma's filter operators require an explicit "$gte" clause.
        current_epoch = int(time.time())
        retrieved_chunks = vector_store.similarity_search(
            query=f"Troubleshooting guidelines for {device}",
            k=2,
            filter={"expires_at": {"$gte": current_epoch}},
        )
        kb_context = "\n---\n".join([doc.page_content for doc in retrieved_chunks]) if retrieved_chunks else "No manuals found."

        # Use an LLM to evaluate compliance based on retrieved context.
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        result = await model.with_structured_output(ValidationSchema).ainvoke(
            f"--- SOP CONTEXT ---\n{kb_context}\n\n--- ANSWER ---\n{agent_answer}\nEvaluate compliance."
        )
        current_revisions = state.get("revision_count", 0)
        # Update state with validation results and revision count.
        return {
            "validation_passed": result.is_compliant,
            "validation_feedback": "" if result.is_compliant else result.feedback,
            "revision_count": current_revisions if result.is_compliant else current_revisions + 1
        }

def human_checkpoint_gate_node(state: SupportSystemState):
    """A placeholder node to signal a human checkpoint has been reached."""
    # This node is primarily for routing and can be expanded for specific human interaction logic.
    # Resets both the "awaiting approval" flag AND the one-time approval grant
    # itself, in case a future resume path lifts the interrupt by continuing
    # through this node directly rather than via the admin takeover endpoint
    # (which already consumes it in order_management_agent -- see above).
    return {"action_requires_approval": False, "approval_granted": False}

# =====================================================================
# Graph Control Routing Wiring
# =====================================================================
def route_from_supervisor(state: SupportSystemState):
    """Determines the next agent based on the supervisor's decision."""
    return state.get("active_agent", "respond_to_user")

def route_order_actions(state: SupportSystemState):
    """Routes order agent's actions based on approval status or tool calls."""
    if state.get("action_requires_approval", False): return "human_gate" # If approval needed, go to human gate.
    if state["messages"][-1].tool_calls: return "order_tools" # If tool calls detected, execute tools.
    return "back_to_supervisor" # Otherwise, go back to supervisor.

def route_troubleshooting_eval(state: SupportSystemState):
    """Routes troubleshooting agent based on RAG validation results and revision count."""
    # If revisions exceed limit or validation passed, go back to supervisor.
    if state.get("revision_count", 0) >= 2 or state.get("validation_passed", False): return "back_to_supervisor"
    return "troubleshooting_agent" # Otherwise, continue troubleshooting.

# Initialize the StateGraph with the defined state.
workflow = StateGraph(SupportSystemState)

# Add nodes to the workflow, each corresponding to an agent or processing step.
workflow.add_node("supervisor", supervisor_router_node)
workflow.add_node("order_agent", order_management_agent)
workflow.add_node("troubleshooting_agent", troubleshooting_agent)
workflow.add_node("order_tools", order_tool_node)
workflow.add_node("rag_validator", live_rag_validation_node)
workflow.add_node("human_gate", human_checkpoint_gate_node)

# Define the entry point of the graph.
workflow.add_edge(START, "supervisor")

# Define conditional transitions from the supervisor based on its routing decision.
workflow.add_conditional_edges("supervisor", route_from_supervisor, {"order_agent": "order_agent", "troubleshooting_agent": "troubleshooting_agent", "respond_to_user": END})

# Define conditional transitions from the order agent.
workflow.add_conditional_edges("order_agent", route_order_actions, {"human_gate": "human_gate", "order_tools": "order_tools", "back_to_supervisor": "supervisor"})

# Define a direct edge from order_tools back to the order_agent to process tool results.
workflow.add_edge("order_tools", "order_agent")

# Define a direct edge from the troubleshooting agent to the RAG validator.
workflow.add_edge("troubleshooting_agent", "rag_validator")

# Define conditional transitions from the RAG validator.
workflow.add_conditional_edges("rag_validator", route_troubleshooting_eval, {"troubleshooting_agent": "troubleshooting_agent", "back_to_supervisor": "supervisor"})

# Define the exit point for the human gate (e.g., after approval, the conversation might end or return to a previous state).
workflow.add_edge("human_gate", END)

# The compiled graph is assigned during the FastAPI lifespan below, once the
# AsyncSqliteSaver's connection is actually open (see `lifespan()`). It's
# declared here so module-level references (and tests, which compile their
# own isolated instance with MemorySaver) can still import `workflow`.
agent_graph: Any = None

# =====================================================================
# FastAPI Secured Endpoints & WebSockets Layer
# =====================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opens the SQLite checkpoint connection and compiles the graph for the
    app's lifetime, then closes it cleanly on shutdown.

    `AsyncSqliteSaver.from_conn_string(...)` is an async context manager, not
    a plain constructor -- the original code called it directly at bare
    module level (`graph_conn = SqliteSaver.from_conn_string(...)`), outside
    of any event loop and without ever entering/exiting the context, which
    doesn't work for the async saver. FastAPI's lifespan is the standard
    place to own a resource like this for the whole process.
    """
    global agent_graph
    async with AsyncSqliteSaver.from_conn_string("production_support.db") as saver:
        agent_graph = workflow.compile(checkpointer=saver, interrupt_before=["human_gate"])
        yield

app = FastAPI(title="Enterprise Support API Engine", lifespan=lifespan) # Initialize FastAPI application.

class TakeoverRequestSchema(BaseModel):
    """Schema for the administrative takeover request payload."""
    thread_id: str # The conversation thread to take over.
    override_message: str # The message to inject into the conversation.


class RegisterRequestSchema(BaseModel):
    """Schema for new employee/admin account registration."""
    username: str
    email: str
    password: str
    role: str = "agent"  # "agent" or "admin" -- see UserModel.role.


class LoginRequestSchema(BaseModel):
    """Schema for the username/password login request."""
    username: str
    password: str


class TokenResponseSchema(BaseModel):
    """Schema for a successful login's JWT bearer token response."""
    access_token: str
    token_type: str = "bearer"


def generate_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Signs a JWT access token carrying the given claims (e.g. {"sub": username, "role": role}).

    This was imported by tests/test_security.py and referenced by the README's
    takeover walkthrough, but never actually defined anywhere in the original
    project -- along with the /auth/register and /auth/login routes below, it's
    the missing piece that issues the tokens verify_admin_token_role checks.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=30))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register_employee_account(payload: RegisterRequestSchema, db: Session = Depends(get_db)):
    """Registers a new employee/admin account with a bcrypt-hashed password."""
    existing = (
        db.query(UserModel)
        .filter((UserModel.username == payload.username) | (UserModel.email == payload.email))
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already registered")

    user = UserModel(
        username=payload.username,
        email=payload.email,
        hashed_password=pwd_context.hash(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"account_id": user.id, "username": user.username, "role": user.role}


@app.post("/api/v1/auth/login", response_model=TokenResponseSchema)
def login_and_issue_token(payload: LoginRequestSchema, db: Session = Depends(get_db)):
    """Verifies username/password and issues a signed JWT bearer token."""
    user = db.query(UserModel).filter(UserModel.username == payload.username).first()
    if user is None or not pwd_context.verify(payload.password, user.hashed_password):
        # Deliberately identical error for "no such user" and "wrong password"
        # so the response doesn't leak which usernames exist.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    token = generate_access_token(data={"sub": user.username, "role": user.role}, expires_delta=timedelta(minutes=60))
    return TokenResponseSchema(access_token=token)


def verify_admin_token_role(credentials: HTTPAuthorizationCredentials = Depends(security_jwt_guard)) -> dict:
    """Dependency to verify JWT token and ensure the user has 'admin' role."""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Administrative privileges required")
        return {"username": payload.get("sub")} # Return username if authenticated and authorized.
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token properties.") # Handle invalid tokens.

async def async_database_sync_logger(thread_id: str, prompt: str):
    """Asynchronously logs interaction data to a simulated analytics sink."""
    await asyncio.sleep(0.1) # Simulate I/O delay for logging.
    print(f"📊 [ANALYTICS SINK LOGGED] Thread: {thread_id} | Msg: {prompt[:20]}")

@app.get("/metrics")
def metrics_scraper_endpoint():
    """Exposes Prometheus metrics endpoint for scraping by monitoring systems."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/api/v1/support/takeover")
async def secure_admin_takeover(payload: TakeoverRequestSchema, admin: dict = Depends(verify_admin_token_role)):
    """Admin-only endpoint to inject messages or grant approvals into ongoing conversations."""
    config = {"configurable": {"thread_id": payload.thread_id}}
    # Update the LangGraph state with the admin's message and approval.
    await agent_graph.aupdate_state(config, {"messages": [AIMessage(content=payload.override_message, name=admin["username"])], "approval_granted": True}, as_node="supervisor")
    # Send confirmation message to the user via WebSocket.
    await manager.push_message_to_user(payload.thread_id, {"type": "token", "content": f"🛡️ [Supervisor {admin['username']} Intervened]: {payload.override_message}"})
    await manager.push_message_to_user(payload.thread_id, {"type": "status", "content": "complete"})
    return {"status": "SUCCESS", "operator": admin["username"]}

@app.websocket("/ws/{thread_id}")
async def customer_websocket_entry(websocket: WebSocket, thread_id: str, background_tasks: BackgroundTasks):
    """Main WebSocket endpoint for customer support interactions, handling real-time chat."""
    await manager.connect_user(thread_id, websocket)
    client_ip = websocket.client.host if websocket.client else "unknown_ip"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        while True:
            user_input = await websocket.receive_text()
            # Apply rate limiting to incoming messages.
            if not rate_limiter.is_allowed(client_ip):
                RATE_LIMIT_DROPS.inc()
                await websocket.send_json({"type": "error", "code": "RATE_LIMIT", "content": "Slow down! Wait a moment."})
                continue

            input_state = {"messages": [HumanMessage(content=user_input)]}
            start_latency_timer = time.perf_counter()

            # Stream events from the LangGraph agent.
            async for event in agent_graph.astream_events(input_state, config, version="v2"):
                if event.get("event") == "on_chat_model_stream":
                    token = event["data"]["chunk"].content
                    if token:
                        await websocket.send_json({"type": "token", "content": token})

            GRAPH_LATENCY.observe(time.perf_counter() - start_latency_timer) # Record graph latency.
            await websocket.send_json({"type": "status", "content": "complete"})
            # Log the interaction in the background.
            background_tasks.add_task(async_database_sync_logger, thread_id=thread_id, prompt=user_input)

    except WebSocketDisconnect:
        manager.disconnect_user(thread_id) # Handle client disconnection.
    except Exception:
        manager.disconnect_user(thread_id) # Ensure disconnection on other errors.
        await websocket.close()