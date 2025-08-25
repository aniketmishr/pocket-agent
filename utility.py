
from pydantic import BaseModel
query_router_prompt = """
You are an AI assistant with two response modes:

1. Direct Response Mode (Simple Queries):
- If the user query is straightforward, factual, or conversational, answer directly using your own knowledge.
- Examples: greetings, trivia, factual lookups, simple definitions, short explanations.

2. Agent Mode (Complex Queries):
- If the user query requires multi-step reasoning, planning, or external tools (e.g., web search, database queries, calculations, document generation, scheduling, API calls), do not answer.
- ONLY reply with: AGENT
"""

from pydantic import BaseModel, Field
from typing import List
from openai import OpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class ClarificationResponse(BaseModel):
    summary: str = Field(
        ...,
        description=(
            "A very short and precise summary of the clarification. "
            "Do NOT include or mention any args, parameters, or technical details."
        )
    )
    choices: List[str] = Field(
        ...,
        description="A list of possible choices or options explicitly mentioned in the clarification."
    )

def get_structured_clarification(clarification_prompt:str, client:OpenAI) -> ClarificationResponse: 
    response = client.chat.completions.parse(
                    model="gpt-5-nano", 
                    messages=[
                        {"role": "user", "content": clarification_prompt}
                    ], 
                    response_format=ClarificationResponse
    )
    return response.choices[0].message.parsed

def build_inline_keyboard(clarification: ClarificationResponse) -> InlineKeyboardMarkup: 
    keyboard = [
        [InlineKeyboardButton(choice, callback_data=choice)]
        for choice in clarification.choices
    ]
    return InlineKeyboardMarkup(keyboard)


