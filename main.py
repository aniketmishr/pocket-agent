import os
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI
from dotenv import load_dotenv
from portia import (
    ActionClarification,
    InputClarification,
    MultipleChoiceClarification,
    PlanRunState,
    Portia,
    PortiaToolRegistry,
    Config
)

from custom_tool import get_tool_registry

load_dotenv()

system_prompt = """
You are an AI assistant with two response modes:

1. Direct Response Mode (Simple Queries):
- If the user query is straightforward, factual, or conversational, answer directly using your own knowledge.
- Examples: greetings, trivia, factual lookups, simple definitions, short explanations.

2. Agent Mode (Complex Queries):
- If the user query requires multi-step reasoning, planning, or external tools (e.g., web search, database queries, calculations, document generation, scheduling, API calls), do not answer.
- ONLY reply with: AGENT
"""

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tg-portia-bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_USERNAME = os.getenv("TELEGRAM_USERNAME")

class PocketAgent: 
    def __init__(self):
        self.portia_config = Config.from_default(default_model="google/gemini-2.5-flash", planning_model="openai/gpt-5-mini", execution_model = "google/gemini-2.5-flash")
        self.portia = Portia(tools=get_tool_registry(self.portia_config))
        self.openai_client = OpenAI()

    async def start(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "Hey! I’m your PocketAgent.\n\n"
            "• Send me any question and I’ll answer using Portia AI.\n"
            "• Use /help for tips."
        )


    async def help_cmd(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "How to use me:\n"
            "1) Type a question—general knowledge, code, math, etc.\n"
            "2) Ask follow-ups naturally, I’ll keep context in your message.\n"
        )

    async def ask(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        
        user = update.effective_user
        if not(user.username==TELEGRAM_USERNAME): 
            return 
        text = (update.message.text or "").strip()
        if not text:
            return

        # Show "typing..." while we think
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-5-nano", 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ]
            )
            if (response.choices[0].message.content =="AGENT"): 
                answer: str = self.run_portia_agent(query=text)
            else : 
                answer: str = response.choices[0].message.content

        except Exception as e:
            logger.exception("LLM call failed: %s", e)
            await update.message.reply_text(
                "Oops — I couldn’t generate a reply right now. Please try again."
            )
            return

        await update.message.reply_text(answer)

    async def unknown(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Catches non-text messages (stickers, photos, etc.).
        """
        await update.message.reply_text(
            "I currently understand text messages. Try typing a question or use /help."
        )


    async def error_handler(self,update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Global error logger to avoid crashes on unexpected errors.
        """
        logger.exception("Unhandled error while handling an update:", exc_info=context.error)

    def run_portia_agent(self, query:str) -> str : 
        # Generate the plan from the user query and print it
        plan = self.portia.plan(query)
        # print(f"{plan.model_dump_json(indent=2)}")

        # Run the plan
        plan_run = self.portia.run_plan(plan)

        while plan_run.state == PlanRunState.NEED_CLARIFICATION:
            # If clarifications are needed, resolve them before resuming the plan run
            for clarification in plan_run.get_outstanding_clarifications():
                # Usual handling of Input and Multiple Choice clarifications
                if isinstance(clarification, (InputClarification, MultipleChoiceClarification)):
                    print(f"{clarification.user_guidance}")
                    user_input = input("Please enter a value:\n" 
                                    + (("\n".join(clarification.options) + "\n") if "options" in clarification else ""))
                    plan_run = self.portia.resolve_clarification(clarification, user_input, plan_run)
                
                # Handling of Action clarifications
                if isinstance(clarification, ActionClarification):
                    print(f"{clarification.user_guidance} -- Please click on the link below to proceed.")
                    print(clarification.action_url)
                    plan_run = self.portia.wait_for_ready(plan_run)

            # Once clarifications are resolved, resume the plan run
            plan_run = self.portia.resume(plan_run)

        # Serialise into JSON and print the output
        print(f"{plan_run.model_dump_json(indent=2)}")
        print()
        return str(plan_run.outputs.final_output.value)


    def run(self) -> None:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Commands
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help_cmd))

        # Q&A for any plain text (excluding commands)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.ask))

        # Everything else (stickers / photos / etc.)
        app.add_handler(MessageHandler(~filters.TEXT, self.unknown))

        # Errors
        app.add_error_handler(self.error_handler)

        # Start long polling
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    agent = PocketAgent()
    agent.run()
