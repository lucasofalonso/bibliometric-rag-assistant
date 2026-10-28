import json

import gradio as gr

from bibliometric_rag_assistant.agents.typed_agent_postgres import (
    TOOL_LABELS,
    instructions,
    run_agent,
)


def format_tool_call(entry: dict) -> gr.ChatMessage:
    # Each call becomes a collapsible block above the answer
    arguments = json.dumps(entry["arguments"], ensure_ascii=False, indent=2)
    status = entry["result"].get("status")

    return gr.ChatMessage(
        role="assistant",
        content=f"```json\n{arguments}\n```\nStatus: `{status}`",
        metadata={
            "title": f"🔧 {TOOL_LABELS.get(entry['tool'], entry['tool'])}",
            "status": "done",
        },
    )


def respond(message: str, chat_history: list, agent_history: list | None):
    # New conversation (first message or cleared chat): history from scratch.
    # agent_history also keeps the tool calls, which the interface's
    # chat_history does not have
    if not chat_history or agent_history is None:
        agent_history = [{"role": "developer", "content": instructions}]

    result = run_agent(message, history=agent_history, verbose=False)
    answer = result["answer"] or f"_No final answer ({result['stop_reason']})._"

    messages = [format_tool_call(entry) for entry in result["call_log"]]
    messages.append(gr.ChatMessage(role="assistant", content=answer))

    return messages, agent_history


agent_state = gr.State(None)

demo = gr.ChatInterface(
    respond,
    additional_inputs=[agent_state],
    additional_outputs=[agent_state],
    chatbot=gr.Chatbot(
        height=600,
        placeholder=(
            "**PubMed/Crossref Agent**<br>"
            "Ask about the current query, PMIDs or DOIs."
        ),
    ),
    title="PubMed/Crossref Agent",
    description="Bibliographic queries with typed tools over PubMed and Crossref.",
    analytics_enabled=False,
)


if __name__ == "__main__":
    demo.launch()
