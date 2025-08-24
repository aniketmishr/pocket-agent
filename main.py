import os
import logging
import asyncio
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI
from dotenv import load_dotenv
from portia import (
    ActionClarification,
    InputClarification,
    MultipleChoiceClarification,
    UserVerificationClarification, 
    PlanRunState,
    Portia,
    PortiaToolRegistry,
    Config,
)
from portia.end_user import EndUser
from portia.execution_hooks import ExecutionHooks, clarify_on_tool_calls
from custom_tool import get_tool_registry
from workflows import daily_news_plan, tech_digest_plan
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
        self.portia = Portia(
            config=self.portia_config,
            tools=PortiaToolRegistry(self.portia_config), 
            execution_hooks=ExecutionHooks(
                before_tool_call=clarify_on_tool_calls(
                    [
                        'portia:google:gmail:send_email'
                    ]
                )
            )
            )
        # self.portia_end_user = EndUser()
        self.openai_client = OpenAI()
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.chat_id = None 
        self.pending_clarification : asyncio.Future | None = None 

    async def start(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.chat_id = update.effective_chat.id
        await update.message.reply_text(
            """
👋 Hey there! I’m PocketAgent 🚀  

✨ Got questions? I’ll solve them  
🛠  Need a hand? I’ll act for you  
⚡ Want ease? I’ll automate your life"""
        )


    async def help_cmd(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.chat_id = update.effective_chat.id
        await update.message.reply_text(
"""
🤖 How to use me:  
1️⃣ Ask me any question or query — I’ll help you out  
2️⃣ Need complex stuff done? I can take actions & reason it through  
3️⃣ Want automation? Try our built-in workflows → type /workflow  """
        )

    async def ask(self, text:str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.chat_id = update.effective_chat.id
        user = update.effective_user
        if not(user.username==TELEGRAM_USERNAME): 
            return 
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
                answer = await self.run_portia_agent(query=text)
            else : 
                answer: str = response.choices[0].message.content

        except Exception as e:
            logger.exception("LLM call failed: %s", e)
            await update.message.reply_text(
                "Oops,I couldn’t generate a reply right now. Please try again later."
            )
            return

        await update.message.reply_markdown(answer)

    async def unknown(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.chat_id = update.effective_chat.id
        """
        Catches non-text messages (stickers, photos, etc.).
        """
        await update.message.reply_text(
            "I currently understand text messages. Try typing a question or use /help."
        )

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE): 
        self.chat_id = update.effective_chat.id
        text = update.message.text.strip()

        # if there is a pending clarification, resolve it
        if self.pending_clarification and not self.pending_clarification.done(): 
            self.pending_clarification.set_result(text)
            return 
        
        asyncio.create_task(self.ask(text, update,context))

    async def notify_user(self,chat_id: int, text: str):
        await self.app.bot.send_message(chat_id=chat_id, text=text)

    async def error_handler(self,update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Global error logger to avoid crashes on unexpected errors.
        """
        logger.exception("Unhandled error while handling an update:", exc_info=context.error)

    async def run_portia_agent(self, query:str) -> str : 
        # Generate the plan from the user query and print it
        plan = self.portia.plan(query)
        print(f"{plan.model_dump_json(indent=2)}")
        # Run the plan
        plan_run = self.portia.run_plan(plan)
        while plan_run.state == PlanRunState.NEED_CLARIFICATION:
            # If clarifications are needed, resolve them before resuming the plan run
            for clarification in plan_run.get_outstanding_clarifications():
                # Usual handling of Input and Multiple Choice clarifications
                if isinstance(clarification, (InputClarification, MultipleChoiceClarification)):
                    print(f"{clarification.user_guidance}")
                    await self.notify_user(self.chat_id,
                        "Please enter a value:\n" 
                                    + (("\n".join(clarification.options) + "\n") if "options" in clarification else ""))
                    # Create a Future and wait for it
                    self.pending_clarification = asyncio.get_running_loop().create_future()
                    user_input = await self.pending_clarification
                    # self.pending_clarification = None   # TODO(Check if this is really required or not? )
                    plan_run = self.portia.resolve_clarification(clarification, user_input, plan_run)

                # handle User Verification Clarification : Human in the loop
                if isinstance(clarification, UserVerificationClarification) :
                    print(f"{clarification.user_guidance}")
                    await self.notify_user(self.chat_id,
                        # "Please enter a value:\n" +
                               f"{clarification.user_guidance}"   
                                )
                    self.pending_clarification = asyncio.get_running_loop().create_future()
                    user_input = await self.pending_clarification
                    plan_run = self.portia.resolve_clarification(clarification, user_input, plan_run)
        
                # Handling of Action clarifications
                if isinstance(clarification, ActionClarification):
                    await self.notify_user(
                        self.chat_id,
                        f"{clarification.user_guidance} -- Please click on the link below to proceed.\n"
                        f"[Click on this]({clarification.action_url})"
                        )
                    plan_run = self.portia.wait_for_ready(plan_run)

            # Once clarifications are resolved, resume the plan run
            plan_run = self.portia.resume(plan_run)

        # Serialise into JSON and print the output
        print(f"{plan_run.model_dump_json(indent=2)}")
        print()
        return str(plan_run.outputs.final_output.value)
    
    async def run_portia_workflow(self, workflow_id:str) -> str : 

        if workflow_id=="1" : 
            workflow_plan = daily_news_plan
        elif workflow_id=="2": 
            workflow_plan = tech_digest_plan
        else: 
            workflow_plan = None 
            return 

        plan_run = await self.portia.arun_plan(workflow_plan)
        while plan_run.state == PlanRunState.NEED_CLARIFICATION:
            # If clarifications are needed, resolve them before resuming the plan run
            for clarification in plan_run.get_outstanding_clarifications():
                # Usual handling of Input and Multiple Choice clarifications
                if isinstance(clarification, (InputClarification, MultipleChoiceClarification)):
                    print(f"{clarification.user_guidance}")
                    await self.notify_user(self.chat_id,
                        "Please enter a value:\n" 
                                    + (("\n".join(clarification.options) + "\n") if "options" in clarification else ""))
                    # Create a Future and wait for it
                    self.pending_clarification = asyncio.get_running_loop().create_future()
                    user_input = await self.pending_clarification
                    # self.pending_clarification = None   # TODO(Check if this is really required or not? )
                    plan_run = self.portia.resolve_clarification(clarification, user_input, plan_run)

                # handle User Verification Clarification : Human in the loop
                if isinstance(clarification, UserVerificationClarification) :
                    print(0)
                    print(f"{clarification.user_guidance}")
                    await self.notify_user(self.chat_id,
                        # "Please enter a value:\n" +
                               f"{clarification.user_guidance}"   
                                )  
                    self.pending_clarification = asyncio.get_running_loop().create_future()
                    user_input = await self.pending_clarification
                    plan_run = self.portia.resolve_clarification(clarification, user_input, plan_run)    
        
                # Handling of Action clarifications
                if isinstance(clarification, ActionClarification):
                    await self.notify_user(
                        self.chat_id,
                        f"{clarification.user_guidance} -- Please click on the link below to proceed.\n"
                        f"[Click on this]({clarification.action_url})"
                        )
                    plan_run = self.portia.wait_for_ready(plan_run)

            # Once clarifications are resolved, resume the plan run
            plan_run = self.portia.resume(plan_run)

        # Serialise into JSON and print the output
        print(f"{plan_run.model_dump_json(indent=2)}")
        print()
        return str(plan_run.outputs.final_output.value)
  
    async def workflow(self,update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: 
        if context.args: # arguments after the command
            workflow_id = context.args[0]
            workflow_out = await self.run_portia_workflow(workflow_id)
            await update.message.reply_markdown(f"{workflow_out}")
        else :
            await update.message.reply_html("""
<b>⚡ What is /workflow?</b>
Automate your boring <i>regular</i> stuff with just <b>one click</b>.  
<b>🚀 How to use /workflow</b>  
Type <code>/workflow &lt;workflow_id&gt;</code> to run your favorite workflow.  

<b>✅ Currently supported workflows:</b>  
🔹 <b>ID 1</b> → News Innovation Digest
🔹 <b>ID 2</b> → Tech Innovation Digest  
  

<b>✨ More cool workflows coming soon... stay tuned!</b>
                                            """)


    def run(self) -> None:
        # Commands
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help_cmd))

        # Q&A for any plain text (excluding commands)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handler))

        # Everything else (stickers / photos / etc.)
        self.app.add_handler(MessageHandler(~filters.TEXT, self.unknown))

        # Workflow Handler : Execute any workflow
        self.app.add_handler(CommandHandler("workflow", self.workflow))

        # Errors
        self.app.add_error_handler(self.error_handler)

        # Start long polling
        self.app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    agent = PocketAgent()
    agent.run()
