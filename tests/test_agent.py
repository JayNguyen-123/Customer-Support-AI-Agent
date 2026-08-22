import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Import your unified graph primitives directly from your main application script
from main import workflow, SupportSystemState

@pytest.fixture
def mock_compiled_graph():
    """Compiles an isolated test instance of the graph with memory checkpoint tracking."""
    from langgraph.checkpoint.memory import MemorySaver
    # MemorySaver runs entirely in RAM, isolating test states from disk DB side-effects
    return workflow.compile(checkpointer=MemorySaver())

@pytest.mark.asyncio
async def test_supervisor_routes_to_order_agent(mock_compiled_graph):
    """Verifies that the supervisor node successfully intercepts order questions and routes traffic."""
    test_config = {"configurable": {"thread_id": "test_thread_001"}}
    initial_state = {
        "messages": [HumanMessage(content="Where is my delivery? Order reference ID is 123-ABC")]
    }

    # Intercept ChatOpenAI invocation to return a mock routing decision matrix
    with patch("langchain_openai.ChatOpenAI.ainvoke", new_callable=AsyncMock) as mock_llm:
        # Simulate structured output schema injection
        from main import RouterSchema
        mock_router_output = RouterSchema(
            next_agent="order_agent",
            extracted_order_id="123-ABC",
            extracted_device=""
        )

        # When using .with_structured_output(), the mock needs to return our Pydantic model
        with patch("langchain_core.language_models.chat_models.BaseChatModel.with_structured_output") as mock_structured:
            mock_structured.return_value.ainvoke = AsyncMock(return_value=mock_router_output)

            # Run graph execution turn
            final_state = await mock_compiled_graph.ainvoke(initial_state, config=test_config)

            # Assertions: Confirm state maps perfectly
            assert final_state["active_agent"] == "order_agent"
            assert final_state["order_id"] == "123-ABC"

@pytest.mark.asyncio
async def test_order_agent_triggers_hitl_breakpoint_on_refund(mock_compiled_graph):
    """Ensures sensitive actions like refunds pause execution before reaching the tool layer."""
    test_config = {"configurable": {"thread_id": "test_thread_002"}}
    initial_state = {
        "messages": [HumanMessage(content="Cancel my purchase and give me a full refund immediately.")],
        "order_id": "123-ABC",
        "approval_granted": False
    }

    # Execute graph logic stream
    final_state = await mock_compiled_graph.ainvoke(initial_state, config=test_config)

    # Assert that the human gate indicator is flagged to freeze the runtime stream
    assert final_state.get("action_requires_approval") is True
    assert "supervisor authorization" in final_state["messages"][-1].content

@pytest.mark.asyncio
async def test_rag_validator_loop_self_corrects_bad_advice(mock_compiled_graph):
    """Verifies that the RAG layer successfully forces self-correction on SOP violations."""
    test_config = {"configurable": {"thread_id": "test_thread_003"}}

    # Set up initial state with an invalid agent response (recommending a hard reset)
    malicious_setup = {
        "messages": [
            HumanMessage(content="My router is flashing red."),
            AIMessage(content="You should find a paperclip and execute a hard physical factory reset.")
        ],
        "device_model": "Netgear Wi-Fi Router",
        "revision_count": 0,
        "validation_passed": False
    }

    from main import ValidationSchema
    mock_bad_eval = ValidationSchema(
        is_compliant=False,
        feedback="SOP-402 violated: Wiping ISP configuration via pinhole is strictly prohibited."
    )

    with patch("langchain_openai.ChatOpenAI.with_structured_output") as mock_structured:
        # Force the evaluator to reject the first answer
        mock_structured.return_value.ainvoke = AsyncMock(return_value=mock_bad_eval)

        # Intercept the agent's second attempt to make it return correct advice
        with patch("langchain_openai.ChatOpenAI.ainvoke", new_callable=AsyncMock) as mock_agent_call:
            mock_agent_call.return_value = AIMessage(content="Please power cycle the router for 30 seconds.")

            # Run the streaming workflow loop execution
            final_state = await mock_compiled_graph.ainvoke(malicious_setup, config=test_config)

            # Verify counter increments and the agent loop paths kicked back into effect
            assert final_state["revision_count"] == 1
            assert final_state["validation_passed"] is False
            assert "SOP-402 violated" in final_state["validation_feedback"]
